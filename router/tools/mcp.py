from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import json
import re
from typing import Any, Protocol
from urllib import request

from router.tools.registry import ToolRegistry
from router.tools.types import (
    McpToolBinding,
    McpToolServerState,
    ToolCall,
    ToolContext,
    ToolResult,
    ToolRiskLevel,
    ToolSpec,
)


class McpServerStatus(str, Enum):
    INSTALLED = "installed"
    READY = "ready"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True)
class McpCatalogSource:
    source_id: str
    display_name: str
    repository_url: str
    catalog_api_url: str
    tools_url_template: str


@dataclass(frozen=True)
class McpServerDefinition:
    source_id: str
    server_id: str
    slug: str
    display_name: str
    description: str
    details_url: str
    tools_url: str | None = None


@dataclass(frozen=True)
class McpDiscoveredTool:
    tool_name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    capabilities: list[str] = field(default_factory=list)
    workspace_required: bool = False


@dataclass(frozen=True)
class McpServerInstallation:
    definition: McpServerDefinition
    status: McpServerStatus
    enabled: bool = False
    discovered_tools: tuple[McpDiscoveredTool, ...] = ()
    published_tool_names: tuple[str, ...] = ()
    last_error: str | None = None


class McpCatalogClient(Protocol):
    def list_servers(self, source: McpCatalogSource) -> list[McpServerDefinition]:
        ...

    def discover_tools(self, definition: McpServerDefinition) -> list[McpDiscoveredTool]:
        ...


class McpRuntime(Protocol):
    async def invoke(
        self,
        *,
        installation: McpServerInstallation,
        tool: McpDiscoveredTool,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        ...


class McpCatalogError(RuntimeError):
    error_type = "mcp_catalog_unavailable"


class McpCatalogUnavailableError(McpCatalogError):
    error_type = "mcp_catalog_unavailable"


class McpCatalogInvalidResponseError(McpCatalogError):
    error_type = "mcp_catalog_invalid_response"


class GithubMcpCatalogClient:
    def __init__(self, fetch_json=None) -> None:
        self._fetch_json = fetch_json or _fetch_json

    def list_servers(self, source: McpCatalogSource) -> list[McpServerDefinition]:
        payload = self._load_json(source.catalog_api_url)
        entries = payload.get("servers") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise McpCatalogInvalidResponseError(
                f"Invalid catalog server list response from {source.catalog_api_url}."
            )

        servers: list[McpServerDefinition] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_server_definition(entry, source)
            if parsed is not None:
                servers.append(parsed)
        return sorted(servers, key=lambda item: item.server_id)

    def discover_tools(self, definition: McpServerDefinition) -> list[McpDiscoveredTool]:
        if definition.tools_url is None:
            return []

        payload = self._load_json(definition.tools_url)
        entries = payload.get("tools") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise McpCatalogInvalidResponseError(
                f"Invalid MCP tools response from {definition.tools_url}."
            )

        tools: list[McpDiscoveredTool] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_discovered_tool(entry)
            if parsed is not None:
                tools.append(parsed)
        return sorted(tools, key=lambda item: item.tool_name)

    def _load_json(self, url: str) -> Any:
        try:
            return self._fetch_json(url)
        except McpCatalogError:
            raise
        except Exception as exc:
            raise McpCatalogUnavailableError(
                f"Unable to load MCP catalog data from {url}."
            ) from exc


class UnavailableMcpRuntime:
    async def invoke(
        self,
        *,
        installation: McpServerInstallation,
        tool: McpDiscoveredTool,
        call: ToolCall,
        ctx: ToolContext,
    ) -> ToolResult:
        del tool
        del ctx
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=False,
            error_code="mcp_runtime_unavailable",
            error_message=(
                f"MCP runtime invocation is not implemented for server: "
                f"{installation.definition.server_id}"
            ),
        )


