from __future__ import annotations

import unittest

from router.tools.policy import ToolExecutionDeniedError, ToolPolicy, ToolPolicyConfig
from router.tools.types import McpToolBinding, McpToolServerState, ToolContext, ToolRiskLevel, ToolSpec


def _make_spec(name: str = "tool.a", workspace_required: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        description="test tool",
        input_schema={"type": "object", "additionalProperties": False},
        risk_level=ToolRiskLevel.LOW,
        capabilities=[],
        enabled_by_default=True,
        workspace_required=workspace_required,
    )


def _make_ctx(
    workspace_root: str | None = None,
    mcp_server_state_lookup=None,
) -> ToolContext:
    return ToolContext(
        request_id="req-test",
        workspace_root=workspace_root,
        mcp_server_state_lookup=mcp_server_state_lookup,
    )


class ToolPolicyWorkspaceRequiredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ToolPolicy()

    # --- Red: workspace_required=True + no workspace_root → deny ---

    def test_denies_workspace_required_tool_when_no_workspace_root(self) -> None:
        spec = _make_spec(workspace_required=True)
        ctx = _make_ctx(workspace_root=None)
        with self.assertRaises(ToolExecutionDeniedError) as exc_info:
            self.policy.check(spec, ctx)
        self.assertIn("workspace_root", str(exc_info.exception).lower())

    def test_denies_filesystem_read_when_no_workspace_root(self) -> None:
        spec = _make_spec(name="filesystem.read", workspace_required=True)
        ctx = _make_ctx(workspace_root=None)
        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    def test_denies_filesystem_list_when_no_workspace_root(self) -> None:
        spec = _make_spec(name="filesystem.list", workspace_required=True)
        ctx = _make_ctx(workspace_root=None)
        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    def test_denies_git_status_when_no_workspace_root(self) -> None:
        spec = _make_spec(name="git.status", workspace_required=True)
        ctx = _make_ctx(workspace_root=None)
        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    def test_denies_git_diff_when_no_workspace_root(self) -> None:
        spec = _make_spec(name="git.diff", workspace_required=True)
        ctx = _make_ctx(workspace_root=None)
        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    # --- Green: workspace_required=True + workspace_root present → allow ---

    def test_allows_workspace_required_tool_when_workspace_root_present(self) -> None:
        spec = _make_spec(workspace_required=True)
        ctx = _make_ctx(workspace_root="/some/path")
        self.policy.check(spec, ctx)  # must not raise

    # --- Regression: workspace_required=False + no workspace_root → allow ---

    def test_allows_non_workspace_tool_without_workspace_root(self) -> None:
        spec = _make_spec(workspace_required=False)
        ctx = _make_ctx(workspace_root=None)
        self.policy.check(spec, ctx)  # must not raise


class ToolPolicyMcpReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ToolPolicy()

    def _mcp_spec(self) -> ToolSpec:
        return ToolSpec(
            name="mcp.demo.lookup",
            description="demo mcp tool",
            input_schema={"type": "object", "additionalProperties": False},
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["mcp"],
            enabled_by_default=False,
            mcp_binding=McpToolBinding(
                server_id="demo.server",
                server_slug="demo-server",
                discovered_tool_name="lookup",
            ),
        )

    def test_denies_mcp_tool_when_server_not_ready(self) -> None:
        spec = self._mcp_spec()
        ctx = ToolContext(
            request_id="req-test",
            allowed_tool_names=frozenset({"mcp.demo.lookup"}),
            mcp_server_state_lookup=lambda binding: McpToolServerState(
                server_id=binding.server_id,
                installed=True,
                enabled=True,
                ready=False,
            ),
        )

        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    def test_denies_mcp_tool_when_server_disabled(self) -> None:
        spec = self._mcp_spec()
        ctx = ToolContext(
            request_id="req-test",
            allowed_tool_names=frozenset({"mcp.demo.lookup"}),
            mcp_server_state_lookup=lambda binding: McpToolServerState(
                server_id=binding.server_id,
                installed=True,
                enabled=False,
                ready=False,
            ),
        )

        with self.assertRaises(ToolExecutionDeniedError):
            self.policy.check(spec, ctx)

    def test_allows_mcp_tool_when_server_ready(self) -> None:
        spec = self._mcp_spec()
        ctx = ToolContext(
            request_id="req-test",
            allowed_tool_names=frozenset({"mcp.demo.lookup"}),
            mcp_server_state_lookup=lambda binding: McpToolServerState(
                server_id=binding.server_id,
                installed=True,
                enabled=True,
                ready=True,
            ),
        )

        self.policy.check(spec, ctx)


if __name__ == "__main__":
    unittest.main()
