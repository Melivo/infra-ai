from __future__ import annotations

import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from router.conversation import (
    AssistantTurn,
    ExecutionDependency,
    ExecutionDependencyOrigin,
    ExecutionPlan,
    ExecutionPlanNode,
    ExecutionStep,
    StepPhase,
    ToolCallTurn,
    DeclaredPlanNodeSpec,
    DeclaredPlanSpec,
)
from router.normalization import GenerationRequest
from router.provider_output import ParsedProviderStep, ProviderOutput
from router.providers.base import Provider
from router.tool_loop import ToolLoopEngine, ToolLoopError
from router.tools.core_tools import register_core_tools
from router.tools.example_tools import register_example_tools
from router.tools.orchestrator import ToolOrchestrator
from router.tools.policy import ToolPolicy
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext, ToolResult


class _StubProvider(Provider):
    name = "stub"

    def list_models(self):
        return 200, {"object": "list", "data": []}

    def generate(self, request: GenerationRequest) -> ProviderOutput:
        del request
        return ProviderOutput(
            format="openai_chat_completion",
            body={},
            provider_name=self.name,
        )


class _FailIfCalledOrchestrator:
    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        del call
        del ctx
        raise AssertionError("tool orchestrator should not be called")


class _CountingOrchestrator:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        del ctx
        self.calls += 1
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_json={"ok": True},
        )


