from __future__ import annotations

import json
import sys
from urllib import error, request

from cli.tool_selector import select_tools

try:
    import questionary
    from questionary import Choice
except ImportError:  # pragma: no cover - runtime fallback
    questionary = None
    Choice = None


def configure_session(router_url: str) -> list[str]:
    if questionary is None or Choice is None:
        return select_tools(router_url)

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return select_tools(router_url)

    selected_tools = select_tools(router_url)
    while True:
        action = questionary.select(
            "Session setup",
            choices=[
                Choice(title="Tools", value="tools"),
                Choice(title="MCP Servers", value="mcp_servers"),
                Choice(title="Start chat", value="start_chat"),
            ],
            instruction="ENTER = waehlen",
        ).ask()

        if action == "tools":
            selected_tools = select_tools(router_url)
            continue
        if action == "mcp_servers":
            _manage_mcp_servers(router_url)
            continue
        return selected_tools


def _manage_mcp_servers(router_url: str) -> None:
    if questionary is None or Choice is None:
        return

    while True:
        action = questionary.select(
            "MCP Servers",
            choices=[
                Choice(title="Install from catalog", value="install"),
                Choice(title="Suggest for task", value="suggest"),
                Choice(title="Enable installed server", value="enable"),
                Choice(title="Disable installed server", value="disable"),
                Choice(title="Back", value="back"),
            ],
            instruction="ENTER = waehlen",
        ).ask()

        if action == "back":
            return
        if action == "install":
            _install_from_catalog(router_url)
            continue
        if action == "suggest":
            _suggest_and_install(router_url)
            continue
        if action == "enable":
            _toggle_server(router_url, path="/mcp/servers/enable", heading="Enable MCP server")
            continue
        if action == "disable":
            _toggle_server(router_url, path="/mcp/servers/disable", heading="Disable MCP server")


def _install_from_catalog(router_url: str) -> None:
    servers = _request_json(
        router_url=router_url,
        path="/mcp/catalog/servers",
        payload=None,
    ).get("data", [])
    selected = _select_server(
        "Install MCP server from catalog",
        servers if isinstance(servers, list) else [],
    )
    if not isinstance(selected, dict):
        return
    _install_selected_server(router_url, selected)


def _suggest_and_install(router_url: str) -> None:
    if questionary is None:
        return
    query = questionary.text("Describe the missing capability").ask()
    if not isinstance(query, str) or not query.strip():
        return
    suggestions = _request_json(
        router_url=router_url,
        path="/mcp/catalog/suggest",
        payload={"query": query},
    ).get("data", [])
    selected = _select_server(
        "Suggested MCP servers",
        suggestions if isinstance(suggestions, list) else [],
    )
    if not isinstance(selected, dict):
        return
    _install_selected_server(router_url, selected)


def _toggle_server(router_url: str, *, path: str, heading: str) -> None:
    servers = _request_json(
        router_url=router_url,
        path="/mcp/servers",
        payload=None,
    ).get("data", [])
    selected = _select_server(
        heading,
        servers if isinstance(servers, list) else [],
    )
    if not isinstance(selected, dict):
        return

    server_id = selected.get("server_id")
    if not isinstance(server_id, str):
        return

    response = _request_json(
        router_url=router_url,
        path=path,
        payload={"server_id": server_id},
    )
    server = response.get("server")
    if isinstance(server, dict):
        print(
            f"MCP server {server.get('server_id')} -> "
            f"status={server.get('status')} enabled={server.get('enabled')}"
        )


def _install_selected_server(router_url: str, selected: dict[str, object]) -> None:
    if questionary is None:
        return
    source_id = selected.get("source_id")
    server_id = selected.get("server_id")
    if not isinstance(source_id, str) or not isinstance(server_id, str):
        return

    confirmed = questionary.confirm(
        f"Install MCP server {server_id}?",
        default=False,
    ).ask()
    if confirmed is not True:
        return

    response = _request_json(
        router_url=router_url,
        path="/mcp/servers/install",
        payload={
            "source_id": source_id,
            "server_id": server_id,
            "confirm": True,
        },
    )
    server = response.get("server")
    if isinstance(server, dict):
        print(f"Installed MCP server {server.get('server_id')} ({server.get('status')})")

    enable_now = questionary.confirm(
        f"Enable MCP server {server_id} now?",
        default=True,
    ).ask()
    if enable_now is not True:
        return

    enabled = _request_json(
        router_url=router_url,
        path="/mcp/servers/enable",
        payload={"server_id": server_id},
    )
    enabled_server = enabled.get("server")
    if isinstance(enabled_server, dict):
        print(
            f"Enabled MCP server {enabled_server.get('server_id')} -> "
            f"status={enabled_server.get('status')}"
        )


def _select_server(prompt: str, servers: list[object]) -> dict[str, object] | None:
    if questionary is None or Choice is None or not servers:
        return None

    normalized_servers = [server for server in servers if isinstance(server, dict)]
    if not normalized_servers:
        print("No MCP servers available.")
        return None

    selected = questionary.select(
        prompt,
        choices=[
            Choice(
                title=_server_title(server),
                value=server,
            )
            for server in normalized_servers
        ],
        instruction="ENTER = waehlen",
    ).ask()
    return selected if isinstance(selected, dict) else None


def _server_title(server: dict[str, object]) -> str:
    display_name = server.get("display_name")
    server_id = server.get("server_id")
    status = server.get("status")
    if isinstance(display_name, str) and isinstance(server_id, str):
        suffix = f" [{status}]" if isinstance(status, str) and status else ""
        return f"{display_name} ({server_id}){suffix}"
    return str(server)


def _request_json(
    *,
    router_url: str,
    path: str,
    payload: dict[str, object] | None,
) -> dict[str, object]:
    url = f"{router_url.rstrip('/')}{path}"
    method = "GET" if payload is None else "POST"
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")

    req = request.Request(url, headers=headers, method=method, data=data)
    try:
        with request.urlopen(req, timeout=120.0) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        raw_response = exc.read().decode("utf-8") or "{}"
        raise SystemExit(f"router returned HTTP {exc.code}: {raw_response}") from exc
    except error.URLError as exc:
        raise SystemExit(f"could not reach router at {url}: {exc.reason}") from exc

    if not isinstance(decoded, dict):
        raise SystemExit("router response was not a JSON object")
    return decoded
