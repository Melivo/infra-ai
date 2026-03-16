from __future__ import annotations

import unittest

from router.providers.base import ProviderError
from router.providers.local_vllm import _normalize_openai_chat_response
from router.providers.openai.responses import _normalize_response


class ProviderNormalizationTests(unittest.TestCase):
    def test_local_vllm_normalizes_openai_style_tool_call(self) -> None:
        generation = _normalize_openai_chat_response(
            {
                "id": "chatcmpl-local",
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
            provider_slot=None,
            fallback_model="Qwen",
        )

        self.assertEqual(generation.message.tool_calls[0].name, "add_numbers")
        self.assertEqual(generation.message.tool_calls[0].arguments, {"a": 2, "b": 3})
        self.assertFalse(generation.final)

    def test_local_vllm_rejects_blank_tool_name(self) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            _normalize_openai_chat_response(
                {
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
                provider_slot=None,
                fallback_model="Qwen",
            )

        self.assertEqual(
            exc_info.exception.payload["error"]["type"],
            "invalid_model_tool_call",
        )

    def test_openai_responses_normalizes_function_call_output(self) -> None:
        generation = _normalize_response(
            {
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
            slot="openai_reasoning",
            model="gpt-5.2",
        )

        self.assertEqual(generation.message.tool_calls[0].name, "echo")
        self.assertEqual(generation.message.tool_calls[0].arguments, {"message": "hi"})
        self.assertFalse(generation.final)

    def test_openai_responses_rejects_non_object_tool_arguments(self) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            _normalize_response(
                {
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": "[1,2,3]",
                        }
                    ]
                },
                slot="openai_reasoning",
                model="gpt-5.2",
            )

        self.assertEqual(
            exc_info.exception.payload["error"]["type"],
            "invalid_model_tool_call",
        )


if __name__ == "__main__":
    unittest.main()