class McpManagedToolExecutor:
    def __init__(
        self,
        *,
        installation: McpServerInstallation,
        tool: McpDiscoveredTool,
        runtime: McpRuntime,
    ) -> None:
        self._installation = installation
        self._tool = tool
        self._runtime = runtime

    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        return await self._runtime.invoke(
            installation=self._installation,
            tool=self._tool,
            call=call,
            ctx=ctx,
        )


class McpServerManager:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        catalog_client: McpCatalogClient,
        runtime: McpRuntime | None = None,
        sources: list[McpCatalogSource] | None = None,
    ) -> None:
        self.registry = registry
        self._catalog_client = catalog_client
        self._runtime = runtime or UnavailableMcpRuntime()
        default_sources = sources or [docker_mcp_catalog_source()]
        self._sources = {source.source_id: source for source in default_sources}
        self._installations: dict[str, McpServerInstallation] = {}

    def list_sources(self) -> list[McpCatalogSource]:
        return [self._sources[source_id] for source_id in sorted(self._sources)]

    def list_catalog_servers(self, source_id: str | None = None) -> list[McpServerDefinition]:
        if source_id is not None:
            source = self._sources[source_id]
            return self._catalog_client.list_servers(source)

        servers: list[McpServerDefinition] = []
        for source in self.list_sources():
            servers.extend(self._catalog_client.list_servers(source))
        return sorted(servers, key=lambda item: item.server_id)

    def suggest_servers(self, query: str, *, limit: int = 5) -> list[McpServerDefinition]:
        normalized_query = query.strip().lower()
        servers = self.list_catalog_servers()
        if not normalized_query:
            return servers[:limit]

        query_tokens = [token for token in re.split(r"[^a-z0-9]+", normalized_query) if token]
        scored: list[tuple[int, McpServerDefinition]] = []
        for definition in servers:
            haystack = " ".join(
                [
                    definition.server_id.lower(),
                    definition.slug.lower(),
                    definition.display_name.lower(),
                    definition.description.lower(),
                ]
            )
            score = sum(1 for token in query_tokens if token in haystack)
            if score > 0:
                scored.append((score, definition))
        scored.sort(key=lambda item: (-item[0], item[1].server_id))
        return [definition for _, definition in scored[:limit]]

    def list_installations(self) -> list[McpServerInstallation]:
        return [self._installations[server_id] for server_id in sorted(self._installations)]

    def install_server(
        self,
        *,
        source_id: str,
        server_id: str,
        confirm: bool,
    ) -> McpServerInstallation:
        if confirm is not True:
            raise ValueError("MCP server installation requires explicit confirm=true.")

        definition = self._resolve_server_definition(source_id=source_id, server_id=server_id)
        self._unpublish(definition.server_id)
        installation = McpServerInstallation(
            definition=definition,
            status=McpServerStatus.INSTALLED,
            enabled=False,
        )
        self._installations[definition.server_id] = installation
        return installation

    def enable_server(self, server_id: str) -> McpServerInstallation:
        installation = self._installations[server_id]
        discovered_tools = tuple(self._catalog_client.discover_tools(installation.definition))
        if not discovered_tools:
            failed = replace(
                installation,
                status=McpServerStatus.ERROR,
                enabled=False,
                last_error="No MCP tools were discovered for this server.",
            )
            self._installations[server_id] = failed
            self._unpublish(server_id)
            return failed

        ready = replace(
            installation,
            status=McpServerStatus.READY,
            enabled=True,
            discovered_tools=discovered_tools,
            published_tool_names=tuple(
                _registry_tool_name(installation.definition.slug, tool.tool_name)
                for tool in discovered_tools
            ),
            last_error=None,
        )
        self._unpublish(server_id)
        self._installations[server_id] = ready
        self._publish(installation=ready, discovered_tools=discovered_tools)
        return ready

    def disable_server(self, server_id: str) -> McpServerInstallation:
        installation = self._installations[server_id]
        self._unpublish(server_id)
        disabled = replace(
            installation,
            status=McpServerStatus.DISABLED,
            enabled=False,
            published_tool_names=(),
        )
        self._installations[server_id] = disabled
        return disabled

    def capabilities_payload(self) -> dict[str, object]:
        return {
            "implemented": True,
            "management_flow": "separate_control_plane",
            "install_confirmation_required": True,
            "catalog_sources": [
                {
                    "source_id": source.source_id,
                    "display_name": source.display_name,
                    "repository_url": source.repository_url,
                }
                for source in self.list_sources()
            ],
            "servers": [self._installation_payload(item) for item in self.list_installations()],
        }

    def catalog_servers_payload(self) -> list[dict[str, object]]:
        installed_by_id = {item.definition.server_id: item for item in self.list_installations()}
        payload: list[dict[str, object]] = []
        for definition in self.list_catalog_servers():
            installation = installed_by_id.get(definition.server_id)
            payload.append(
                {
                    "source_id": definition.source_id,
                    "server_id": definition.server_id,
                    "slug": definition.slug,
                    "display_name": definition.display_name,
                    "description": definition.description,
                    "details_url": definition.details_url,
                    "installed": installation is not None,
                    "enabled": installation.enabled if installation is not None else False,
                    "status": installation.status.value if installation is not None else None,
                }
            )
        return payload

    def installations_payload(self) -> list[dict[str, object]]:
        return [self._installation_payload(item) for item in self.list_installations()]

    def suggestions_payload(self, query: str) -> list[dict[str, object]]:
        return [
            {
                "source_id": definition.source_id,
                "server_id": definition.server_id,
                "slug": definition.slug,
                "display_name": definition.display_name,
                "description": definition.description,
                "details_url": definition.details_url,
            }
            for definition in self.suggest_servers(query)
        ]

    def server_state_for_binding(
        self,
        binding: McpToolBinding,
    ) -> McpToolServerState | None:
        installation = self._installations.get(binding.server_id)
        if installation is None:
            return None
        return McpToolServerState(
            server_id=installation.definition.server_id,
            installed=True,
            enabled=installation.enabled,
            ready=installation.status == McpServerStatus.READY,
            auth_ready=installation.status == McpServerStatus.READY,
            last_error=installation.last_error,
        )

    def _resolve_server_definition(self, *, source_id: str, server_id: str) -> McpServerDefinition:
        for definition in self.list_catalog_servers(source_id):
            if definition.server_id == server_id:
                return definition
        raise ValueError(f"Unknown MCP server: {server_id}")

    def _publish(
        self,
        *,
        installation: McpServerInstallation,
        discovered_tools: tuple[McpDiscoveredTool, ...],
    ) -> None:
        for tool in discovered_tools:
            tool_name = _registry_tool_name(installation.definition.slug, tool.tool_name)
            spec = ToolSpec(
                name=tool_name,
                description=f"[MCP {installation.definition.slug}] {tool.description}",
                input_schema=dict(tool.input_schema),
                risk_level=tool.risk_level,
                capabilities=_merge_capabilities(tool.capabilities),
                enabled_by_default=False,
                workspace_required=tool.workspace_required,
                mcp_binding=McpToolBinding(
                    server_id=installation.definition.server_id,
                    server_slug=installation.definition.slug,
                    discovered_tool_name=tool.tool_name,
                ),
            )
            self.registry.register(
                spec,
                McpManagedToolExecutor(
                    installation=installation,
                    tool=tool,
                    runtime=self._runtime,
                ),
            )

    def _unpublish(self, server_id: str) -> None:
        installation = self._installations.get(server_id)
        if installation is None:
            return
        for tool_name in installation.published_tool_names:
            if self.registry.has(tool_name):
                self.registry.unregister(tool_name)

    def _installation_payload(self, installation: McpServerInstallation) -> dict[str, object]:
        return {
            "source_id": installation.definition.source_id,
            "server_id": installation.definition.server_id,
            "slug": installation.definition.slug,
            "display_name": installation.definition.display_name,
            "description": installation.definition.description,
            "status": installation.status.value,
            "enabled": installation.enabled,
            "ready_tool_names": list(installation.published_tool_names),
            "last_error": installation.last_error,
        }


