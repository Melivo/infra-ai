from __future__ import annotations

from dataclasses import dataclass

from router.tools.types import ToolContext, ToolRiskLevel, ToolSpec


class ToolPolicyError(Exception):
    """Base error for tool policy failures."""


class ToolExecutionDeniedError(ToolPolicyError):
    """Raised when tool execution is not allowed in the current context."""


@dataclass(frozen=True)
class ToolPolicyConfig:
    """Minimal configuration for phase 1 tool policy decisions."""

    allow_disabled_tools: bool = False
    allowed_risk_levels: set[ToolRiskLevel] | None = None


class ToolPolicy:
    """Minimal policy gate for tool execution decisions."""

    def __init__(self, config: ToolPolicyConfig | None = None) -> None:
        self._config = config or ToolPolicyConfig()

    def check(self, spec: ToolSpec, ctx: ToolContext) -> None:
        """Allow a tool or raise a clear denial error."""
        explicitly_allowed = (
            ctx.allowed_tool_names is not None
            and spec.name in ctx.allowed_tool_names
        )

        if (
            not spec.enabled_by_default
            and not explicitly_allowed
            and not self._config.allow_disabled_tools
        ):
            raise ToolExecutionDeniedError(
                f"tool is disabled by default: {spec.name}"
            )

        if (
            self._config.allowed_risk_levels is not None
            and spec.risk_level not in self._config.allowed_risk_levels
        ):
            raise ToolExecutionDeniedError(
                f"tool risk level is not allowed: {spec.name} ({spec.risk_level.value})"
            )

        if ctx.current_tool_step >= ctx.max_tool_steps:
            raise ToolExecutionDeniedError(
                f"maximum tool steps exceeded: {spec.name}"
            )
