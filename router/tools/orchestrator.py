from __future__ import annotations

import asyncio
from dataclasses import replace

from router.tools.policy import ToolPolicy
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext, ToolResult
from router.tools.validation import validate_tool_arguments


class ToolOrchestrationError(Exception):
    """Base error for tool orchestration failures."""


class ToolExecutionTimeoutError(ToolOrchestrationError):
    """Raised when a tool exceeds the configured timeout."""


class ToolOrchestrator:
    """Minimal coordinator for tool lookup, policy checks, and execution."""

    def __init__(self, registry: ToolRegistry, policy: ToolPolicy) -> None:
        self._registry = registry
        self._policy = policy

    async def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        """Resolve a tool, check policy, and execute it once."""
        spec = self._registry.get_spec(call.name)
        executor = self._registry.get_executor(call.name)

        self._policy.check(spec, ctx)
        validate_tool_arguments(spec.input_schema, call.arguments)

        execution_ctx = replace(ctx, current_tool_step=ctx.current_tool_step + 1)
        try:
            return await asyncio.wait_for(
                executor.execute(call, execution_ctx),
                timeout=ctx.tool_timeout_s,
            )
        except TimeoutError as exc:
            raise ToolExecutionTimeoutError(
                f"tool timed out after {ctx.tool_timeout_s} seconds: {call.name}"
            ) from exc
