"""Provider-output validation helpers for malformed model tool calls."""

from __future__ import annotations

import json

from router.schemas import JSONValue


def parse_tool_call_fields(
    *,
    call_id: JSONValue,
    name: JSONValue,
    arguments_raw: JSONValue,
    malformed_message: str,
    missing_name_message: str | None = None,
) -> tuple[str, str, dict[str, JSONValue]]:
    if not isinstance(call_id, str) or not call_id.strip():
        raise invalid_model_tool_call(malformed_message)
    if not isinstance(name, str) or not name.strip():
        raise invalid_model_tool_call(missing_name_message or malformed_message)
    arguments = parse_tool_arguments(arguments_raw)
    return call_id, name, arguments


def parse_tool_arguments(arguments_raw: JSONValue) -> dict[str, JSONValue]:
    if isinstance(arguments_raw, dict):
        return validate_argument_field_names(arguments_raw)
    if isinstance(arguments_raw, str):
        try:
            arguments = json.loads(arguments_raw)
        except json.JSONDecodeError as exc:
            raise invalid_model_tool_call("Model returned tool arguments that are not valid JSON.") from exc
        if isinstance(arguments, dict):
            return validate_argument_field_names(arguments)
    raise invalid_model_tool_call("Model returned tool arguments that are not a JSON object.")


def validate_argument_field_names(arguments: dict[str, JSONValue]) -> dict[str, JSONValue]:
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise invalid_model_tool_call("Model returned tool arguments with an invalid field name.")
    return arguments


def invalid_model_tool_call(message: str):
    from router.providers.base import ProviderError

    return ProviderError(
        message,
        status_code=502,
        payload={
            "error": {
                "type": "invalid_model_tool_call",
                "message": message,
            }
        },
    )
