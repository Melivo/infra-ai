from __future__ import annotations

import asyncio
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
                plan=ExecutionPlan(
                    declared_plan=DeclaredPlanSpec(
                        nodes=[
                            DeclaredPlanNodeSpec(
                                tool_call_id="call-1",
                                depends_on_call_ids=["missing-call"],
                            )
                        ]
                    ),
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
                plan=ExecutionPlan(
                    declared_plan=DeclaredPlanSpec(
                        nodes=[
                            DeclaredPlanNodeSpec(tool_call_id="call-1"),
                            DeclaredPlanNodeSpec(
                                tool_call_id="call-2",
                                depends_on_call_ids=["missing-call"],
                            ),
                        ]
                    ),
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


if __name__ == "__main__":
    unittest.main()
