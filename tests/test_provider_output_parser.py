from __future__ import annotations

import unittest

from router.provider_output import ProviderOutput, parse_provider_generation, provider_output_to_generation
from router.providers.base import ProviderError


class ProviderOutputParserTests(unittest.TestCase):
    def test_parse_openai_chat_assistant_message_into_turns(self) -> None:
        turns = parse_provider_generation(
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

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "final"])
        self.assertEqual(turns[0].content, "hello from vllm")
        self.assertEqual(turns[1].metadata["provider_name"], "local_vllm")

    def test_parse_openai_chat_tool_call_detection(self) -> None:
        turns = parse_provider_generation(
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

        self.assertEqual([turn.type.value for turn in turns], ["assistant", "tool_call"])
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

    def test_provider_output_to_generation_rebuilds_public_response_shape(self) -> None:
        generation = provider_output_to_generation(
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

        self.assertTrue(generation.final)
        self.assertEqual(generation.message.role, "assistant")
        self.assertEqual(generation.message.content, "done")
        self.assertEqual(generation.provider_name, "openai_responses")
        self.assertEqual(generation.provider_slot, "openai_reasoning")
        self.assertEqual(generation.usage["total_tokens"], 14)


if __name__ == "__main__":
    unittest.main()
