from __future__ import annotations

from typing import Any


class ToolArgumentsValidationError(Exception):
    """Raised when tool arguments do not match a tool schema."""


def validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if schema.get("type") not in {None, "object"}:
        raise ToolArgumentsValidationError("Only object tool schemas are supported.")

    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}

    required = schema.get("required", [])
    if not isinstance(required, list):
        required = []

    additional_properties = schema.get("additionalProperties", True)

    for key in required:
        if isinstance(key, str) and key not in arguments:
            raise ToolArgumentsValidationError(f"Missing required argument: {key}")

    for key, value in arguments.items():
        property_schema = properties.get(key)
        if property_schema is None:
            if additional_properties is False:
                raise ToolArgumentsValidationError(f"Unexpected argument: {key}")
            continue
        if not isinstance(property_schema, dict):
            continue
        _validate_value(key=key, value=value, schema=property_schema)


def _validate_value(*, key: str, value: Any, schema: dict[str, Any]) -> None:
    expected_type = schema.get("type")
    if not isinstance(expected_type, str):
        return

    if expected_type == "string":
        if isinstance(value, str):
            return
    elif expected_type == "boolean":
        if isinstance(value, bool):
            return
    elif expected_type == "integer":
        if isinstance(value, int) and not isinstance(value, bool):
            return
    elif expected_type == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return
    elif expected_type == "object":
        if isinstance(value, dict):
            nested_properties = schema.get("properties", {})
            nested_required = schema.get("required", [])
            nested_additional = schema.get("additionalProperties", True)
            validate_tool_arguments(
                {
                    "type": "object",
                    "properties": nested_properties if isinstance(nested_properties, dict) else {},
                    "required": nested_required if isinstance(nested_required, list) else [],
                    "additionalProperties": nested_additional,
                },
                value,
            )
            return
    elif expected_type == "array":
        if isinstance(value, list):
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    _validate_value(key=f"{key}[{index}]", value=item, schema=item_schema)
            return

    raise ToolArgumentsValidationError(
        f"Argument {key} must have type {expected_type}."
    )
