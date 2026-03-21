from __future__ import annotations

import asyncio
import unittest

from router.tools.mcp import (
    GithubMcpCatalogClient,
    McpCatalogError,
    McpCatalogSource,
    McpDiscoveredTool,
    McpServerDefinition,
    McpServerManager,
    McpServerStatus,
)
from router.tools.orchestrator import ToolOrchestrator
from router.tools.policy import ToolPolicy
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext, ToolResult, ToolRiskLevel


class _CountingRegistry(ToolRegistry):
    def __init__(self) -> None:
        super().__init__()
        self.register_calls: list[str] = []
        self.unregister_calls: list[str] = []

    def register(self, spec, executor) -> None:
        self.register_calls.append(spec.name)
        super().register(spec, executor)

    def unregister(self, name: str) -> None:
        self.unregister_calls.append(name)
        super().unregister(name)


class _FakeCatalogClient:
    def __init__(
        self,
        *,
        servers: list[McpServerDefinition] | None = None,
        tools_by_server_id: dict[str, list[McpDiscoveredTool]] | None = None,
    ) -> None:
        self.servers = servers or []
        self.tools_by_server_id = tools_by_server_id or {}

    def list_servers(self, source: McpCatalogSource) -> list[McpServerDefinition]:
        del source
        return list(self.servers)

    def discover_tools(self, definition: McpServerDefinition) -> list[McpDiscoveredTool]:
        return list(self.tools_by_server_id.get(definition.server_id, []))


class _FakeRuntime:
    async def invoke(
        self,
        *,
        installation,
        tool: McpDiscoveredTool,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        del ctx
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_json={
                "server_id": installation.definition.server_id,
                "tool_name": tool.tool_name,
                "arguments": dict(call.arguments),
            },
        )


