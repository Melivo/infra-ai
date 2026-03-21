from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol


class ToolRiskLevel(Enum):
    """Minimal risk classification for tool definitions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class McpToolBinding:
    """Explicit MCP ownership metadata for MCP-backed tools."""

    server_id: str
    server_slug: str
    discovered_tool_name: str


@dataclass(frozen=True)
class McpToolServerState:
    """Minimal MCP server execution state visible to the tool policy."""

    server_id: str
    installed: bool
    enabled: bool
    ready: bool
    auth_ready: bool = True
    last_error: str | None = None


@dataclass(frozen=True)
class ToolSpec:
    """Describes a registrable tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: ToolRiskLevel
    capabilities: list[str]
    enabled_by_default: bool = False
    workspace_required: bool = False
    mcp_binding: McpToolBinding | None = None


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
    allowed_tool_names: frozenset[str] | None = None
    mcp_server_state_lookup: Callable[[McpToolBinding], McpToolServerState | None] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolExecutor(Protocol):
    """Protocol for asynchronous tool execution."""

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        ...
