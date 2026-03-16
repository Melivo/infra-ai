from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class ToolRiskLevel(Enum):
    """Minimal risk classification for tool definitions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ToolSpec:
    """Describes a registrable tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: ToolRiskLevel
    capabilities: list[str]
    enabled_by_default: bool = False


@dataclass(frozen=True)
class ToolCall:
    """Normalized tool invocation."""

    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """Normalized tool execution result for success and failure cases."""

    call_id: str
    name: str
    ok: bool
    output_text: str | None = None
    output_json: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolContext:
    """Minimal execution context for phase 1 tool calls."""

    request_id: str
    workspace_root: str | None = None
    max_tool_steps: int = 1
    current_tool_step: int = 0
    tool_timeout_s: float = 30.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor(Protocol):
    """Protocol for asynchronous tool execution."""

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        ...
