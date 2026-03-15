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


def register_example_tools(registry: ToolRegistry) -> None:
    """Register the minimal example tools for infrastructure testing."""
    spec = ToolSpec(
        name="echo",
        description="Return the provided arguments unchanged.",
        input_schema={
            "type": "object",
            "additionalProperties": True,
        },
        risk_level=ToolRiskLevel.LOW,
        capabilities=["debug"],
        enabled_by_default=True,
    )
    registry.register(spec, EchoExecutor())
