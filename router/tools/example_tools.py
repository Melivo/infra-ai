from __future__ import annotations

from router.tools.registry import ToolRegistry
from router.tools.types import (
    ToolCall,
    ToolContext,
    ToolResult,
    ToolRiskLevel,
    ToolSpec,
)


class EchoExecutor:
    """Minimal example executor that returns the provided arguments."""

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=str(call.arguments),
            output_json=call.arguments,
            metadata={"tool_step": ctx.current_tool_step},
        )


class AddNumbersExecutor:
    """Deterministic arithmetic example with a strict object schema."""

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        first_number = call.arguments["a"]
        second_number = call.arguments["b"]
        total = float(first_number) + float(second_number)

        if _is_integral_number(first_number) and _is_integral_number(second_number):
            total_value: int | float = int(total)
        else:
            total_value = total

        result_payload = {
            "a": first_number,
            "b": second_number,
            "sum": total_value,
        }
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=str(total_value),
            output_json=result_payload,
            metadata={"tool_step": ctx.current_tool_step},
        )


def register_example_tools(registry: ToolRegistry) -> None:
    """Register the minimal example tools for infrastructure testing."""
    registry.register(
        ToolSpec(
            name="echo",
            description="Return the provided arguments unchanged.",
            input_schema={
                "type": "object",
                "additionalProperties": True,
            },
            risk_level=ToolRiskLevel.LOW,
            capabilities=["debug"],
            enabled_by_default=True,
        ),
        EchoExecutor(),
    )
    registry.register(
        ToolSpec(
            name="add_numbers",
            description="Add two numeric arguments and return their sum.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.LOW,
            capabilities=["math", "utility"],
            enabled_by_default=True,
        ),
        AddNumbersExecutor(),
    )


def _is_integral_number(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