def docker_mcp_catalog_source() -> McpCatalogSource:
    return McpCatalogSource(
        source_id="docker_mcp_catalog",
        display_name="Docker MCP Catalog",
        repository_url="https://github.com/docker/mcp-registry",
        catalog_api_url="https://api.github.com/repos/docker/mcp-registry/contents/servers",
        tools_url_template=(
            "https://raw.githubusercontent.com/docker/mcp-registry/main/servers/{slug}/tools.json"
        ),
    )


def _fetch_json(url: str) -> Any:
    req = request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with request.urlopen(req, timeout=30.0) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_server_definition(
    entry: dict[str, object],
    source: McpCatalogSource,
) -> McpServerDefinition | None:
    if entry.get("type") == "dir" and isinstance(entry.get("name"), str):
        slug = entry["name"]
        display_name = slug.replace("-", " ").replace("_", " ").title()
        details_url = (
            entry.get("html_url")
            if isinstance(entry.get("html_url"), str)
            else f"{source.repository_url}/tree/main/servers/{slug}"
        )
        return McpServerDefinition(
            source_id=source.source_id,
            server_id=slug,
            slug=slug,
            display_name=display_name,
            description=f"MCP server from {source.display_name}.",
            details_url=details_url,
            tools_url=source.tools_url_template.format(slug=slug),
        )

    server_id = entry.get("server_id") or entry.get("id") or entry.get("slug")
    slug = entry.get("slug") or server_id
    display_name = entry.get("display_name") or entry.get("name") or slug
    if not isinstance(server_id, str) or not isinstance(slug, str) or not isinstance(display_name, str):
        return None

    description = entry.get("description")
    details_url = entry.get("details_url") or entry.get("html_url")
    tools_url = entry.get("tools_url")
    return McpServerDefinition(
        source_id=source.source_id,
        server_id=server_id,
        slug=slug,
        display_name=display_name,
        description=description if isinstance(description, str) else "",
        details_url=details_url if isinstance(details_url, str) else source.repository_url,
        tools_url=tools_url if isinstance(tools_url, str) else source.tools_url_template.format(slug=slug),
    )