class ToolLoopTests(unittest.TestCase):
    def _build_engine(self, *, workspace_root: str) -> ToolLoopEngine:
        registry = ToolRegistry()
        register_example_tools(registry)
        register_core_tools(registry)
        return ToolLoopEngine(
            tool_orchestrator=ToolOrchestrator(
                registry=registry,
                policy=ToolPolicy(),
            ),
            max_tool_steps=4,
            tool_timeout_s=1.0,
            workspace_root=workspace_root,
        )

    def test_tool_loop_rejects_non_progressing_plan_before_execution(self) -> None:
        engine = ToolLoopEngine(
            tool_orchestrator=_FailIfCalledOrchestrator(),
            max_tool_steps=4,
            tool_timeout_s=1.0,
        )
        parsed_step = ParsedProviderStep(
            turns=[
                AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN),
                ToolCallTurn(
                    tool_name="echo",
                    tool_call_id="call-1",
                    tool_arguments={"message": "hi"},
                ),
            ],
            step=ExecutionStep(
                planning_turns=[AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN)],
                declared_plan=DeclaredPlanSpec(
                    nodes=[
                        DeclaredPlanNodeSpec(
                            tool_call_id="call-1",
                            depends_on_call_ids=["missing-call"],
                        )
                    ]
                ),
                plan=ExecutionPlan(
                    nodes=[
                        ExecutionPlanNode(
                            tool_call=ToolCallTurn(
                                tool_name="echo",
                                tool_call_id="call-1",
                                tool_arguments={"message": "hi"},
                            ),
                            declared_dependencies=[
                                ExecutionDependency(
                                    call_id="missing-call",
                                    origin=ExecutionDependencyOrigin.DECLARED,
                                )
                            ],
                        )
                    ]
                ),
            ),
        )

        with patch("router.tool_loop.parse_provider_step", return_value=parsed_step):
            with self.assertRaises(ToolLoopError) as exc_info:
                asyncio.run(
                    engine.run(
                        provider=_StubProvider(),
                        request=GenerationRequest(turns=[], tools=[]),
                        request_id="req-1",
                        allowed_tools={"echo"},
                    )
                )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")

    def test_tool_loop_rejects_blocked_nodes_after_partial_execution(self) -> None:
        orchestrator = _CountingOrchestrator()
        engine = ToolLoopEngine(
            tool_orchestrator=orchestrator,
            max_tool_steps=4,
            tool_timeout_s=1.0,
        )
        planning_turn = AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN)
        parsed_step = ParsedProviderStep(
            turns=[
                planning_turn,
                ToolCallTurn(
                    tool_name="echo",
                    tool_call_id="call-1",
                    tool_arguments={"message": "hi"},
                ),
                ToolCallTurn(
                    tool_name="add_numbers",
                    tool_call_id="call-2",
                    tool_arguments={"a": 2, "b": 3},
                ),
            ],
            step=ExecutionStep(
                planning_turns=[planning_turn],
                declared_plan=DeclaredPlanSpec(
                    nodes=[
                        DeclaredPlanNodeSpec(tool_call_id="call-1"),
                        DeclaredPlanNodeSpec(
                            tool_call_id="call-2",
                            depends_on_call_ids=["missing-call"],
                        ),
                    ]
                ),
                plan=ExecutionPlan(
                    nodes=[
                        ExecutionPlanNode(
                            tool_call=ToolCallTurn(
                                tool_name="echo",
                                tool_call_id="call-1",
                                tool_arguments={"message": "hi"},
                            ),
                        ),
                        ExecutionPlanNode(
                            tool_call=ToolCallTurn(
                                tool_name="add_numbers",
                                tool_call_id="call-2",
                                tool_arguments={"a": 2, "b": 3},
                            ),
                            declared_dependencies=[
                                ExecutionDependency(
                                    call_id="missing-call",
                                    origin=ExecutionDependencyOrigin.DECLARED,
                                )
                            ],
                        ),
                    ]
                ),
            ),
        )

        with patch("router.tool_loop.parse_provider_step", return_value=parsed_step):
            with self.assertRaises(ToolLoopError) as exc_info:
                asyncio.run(
                    engine.run(
                        provider=_StubProvider(),
                        request=GenerationRequest(turns=[], tools=[]),
                        request_id="req-2",
                        allowed_tools={"echo", "add_numbers"},
                    )
                )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")
        self.assertEqual(orchestrator.calls, 1)

    def test_run_tool_call_executes_filesystem_read_through_existing_orchestrator_path(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_root:
            file_path = f"{workspace_root}/note.txt"
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("hello from tool loop")

            result = asyncio.run(
                self._build_engine(workspace_root=workspace_root).run_tool_call(
                    tool_call=ToolCall(
                        call_id="call-read",
                        name="filesystem.read",
                        arguments={"path": "note.txt"},
                    ),
                    request_id="req-read",
                    current_tool_step=0,
                    allowed_tools={"filesystem.read"},
                )
            )

        self.assertEqual(result.name, "filesystem.read")
        self.assertEqual(result.ok, True)
        self.assertIsInstance(result.output_json, dict)
        self.assertEqual(result.output_json["path"], "note.txt")
        self.assertEqual(result.output_json["content"], "hello from tool loop")

    def test_run_tool_call_returns_failed_result_for_workspace_boundary_violation(self) -> None:
        """ToolArgumentsValidationError must become ToolResult(ok=False), not crash the loop."""
        with tempfile.TemporaryDirectory() as workspace_root:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write("outside workspace")
                outside_path = handle.name

            result = asyncio.run(
                self._build_engine(workspace_root=workspace_root).run_tool_call(
                    tool_call=ToolCall(
                        call_id="call-read-outside",
                        name="filesystem.read",
                        arguments={"path": outside_path},
                    ),
                    request_id="req-outside",
                    current_tool_step=0,
                    allowed_tools={"filesystem.read"},
                )
            )
            Path(outside_path).unlink(missing_ok=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "invalid_tool_arguments")

    def test_allowed_tools_blocks_new_core_tools_when_not_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as workspace_root:
            file_path = f"{workspace_root}/note.txt"
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("hello")

            with self.assertRaises(ToolLoopError) as exc_info:
                asyncio.run(
                    self._build_engine(workspace_root=workspace_root).run_tool_call(
                        tool_call=ToolCall(
                            call_id="call-blocked",
                            name="filesystem.read",
                            arguments={"path": "note.txt"},
                        ),
                        request_id="req-blocked",
                        current_tool_step=0,
                        allowed_tools=set(),
                    )
                )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "tool_not_allowed")


if __name__ == "__main__":
    unittest.main()