class McpServerManagerTests(unittest.TestCase):
    def _make_definition(self) -> McpServerDefinition:
        return McpServerDefinition(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            slug="demo-server",
            display_name="Demo Server",
            description="Demo MCP server.",
            details_url="https://example.test/demo-server",
            tools_url="https://example.test/demo-server/tools.json",
        )

    def _make_tool(self) -> McpDiscoveredTool:
        return McpDiscoveredTool(
            tool_name="lookup",
            description="Look up demo data.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["lookup"],
        )

    def test_docker_mcp_catalog_source_is_registered_with_explicit_metadata(self) -> None:
        manager = McpServerManager(
            registry=ToolRegistry(),
            catalog_client=_FakeCatalogClient(),
        )

        sources = manager.list_sources()

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].source_id, "docker_mcp_catalog")
        self.assertIn("docker/mcp-registry", sources[0].repository_url)

    def test_install_registers_server_as_control_plane_state_only(self) -> None:
        definition = self._make_definition()
        registry = ToolRegistry()
        manager = McpServerManager(
            registry=registry,
            catalog_client=_FakeCatalogClient(servers=[definition]),
        )

        installation = manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )

        self.assertEqual(installation.status, McpServerStatus.INSTALLED)
        self.assertEqual(registry.list_specs(), [])

    def test_enable_marks_server_ready_only_after_discovery_succeeds(self) -> None:
        definition = self._make_definition()
        tool = self._make_tool()
        registry = ToolRegistry()
        manager = McpServerManager(
            registry=registry,
            catalog_client=_FakeCatalogClient(
                servers=[definition],
                tools_by_server_id={"demo.server": [tool]},
            ),
            runtime=_FakeRuntime(),
        )
        manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )

        installation = manager.enable_server("demo.server")

        self.assertEqual(installation.status, McpServerStatus.READY)
        self.assertTrue(registry.has("mcp.demo-server.lookup"))

    def test_enable_server_publishes_tools_once_with_final_state(self) -> None:
        definition = self._make_definition()
        tool = self._make_tool()
        registry = _CountingRegistry()
        manager = McpServerManager(
            registry=registry,
            catalog_client=_FakeCatalogClient(
                servers=[definition],
                tools_by_server_id={"demo.server": [tool]},
            ),
            runtime=_FakeRuntime(),
        )
        manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )

        installation = manager.enable_server("demo.server")

        self.assertEqual(installation.published_tool_names, ("mcp.demo-server.lookup",))
        self.assertEqual(registry.register_calls, ["mcp.demo-server.lookup"])
        self.assertEqual(registry.unregister_calls, [])

    def test_disabled_or_unready_server_does_not_publish_tools_to_registry(self) -> None:
        definition = self._make_definition()
        manager = McpServerManager(
            registry=ToolRegistry(),
            catalog_client=_FakeCatalogClient(
                servers=[definition],
                tools_by_server_id={"demo.server": []},
            ),
        )
        manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )

        installation = manager.enable_server("demo.server")

        self.assertEqual(installation.status, McpServerStatus.ERROR)
        self.assertEqual(manager.registry.list_specs(), [])

    def test_repeated_discovery_is_deterministic_and_does_not_duplicate_registry_entries(self) -> None:
        definition = self._make_definition()
        tool = self._make_tool()
        registry = ToolRegistry()
        manager = McpServerManager(
            registry=registry,
            catalog_client=_FakeCatalogClient(
                servers=[definition],
                tools_by_server_id={"demo.server": [tool]},
            ),
            runtime=_FakeRuntime(),
        )
        manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )

        manager.enable_server("demo.server")
        manager.enable_server("demo.server")

        self.assertEqual(
            [spec.name for spec in registry.list_specs()],
            ["mcp.demo-server.lookup"],
        )

    def test_mcp_tool_invocation_uses_normal_orchestrator_path(self) -> None:
        definition = self._make_definition()
        tool = self._make_tool()
        registry = ToolRegistry()
        manager = McpServerManager(
            registry=registry,
            catalog_client=_FakeCatalogClient(
                servers=[definition],
                tools_by_server_id={"demo.server": [tool]},
            ),
            runtime=_FakeRuntime(),
        )
        manager.install_server(
            source_id="docker_mcp_catalog",
            server_id="demo.server",
            confirm=True,
        )
        manager.enable_server("demo.server")
        orchestrator = ToolOrchestrator(registry=registry, policy=ToolPolicy())

        result = asyncio.run(
            orchestrator.run(
                ToolCall(
                    call_id="call-1",
                    name="mcp.demo-server.lookup",
                    arguments={"query": "router"},
                ),
                ToolContext(
                    request_id="req-1",
                    allowed_tool_names=frozenset({"mcp.demo-server.lookup"}),
                    mcp_server_state_lookup=manager.server_state_for_binding,
                ),
            )
        )

        self.assertEqual(result.ok, True)
        self.assertEqual(result.output_json["tool_name"], "lookup")


class GithubMcpCatalogClientTests(unittest.TestCase):
    def test_catalog_client_normalizes_invalid_server_list_response(self) -> None:
        client = GithubMcpCatalogClient(fetch_json=lambda _: {"servers": "invalid"})

        with self.assertRaises(McpCatalogError) as exc_info:
            client.list_servers(
                McpCatalogSource(
                    source_id="docker_mcp_catalog",
                    display_name="Docker MCP Catalog",
                    repository_url="https://github.com/docker/mcp-registry",
                    catalog_api_url="https://example.test/catalog",
                    tools_url_template="https://example.test/{slug}/tools.json",
                )
            )

        self.assertIn("invalid catalog server list", str(exc_info.exception).lower())

    def test_catalog_client_normalizes_invalid_tools_response(self) -> None:
        client = GithubMcpCatalogClient(fetch_json=lambda _: {"tools": "invalid"})

        with self.assertRaises(McpCatalogError) as exc_info:
            client.discover_tools(
                McpServerDefinition(
                    source_id="docker_mcp_catalog",
                    server_id="demo.server",
                    slug="demo-server",
                    display_name="Demo Server",
                    description="Demo MCP server.",
                    details_url="https://example.test/demo-server",
                    tools_url="https://example.test/demo-server/tools.json",
                )
            )

        self.assertIn("invalid mcp tools response", str(exc_info.exception).lower())


if __name__ == "__main__":
    unittest.main()