def _parse_discovered_tool(entry: dict[str, object]) -> McpDiscoveredTool | None:
    tool_name = entry.get("tool_name") or entry.get("name") or entry.get("id")
    description = entry.get("description") or tool_name
    input_schema = entry.get("input_schema") or entry.get("schema")
    if (
        not isinstance(tool_name, str)
        or not tool_name.strip()
        or not isinstance(description, str)
        or not isinstance(input_schema, dict)
    ):
        return None

    capabilities = entry.get("capabilities")
    risk_level = _parse_risk_level(entry.get("risk_level"))
    workspace_required = entry.get("workspace_required") is True
    return McpDiscoveredTool(
        tool_name=tool_name.strip(),
        description=description.strip(),
        input_schema=input_schema,
        risk_level=risk_level,
        capabilities=_normalize_capability_list(capabilities),
        workspace_required=workspace_required,
    )


def _parse_risk_level(value: object) -> ToolRiskLevel:
    if isinstance(value, str):
        normalized = value.strip().lower()
        for risk_level in ToolRiskLevel:
            if risk_level.value == normalized:
                return risk_level
    return ToolRiskLevel.MEDIUM


def _merge_capabilities(capabilities: list[str]) -> list[str]:
    merged = ["mcp"]
    for capability in capabilities:
        if capability not in merged:
            merged.append(capability)
    return merged


def _normalize_capability_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _registry_tool_name(server_slug: str, tool_name: str) -> str:
    return f"mcp.{_normalize_segment(server_slug)}.{_normalize_segment(tool_name)}"


def _normalize_segment(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip().lower())
    normalized = normalized.strip("-")
    return normalized or "tool"
