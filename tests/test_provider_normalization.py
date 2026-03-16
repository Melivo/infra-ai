from __future__ import annotations

import unittest

from router.normalization import NormalizedMessage
from router.providers.gemini_fallback import _message_text
from router.providers.local_vllm import _message_content_text
from router.providers.openai.responses import _message_output_value


class ProviderNormalizationTests(unittest.TestCase):
    def test_local_vllm_serializes_content_json_when_text_is_missing(self) -> None:
        self.assertEqual(
            _message_content_text(
                NormalizedMessage(
                    role="tool",
                    content=None,
                    content_json={"message": "hi"},
                )
            ),
            "{\"message\": \"hi\"}",
        )

    def test_openai_responses_serializes_content_json_when_text_is_missing(self) -> None:
        self.assertEqual(
            _message_output_value(
                NormalizedMessage(
                    role="tool",
                    content=None,
                    content_json={"sum": 5},
                )
            ),
            "{\"sum\": 5}",
        )

    def test_gemini_fallback_serializes_content_json_when_text_is_missing(self) -> None:
        self.assertEqual(
            _message_text(
                NormalizedMessage(
                    role="tool",
                    content=None,
                    content_json={"sum": 5},
                )
            ),
            "{\"sum\": 5}",
        )


if __name__ == "__main__":
    unittest.main()
