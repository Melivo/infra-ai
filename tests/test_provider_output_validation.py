from __future__ import annotations

import unittest

from router.provider_output import ProviderOutput, parse_provider_generation
from router.providers.base import ProviderError


class ProviderOutputValidationTests(unittest.TestCase):
    def assert_invalid_model_tool_call(self, provider_output: ProviderOutput) -> None:
        with self.assertRaises(ProviderError) as exc_info:
            parse_provider_generation(provider_output)
        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model_tool_call")

    def test_openai_chat_rejects_empty_tool_name(self) -> None:
        self.assert_invalid_model_tool_call(
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
            )
        )

    def test_openai_chat_rejects_non_object_tool_arguments(self) -> None:
        self.assert_invalid_model_tool_call(
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
                                            "name": "echo",
                                            "arguments": "[]",
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                provider_name="local_vllm",
            )
        )

    def test_openai_chat_rejects_invalid_tool_call_structure(self) -> None:
        self.assert_invalid_model_tool_call(
            ProviderOutput(
                format="openai_chat_completion",
                body={
                    "choices": [
                        {
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "",
                                        "function": {
                                            "name": "echo",
                                            "arguments": "{}",
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                },
                provider_name="local_vllm",
            )
        )

    def test_openai_responses_rejects_non_json_arguments(self) -> None:
        self.assert_invalid_model_tool_call(
            ProviderOutput(
                format="openai_responses",
                body={
                    "output": [
                        {
                            "type": "function_call",
                            "call_id": "call-1",
                            "name": "echo",
                            "arguments": "{not-json",
                        }
                    ]
                },
                provider_name="openai_responses",
                provider_slot="openai_reasoning",
            )
        )


if __name__ == "__main__":
    unittest.main()
