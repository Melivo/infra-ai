from __future__ import annotations

import json
import unittest

from router.app import _build_log_event, _describe_model_mode, _extract_error_type


class RouterLoggingTests(unittest.TestCase):
    def test_build_log_event_omits_none_fields_and_keeps_structure(self) -> None:
        payload = json.loads(
            _build_log_event(
                "chat_request_received",
                route_requested="auto",
                streaming=False,
                provider=None,
            )
        )

        self.assertEqual(payload["component"], "router")
        self.assertEqual(payload["event"], "chat_request_received")
        self.assertEqual(payload["route_requested"], "auto")
        self.assertEqual(payload["streaming"], False)
        self.assertNotIn("provider", payload)

    def test_describe_model_mode_distinguishes_auto_explicit_and_omitted(self) -> None:
        self.assertEqual(_describe_model_mode(None), "omitted")
        self.assertEqual(_describe_model_mode("auto"), "auto")
        self.assertEqual(_describe_model_mode("router-default"), "auto")
        self.assertEqual(_describe_model_mode("gpt-5.2"), "explicit")

    def test_extract_error_type_reads_normalized_error_payload(self) -> None:
        self.assertEqual(
            _extract_error_type({"error": {"type": "timeout", "message": "timed out"}}),
            "timeout",
        )
        self.assertIsNone(_extract_error_type({"message": "no error envelope"}))


if __name__ == "__main__":
    unittest.main()
