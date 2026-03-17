from __future__ import annotations

import unittest

from router.conversation import (
    AssistantTurn,
    DECLARED_DEPENDENCY_METADATA_KEY,
    DeclaredPlanNodeSpec,
    DeclaredPlanSpec,
    ExecutionDependency,
    ExecutionDependencyOrigin,
    ExecutionNodeStatus,
    ExecutionPlan,
    ExecutionPlanNode,
    ExecutionPlanValidationError,
    ExecutionStep,
    ExecutionStrategy,
    FinalTurn,
    StepPhase,
    ToolCallTurn,
    ToolResultTurn,
    TurnType,
    UserTurn,
    apply_tool_result_to_step,
    append_declared_plan_node,
    build_execution_plan,
    compute_executable_plan_nodes,
    create_declared_execution_plan,
    declared_plan_spec_from_tool_calls,
    execution_steps_from_turns,
    generation_to_turns,
    mark_plan_node_completed,
    messages_to_turns,
    next_executable_plan_nodes,
    turns_to_generation,
    turns_to_messages,
    validate_execution_plan,
)
from router.normalization import GenerationRequest, NormalizedGeneration, NormalizedMessage, NormalizedToolCall


class ConversationTurnsTests(unittest.TestCase):
    def test_messages_to_turns_split_assistant_tool_call_structure(self) -> None:
        messages = [
            NormalizedMessage(role="user", content="sum this"),
            NormalizedMessage(
                role="assistant",
                content="Calling a tool.",
                tool_calls=[
                    NormalizedToolCall(
                        call_id="call-1",
                        name="add_numbers",
                        arguments={"a": 2, "b": 3},
                    )
                ],
            ),
            NormalizedMessage(
                role="tool",
                content_json={"result": 5},
                tool_call_id="call-1",
                tool_name="add_numbers",
                metadata={"ok": True},
            ),
        ]

        turns = messages_to_turns(messages)

        self.assertEqual(
            [turn.type for turn in turns],
            [
                TurnType.USER,
                TurnType.ASSISTANT,
                TurnType.TOOL_CALL,
                TurnType.TOOL_RESULT,
            ],
        )
        self.assertEqual(turns[0].role, "user")
        self.assertEqual(turns[1].content, "Calling a tool.")
        self.assertEqual(turns[2].tool_name, "add_numbers")
        self.assertEqual(turns[2].tool_call_id, "call-1")
        self.assertEqual(turns[2].tool_arguments, {"a": 2, "b": 3})
        self.assertEqual(turns[3].content_json, {"result": 5})
        self.assertEqual(turns[3].tool_name, "add_numbers")

    def test_turns_to_messages_rebuild_provider_visible_messages(self) -> None:
        turns = [
            UserTurn(role="system", content="Be concise."),
            UserTurn(role="user", content="sum this"),
            AssistantTurn(content="Calling a tool."),
            ToolCallTurn(
                tool_name="add_numbers",
                tool_call_id="call-1",
                tool_arguments={"a": 2, "b": 3},
            ),
            ToolResultTurn(
                content_json={"result": 5},
                tool_name="add_numbers",
                tool_call_id="call-1",
                metadata={"ok": True},
            ),
            FinalTurn(content="done"),
        ]

        messages = turns_to_messages(turns)

        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")
        self.assertEqual(messages[2].role, "assistant")
        self.assertEqual(messages[2].content, "Calling a tool.")
        self.assertEqual(len(messages[2].tool_calls), 1)
        self.assertEqual(messages[2].tool_calls[0].name, "add_numbers")
        self.assertEqual(messages[2].tool_calls[0].arguments, {"a": 2, "b": 3})
        self.assertEqual(messages[3].role, "tool")
        self.assertEqual(messages[3].content_json, {"result": 5})

        messages_with_final = turns_to_messages(turns, include_final=True)
        self.assertEqual(len(messages_with_final), 5)
        self.assertEqual(messages_with_final[-1].role, "assistant")
        self.assertEqual(messages_with_final[-1].content, "done")

    def test_generation_to_turns_adds_final_marker_without_changing_assistant_turn(self) -> None:
        generation = NormalizedGeneration(
            message=NormalizedMessage(role="assistant", content="done"),
            final=True,
            finish_reason="stop",
            response_id="resp-1",
            model="gpt-test",
            provider_name="provider-test",
            provider_slot="slot-test",
        )

        turns = generation_to_turns(generation)

        self.assertEqual([turn.type for turn in turns], [TurnType.ASSISTANT, TurnType.FINAL])
        self.assertEqual(turns[0].content, "done")
        self.assertEqual(turns[1].content, "done")
        self.assertEqual(turns[1].metadata["finish_reason"], "stop")
        self.assertEqual(turns[1].metadata["response_id"], "resp-1")
        self.assertEqual(turns[1].metadata["provider_name"], "provider-test")

    def test_turns_to_generation_uses_latest_assistant_segment(self) -> None:
        turns = [
            UserTurn(role="user", content="plan something"),
            AssistantTurn(content="thinking"),
            AssistantTurn(content="calling tools", phase=StepPhase.TOOL_PLAN),
            ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
            ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
        ]

        steps = execution_steps_from_turns(turns)
        generation = turns_to_generation(turns)

        self.assertEqual(len(steps), 1)
        self.assertIsInstance(steps[-1], ExecutionStep)
        self.assertEqual([turn.content for turn in steps[-1].reasoning_turns], ["thinking"])
        self.assertEqual([turn.phase for turn in steps[-1].reasoning_turns], [StepPhase.REASONING])
        self.assertEqual([turn.phase for turn in steps[-1].planning_turns], [StepPhase.TOOL_PLAN])
        self.assertEqual(steps[-1].planning_turns[-1].content, "calling tools")
        self.assertEqual(len(steps[-1].tool_calls), 2)
        self.assertEqual(len(steps[-1].plan.nodes), 2)
        self.assertIsInstance(steps[-1].plan.nodes[0], ExecutionPlanNode)
        self.assertEqual(steps[-1].plan.nodes[0].declared_dependency_call_ids, [])
        self.assertEqual(steps[-1].plan.nodes[0].strategy_dependency_call_ids, [])
        self.assertEqual(steps[-1].plan.nodes[0].depends_on_call_ids, [])
        self.assertEqual(steps[-1].plan.nodes[1].declared_dependency_call_ids, [])
        self.assertEqual(steps[-1].plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(steps[-1].plan.nodes[1].depends_on_call_ids, ["call-1"])
        self.assertEqual(steps[-1].plan.nodes[1].dependencies[0].origin, ExecutionDependencyOrigin.EXECUTION_STRATEGY)
        self.assertEqual(steps[-1].declared_plan.nodes[1].depends_on_call_ids, [])
        self.assertEqual(generation.message.content, "calling tools")
        self.assertEqual([tool_call.name for tool_call in generation.message.tool_calls], ["echo", "add_numbers"])

    def test_declared_plan_dependencies_stay_distinct_from_strategy_dependencies(self) -> None:
        plan = create_declared_execution_plan()
        plan = append_declared_plan_node(
            plan,
            ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
        )
        plan = append_declared_plan_node(
            plan,
            ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            depends_on_call_ids=["call-1"],
        )
        validate_execution_plan(plan)

        self.assertEqual(plan.nodes[0].declared_dependency_call_ids, [])
        self.assertEqual(plan.nodes[0].strategy_dependency_call_ids, [])
        self.assertEqual(plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(plan.nodes[1].strategy_dependency_call_ids, [])
        self.assertEqual(plan.nodes[1].dependencies[0].origin, ExecutionDependencyOrigin.DECLARED)

    def test_build_execution_plan_derives_strategy_dependencies_after_declaration(self) -> None:
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            ]
        )

        self.assertEqual(plan.nodes[0].declared_dependency_call_ids, [])
        self.assertEqual(plan.nodes[0].strategy_dependency_call_ids, [])
        self.assertEqual(plan.nodes[1].declared_dependency_call_ids, [])
        self.assertEqual(plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(plan.nodes[1].depends_on_call_ids, ["call-1"])

    def test_build_execution_plan_prefers_explicit_declared_plan_spec_over_turn_field(self) -> None:
        declared_plan = DeclaredPlanSpec(
            nodes=[
                DeclaredPlanNodeSpec(tool_call_id="call-1"),
                DeclaredPlanNodeSpec(tool_call_id="call-2", depends_on_call_ids=["call-1"]),
            ]
        )
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(
                    tool_name="add_numbers",
                    tool_call_id="call-2",
                    tool_arguments={"a": 2, "b": 3},
                    declared_dependency_call_ids=["wrong-call"],
                ),
            ],
            declared_plan=declared_plan,
        )

        self.assertEqual(plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(plan.nodes[1].strategy_dependency_call_ids, ["call-1"])

    def test_build_execution_plan_uses_tool_call_metadata_for_declared_dependencies(self) -> None:
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(
                    tool_name="add_numbers",
                    tool_call_id="call-2",
                    tool_arguments={"a": 2, "b": 3},
                    declared_dependency_call_ids=["call-1"],
                ),
            ]
        )

        self.assertEqual(plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(
            [dependency.origin for dependency in plan.nodes[1].dependencies],
            [
                ExecutionDependencyOrigin.DECLARED,
                ExecutionDependencyOrigin.EXECUTION_STRATEGY,
            ],
        )

    def test_append_declared_plan_node_rejects_unknown_declared_dependency(self) -> None:
        with self.assertRaises(ExecutionPlanValidationError):
            append_declared_plan_node(
                create_declared_execution_plan(),
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                depends_on_call_ids=["missing-call"],
            )

    def test_build_execution_plan_rejects_duplicate_tool_call_ids(self) -> None:
        with self.assertRaises(ExecutionPlanValidationError):
            build_execution_plan(
                [
                    ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                    ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "again"}),
                ]
            )

    def test_validate_execution_plan_rejects_cyclic_dependencies(self) -> None:
        plan = ExecutionPlan(
            strategy=ExecutionStrategy.SEQUENTIAL,
            nodes=[
                ExecutionPlanNode(
                    tool_call=ToolCallTurn(
                        tool_name="echo",
                        tool_call_id="call-1",
                        tool_arguments={"message": "hi"},
                    ),
                    declared_dependencies=[
                        ExecutionDependency(
                            call_id="call-2",
                            origin=ExecutionDependencyOrigin.DECLARED,
                        )
                    ],
                ),
                ExecutionPlanNode(
                    tool_call=ToolCallTurn(
                        tool_name="add_numbers",
                        tool_call_id="call-2",
                        tool_arguments={"a": 2, "b": 3},
                    ),
                    declared_dependencies=[
                        ExecutionDependency(
                            call_id="call-1",
                            origin=ExecutionDependencyOrigin.DECLARED,
                        )
                    ],
                ),
            ],
        )

        with self.assertRaises(ExecutionPlanValidationError):
            validate_execution_plan(plan)

    def test_generation_request_uses_turns_as_primary_internal_state(self) -> None:
        request = GenerationRequest.from_messages(
            messages=[NormalizedMessage(role="user", content="hi")],
            tools=[],
            metadata={"request_id": "req-1"},
        )

        self.assertEqual([turn.type for turn in request.turns], [TurnType.USER])
        self.assertEqual(request.messages[0].role, "user")
        self.assertEqual(request.messages[0].content, "hi")
        self.assertEqual(request.to_provider_messages()[0].content, "hi")

    def test_execution_steps_attach_tool_results_to_same_step(self) -> None:
        turns = [
            AssistantTurn(content="plan"),
            ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
            ToolResultTurn(tool_name="echo", tool_call_id="call-1", content_json={"message": "hi"}),
            ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            ToolResultTurn(tool_name="add_numbers", tool_call_id="call-2", content_json={"sum": 5}),
        ]

        steps = execution_steps_from_turns(turns)

        self.assertEqual(len(steps), 1)
        self.assertEqual([turn.tool_name for turn in steps[0].tool_calls], ["echo", "add_numbers"])
        self.assertEqual([turn.tool_name for turn in steps[0].tool_results], ["echo", "add_numbers"])
        self.assertEqual([node.declared_dependency_call_ids for node in steps[0].plan.nodes], [[], []])
        self.assertEqual([node.strategy_dependency_call_ids for node in steps[0].plan.nodes], [[], ["call-1"]])
        self.assertEqual([node.depends_on_call_ids for node in steps[0].plan.nodes], [[], ["call-1"]])
        self.assertEqual([node.status for node in steps[0].plan.nodes], [ExecutionNodeStatus.COMPLETED, ExecutionNodeStatus.COMPLETED])

    def test_execution_steps_rebuild_declared_dependencies_from_tool_call_turns(self) -> None:
        turns = [
            AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN),
            ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
            ToolCallTurn(
                tool_name="add_numbers",
                tool_call_id="call-2",
                tool_arguments={"a": 2, "b": 3},
                declared_dependency_call_ids=["call-1"],
            ),
        ]

        steps = execution_steps_from_turns(turns)

        self.assertEqual(steps[0].declared_plan.nodes[1].depends_on_call_ids, ["call-1"])
        self.assertEqual(steps[0].plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(steps[0].plan.nodes[1].strategy_dependency_call_ids, ["call-1"])

    def test_turns_to_generation_preserves_declared_dependency_metadata_at_boundary(self) -> None:
        turns = [
            AssistantTurn(content="calling tools", phase=StepPhase.TOOL_PLAN),
            ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
            ToolCallTurn(
                tool_name="add_numbers",
                tool_call_id="call-2",
                tool_arguments={"a": 2, "b": 3},
                declared_dependency_call_ids=["call-1"],
            ),
        ]

        generation = turns_to_generation(turns)

        self.assertEqual(generation.message.tool_calls[1].metadata[DECLARED_DEPENDENCY_METADATA_KEY], ["call-1"])

    def test_execution_steps_classify_finalization_phase(self) -> None:
        turns = [
            AssistantTurn(content="draft"),
            AssistantTurn(content="final answer", phase=StepPhase.FINALIZATION),
            FinalTurn(content="final answer"),
        ]

        steps = execution_steps_from_turns(turns)

        self.assertEqual(len(steps), 1)
        self.assertEqual([turn.phase for turn in steps[0].reasoning_turns], [StepPhase.REASONING])
        self.assertEqual([turn.phase for turn in steps[0].finalization_turns], [StepPhase.FINALIZATION])

    def test_apply_tool_result_updates_explicit_execution_plan_state(self) -> None:
        step = ExecutionStep(
            planning_turns=[AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN)],
            declared_plan=DeclaredPlanSpec(
                nodes=[
                    DeclaredPlanNodeSpec(tool_call_id="call-1"),
                    DeclaredPlanNodeSpec(tool_call_id="call-2"),
                ]
            ),
            plan=build_execution_plan(
                [
                    ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                    ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
                ]
            ),
        )

        updated = apply_tool_result_to_step(
            step,
            ToolResultTurn(tool_name="echo", tool_call_id="call-1", content_json={"message": "hi"}),
        )

        self.assertEqual(updated.plan.nodes[0].status, ExecutionNodeStatus.COMPLETED)
        self.assertEqual(updated.plan.nodes[0].result.content_json, {"message": "hi"})
        self.assertEqual(updated.plan.nodes[1].status, ExecutionNodeStatus.PLANNED)
        self.assertEqual(updated.declared_plan.nodes[0].depends_on_call_ids, [])
        self.assertEqual(updated.declared_plan.nodes[1].depends_on_call_ids, [])

    def test_mark_plan_node_completed_only_mutates_execution_progress(self) -> None:
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            ]
        )

        updated_plan = mark_plan_node_completed(
            plan,
            ToolResultTurn(tool_name="echo", tool_call_id="call-1", content_json={"message": "hi"}),
        )

        self.assertEqual(updated_plan.nodes[0].status, ExecutionNodeStatus.COMPLETED)
        self.assertEqual(updated_plan.nodes[0].result.content_json, {"message": "hi"})
        self.assertEqual(updated_plan.nodes[0].strategy_dependency_call_ids, [])
        self.assertEqual(updated_plan.nodes[1].status, ExecutionNodeStatus.PLANNED)
        self.assertEqual(updated_plan.nodes[1].strategy_dependency_call_ids, ["call-1"])

    def test_execution_step_carries_explicit_declared_plan_separately_from_execution_plan(self) -> None:
        declared_plan = DeclaredPlanSpec(
            nodes=[
                DeclaredPlanNodeSpec(tool_call_id="call-1"),
                DeclaredPlanNodeSpec(tool_call_id="call-2", depends_on_call_ids=["call-1"]),
            ]
        )
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            ],
            declared_plan=declared_plan,
        )
        step = ExecutionStep(
            planning_turns=[AssistantTurn(content="plan", phase=StepPhase.TOOL_PLAN)],
            declared_plan=declared_plan,
            plan=plan,
        )

        self.assertEqual(step.declared_plan.nodes[1].depends_on_call_ids, ["call-1"])
        self.assertEqual(step.plan.nodes[1].declared_dependency_call_ids, ["call-1"])

    def test_next_executable_plan_nodes_follow_dependency_and_node_state(self) -> None:
        plan = build_execution_plan(
            [
                ToolCallTurn(tool_name="echo", tool_call_id="call-1", tool_arguments={"message": "hi"}),
                ToolCallTurn(tool_name="add_numbers", tool_call_id="call-2", tool_arguments={"a": 2, "b": 3}),
            ]
        )

        first_nodes = compute_executable_plan_nodes(plan)
        updated_step = apply_tool_result_to_step(
            ExecutionStep(
                declared_plan=declared_plan_spec_from_tool_calls(
                    [node.tool_call for node in plan.nodes]
                ),
                plan=plan,
            ),
            ToolResultTurn(tool_name="echo", tool_call_id="call-1", content_json={"message": "hi"}),
        )
        second_nodes = next_executable_plan_nodes(updated_step.plan)

        self.assertEqual([node.tool_call.tool_call_id for node in first_nodes], ["call-1"])
        self.assertEqual([node.tool_call.tool_call_id for node in second_nodes], ["call-2"])


if __name__ == "__main__":
    unittest.main()
