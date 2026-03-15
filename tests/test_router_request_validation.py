from __future__ import annotations

import unittest

from router.app import RequestValidationError, validate_chat_request_payload
from router.policies import RoutingPolicyError


def build_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "auto",
        "messages": [
            {
                "role": "user",
                "content": "Sag kurz, wofuer infra-ai gebaut ist.",
            }
        ],
    }
    payload.update(overrides)
    return payload


class RouterRequestValidationTests(unittest.TestCase):
    def test_valid_minimal_payload_passes(self) -> None:
        validate_chat_request_payload(build_payload())

    def test_messages_are_required(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload({"model": "auto"})

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_messages")

    def test_stream_must_be_boolean(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(build_payload(stream="true"))

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_stream")

    def test_model_must_be_non_blank_string(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(build_payload(model="  "))

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_model")

    def test_provider_slot_is_reserved_for_router(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(
                build_payload(provider_slot="openai_reasoning")
            )

        self.assertEqual(
            exc_info.exception.payload["error"]["type"],
            "invalid_request_field",
        )

    def test_unsupported_roles_are_rejected_early(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(
                build_payload(messages=[{"role": "tool", "content": "noop"}])
            )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "unsupported_role")

    def test_only_text_content_is_supported(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(
                build_payload(
                    messages=[
                        {
                            "role": "user",
                            "content": [{"type": "image_url", "image_url": "x"}],
                        }
                    ]
                )
            )

        self.assertEqual(
            exc_info.exception.payload["error"]["type"],
            "unsupported_content",
        )

    def test_all_system_messages_are_rejected(self) -> None:
        with self.assertRaises(RequestValidationError) as exc_info:
            validate_chat_request_payload(
                build_payload(messages=[{"role": "system", "content": "Sei knapp."}])
            )

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_messages")

    def test_invalid_route_keeps_policy_error_shape(self) -> None:
        with self.assertRaises(RoutingPolicyError) as exc_info:
            validate_chat_request_payload(build_payload(route="cloud"))

        self.assertEqual(exc_info.exception.payload["error"]["type"], "invalid_route")


if __name__ == "__main__":
    unittest.main()
