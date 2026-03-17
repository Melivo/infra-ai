from __future__ import annotations

import unittest

from router.conversation import (
    DeclaredPlanNodeSpec,
    DeclaredPlanSpec,
    ExecutionDependencyOrigin,
    ExecutionNodeStatus,
    StepPhase,
    turns_to_generation,
)
from router.provider_output import ProviderOutput, parse_provider_generation, parse_provider_step
from router.providers.base import ProviderError


class ProviderOutputParserTests(unittest.TestCase):
    def test_parse_openai_chat_assistant_message_into_turns(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_chat_completion",
                body={
                    "id": "chatcmpl-1",
                    "model": "Qwen",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "hello from vllm",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
                provider_name="local_vllm",
                fallback_model="Qwen",
            )
        )
        turns = parsed.turns

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "final"])
        self.assertEqual(turns[0].content, "hello from vllm")
        self.assertEqual(turns[1].metadata["provider_name"], "local_vllm")

    def test_parse_openai_chat_tool_call_detection(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_chat_completion",
                body={
                    "id": "chatcmpl-2",
                    "model": "Qwen",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "type": "function",
                                        "function": {
                                            "name": "add_numbers",
                                            "arguments": "{\"a\": 2, \"b\": 3}",
                                        },
                                    }
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                },
                provider_name="local_vllm",
                fallback_model="Qwen",
            )
        )
        turns = parsed.turns

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "tool_call"])
        self.assertEqual(parsed.step.planning_turns[-1].phase, StepPhase.TOOL_PLAN)
        self.assertEqual(len(parsed.step.plan.nodes), 1)
        self.assertEqual(parsed.step.plan.nodes[0].status, ExecutionNodeStatus.PLANNED)
        self.assertEqual(parsed.step.plan.nodes[0].declared_dependency_call_ids, [])
        self.assertEqual(parsed.step.plan.nodes[0].strategy_dependency_call_ids, [])
        self.assertEqual(parsed.step.declared_plan.nodes[0].depends_on_call_ids, [])
        self.assertEqual(turns[1].tool_name, "add_numbers")
        self.assertEqual(turns[1].tool_arguments, {"a": 2, "b": 3})

    def test_parse_openai_chat_invalid_tool_call_raises_provider_error(self) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            parse_provider_generation(
                ProviderOutput(
                    format="openai_chat_completion",
                    body={
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "function": {
                                                "name": " ",
                                                "arguments": "{}",
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    provider_name="local_vllm",
                    fallback_model="Qwen",
                )
            )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")

    def test_parse_openai_responses_tool_call_detection(self) -> None:
        turns = parse_provider_generation(
            ProviderOutput(
                format="openai_responses",
                body={
                    "id": "resp-1",
                    "model": "gpt-5.2",
                    "status": "in_progress",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": "{\"message\": \"hi\"}",
                        }
                    ],
                },
                provider_name="openai_responses",
                provider_slot="openai_reasoning",
                fallback_model="gpt-5.2",
            )
        )

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "tool_call"])
        self.assertEqual(turns[1].tool_name, "echo")
        self.assertEqual(turns[1].tool_arguments, {"message": "hi"})

    def test_parse_openai_chat_multiple_tool_calls_preserves_all_turns(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_chat_completion",
                body={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "echo",
                                            "arguments": "{\"message\": \"hi\"}",
                                        },
                                    },
                                    {
                                        "id": "call-2",
                                        "function": {
                                            "name": "add_numbers",
                                            "arguments": "{\"a\": 2, \"b\": 3}",
                                        },
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                provider_name="local_vllm",
                fallback_model="Qwen",
            )
        )
        turns = parsed.turns

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "tool_call", "tool_call"])
        self.assertEqual([turn.tool_name for turn in turns[1:]], ["echo", "add_numbers"])
        self.assertEqual(parsed.step.plan.nodes[1].declared_dependency_call_ids, [])
        self.assertEqual(parsed.step.plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(parsed.step.plan.nodes[1].dependencies[0].origin, ExecutionDependencyOrigin.EXECUTION_STRATEGY)

    def test_parse_openai_chat_declared_dependencies_remain_separate_from_strategy(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_chat_completion",
                body={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "echo",
                                            "arguments": "{\"message\": \"hi\"}",
                                        },
                                    },
                                    {
                                        "id": "call-2",
                                        "depends_on_call_ids": ["call-1"],
                                        "function": {
                                            "name": "add_numbers",
                                            "arguments": "{\"a\": 2, \"b\": 3}",
                                        },
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
                provider_name="local_vllm",
                fallback_model="Qwen",
            )
        )

        self.assertEqual(parsed.step.plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(parsed.step.plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(
            [dependency.origin for dependency in parsed.step.plan.nodes[1].dependencies],
            [
                ExecutionDependencyOrigin.DECLARED,
                ExecutionDependencyOrigin.EXECUTION_STRATEGY,
            ],
        )
        self.assertEqual(parsed.step.declared_plan.nodes[1].depends_on_call_ids, ["call-1"])

    def test_parse_openai_chat_unknown_declared_dependency_raises_provider_error(self) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            parse_provider_step(
                ProviderOutput(
                    format="openai_chat_completion",
                    body={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "depends_on_call_ids": ["missing-call"],
                                            "function": {
                                                "name": "echo",
                                                "arguments": "{\"message\": \"hi\"}",
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": "tool_calls",
                            }
                        ]
                    },
                    provider_name="local_vllm",
                    fallback_model="Qwen",
                )
            )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")

    def test_parse_openai_responses_declared_dependencies_remain_separate_from_strategy(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_responses",
                body={
                    "id": "resp-1",
                    "model": "gpt-5.2",
                    "status": "in_progress",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": "{\"message\": \"hi\"}",
                        },
                        {
                            "type": "function_call",
                            "call_id": "call-2",
                            "name": "add_numbers",
                            "arguments": "{\"a\": 2, \"b\": 3}",
                            "depends_on_call_ids": ["call-1"],
                        },
                    ],
                },
                provider_name="openai_responses",
                provider_slot="openai_reasoning",
                fallback_model="gpt-5.2",
            )
        )

        self.assertEqual(parsed.step.plan.nodes[1].declared_dependency_call_ids, ["call-1"])
        self.assertEqual(parsed.step.plan.nodes[1].strategy_dependency_call_ids, ["call-1"])
        self.assertEqual(
            [dependency.origin for dependency in parsed.step.plan.nodes[1].dependencies],
            [
                ExecutionDependencyOrigin.DECLARED,
                ExecutionDependencyOrigin.EXECUTION_STRATEGY,
            ],
        )
        self.assertEqual(parsed.step.declared_plan.nodes[1].depends_on_call_ids, ["call-1"])

    def test_parse_openai_responses_exposes_declared_plan_spec(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="openai_responses",
                body={
                    "id": "resp-2",
                    "model": "gpt-5.2",
                    "status": "in_progress",
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": "{\"message\": \"hi\"}",
                        },
                        {
                            "type": "function_call",
                            "call_id": "call-2",
                            "name": "add_numbers",
                            "arguments": "{\"a\": 2, \"b\": 3}",
                            "depends_on_call_ids": ["call-1"],
                        },
                    ],
                },
                provider_name="openai_responses",
                provider_slot="openai_reasoning",
                fallback_model="gpt-5.2",
            )
        )

        self.assertEqual(
            parsed.step.declared_plan,
            DeclaredPlanSpec(
                nodes=[
                    DeclaredPlanNodeSpec(tool_call_id="call-1"),
                    DeclaredPlanNodeSpec(tool_call_id="call-2", depends_on_call_ids=["call-1"]),
                ]
            ),
        )

    def test_parse_openai_responses_unknown_declared_dependency_raises_provider_error(self) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            parse_provider_step(
                ProviderOutput(
                    format="openai_responses",
                    body={
                        "id": "resp-1",
                        "model": "gpt-5.2",
                        "status": "in_progress",
                        "output": [
                            {
                                "type": "function_call",
                                "call_id": "call-1",
                                "name": "echo",
                                "arguments": "{\"message\": \"hi\"}",
                                "depends_on_call_ids": ["missing-call"],
                            }
                        ],
                    },
                    provider_name="openai_responses",
                    provider_slot="openai_reasoning",
                    fallback_model="gpt-5.2",
                )
            )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")

    def test_parser_turns_rebuild_public_response_shape_via_compat_boundary(self) -> None:
        generation = turns_to_generation(
            parse_provider_generation(
                ProviderOutput(
                    format="openai_responses",
                    body={
                        "id": "resp-2",
                        "model": "gpt-5.2",
                        "status": "completed",
                        "output_text": "done",
                        "output": [],
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 4,
                            "total_tokens": 14,
                        },
                    },
                    provider_name="openai_responses",
                    provider_slot="openai_reasoning",
                    fallback_model="gpt-5.2",
                )
            )
        )

        self.assertTrue(generation.final)
        self.assertEqual(generation.message.role, "assistant")
        self.assertEqual(generation.message.content, "done")
        self.assertEqual(generation.provider_name, "openai_responses")
        self.assertEqual(generation.provider_slot, "openai_reasoning")
        self.assertEqual(generation.usage["total_tokens"], 14)

    def test_parse_gemini_fallback_returns_assistant_and_final_turns(self) -> None:
        parsed = parse_provider_step(
            ProviderOutput(
                format="gemini_generate_content",
                body={
                    "candidates": [
                        {
                            "finishReason": "STOP",
                            "content": {
                                "parts": [
                                    {"text": "gemini"},
                                    {"text": " result"},
                                ]
                            },
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 5,
                        "candidatesTokenCount": 3,
                        "totalTokenCount": 8,
                    },
                },
                provider_name="gemini_fallback",
                fallback_model="gemini-2.5-pro",
            )
        )
        turns = parsed.turns

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "final"])
        self.assertEqual(parsed.step.finalization_turns[-1].phase, StepPhase.FINALIZATION)
        self.assertEqual(parsed.step.final.content, "gemini result")
        self.assertEqual(turns[0].content, "gemini result")
        self.assertEqual(turns[1].metadata["provider_name"], "gemini_fallback")
        self.assertEqual(turns[1].metadata["finish_reason"], "stop")
        self.assertEqual(turns[1].metadata["usage"]["total_tokens"], 8)


if __name__ == "__main__":
    unittest.main()
