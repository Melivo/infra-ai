from __future__ import annotations

import unittest

from router.normalization import tool_result_to_message
from router.tools.types import ToolResult


class NormalizationTests(unittest.TestCase):
    def test_tool_result_to_message_keeps_json_as_primary_internal_format(self) -> None:
        message = tool_result_to_message(
            ToolResult(
                call_id="call-1",
                name="add_numbers",
                ok=True,
                output_json={"a": 2, "b": 3, "sum": 5},
            )
        )

        self.assertEqual(message.role, "tool")
        self.assertEqual(message.content_json, {"a": 2, "b": 3, "sum": 5})
        self.assertIsNone(message.content)

    def test_tool_result_to_message_keeps_text_when_no_json_output_exists(self) -> None:
        message = tool_result_to_message(
            ToolResult(
                call_id="call-2",
                name="echo",
                ok=True,
                output_text="hello",
            )
        )

        self.assertEqual(message.content, "hello")
        self.assertIsNone(message.content_json)


if __name__ == "__main__":
    unittest.main()
