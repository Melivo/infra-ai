from __future__ import annotations

import json
import sys
from urllib import error, request

try:
    import questionary
    from questionary import Choice
except ImportError:  # pragma: no cover - runtime fallback
    questionary = None
    Choice = None


def select_tools(router_url: str) -> list[str]:
    """Fetch tool metadata from the router and prompt for a selection."""
    if questionary is None or Choice is None:
        return []

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return []

    tools = _fetch_tools(router_url)
    if not tools:
        return []

    print("Available tools from router:\n")
    for tool in tools:
        capabilities = ", ".join(tool["capabilities"]) or "none"
        print(f"- {tool['name']}")
        print(f"  risk: {tool['risk_level']}")
        print(f"  capabilities: {capabilities}")
        print(f"  description: {tool['description']}")
    print()

    selected = questionary.checkbox(
        "Select tools for this session",
        choices=[
            Choice(
                title=(
                    f"{tool['name']} ({tool['risk_level']}) - "
                    f"{tool['description']}"
                ),
                value=tool["name"],
                checked=tool["enabled_by_default"],
            )
            for tool in tools
        ],
        instruction="SPACE = auswählen, ENTER = bestätigen",
    ).ask()

    if not selected:
        return []

    return [name for name in selected if isinstance(name, str)]


def _fetch_tools(router_url: str) -> list[dict[str, object]]:
    url = f"{router_url.rstrip('/')}/router/capabilities"
    req = request.Request(url, headers={"Accept": "application/json"}, method="GET")

    try:
        with request.urlopen(req, timeout=120.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (error.HTTPError, error.URLError, json.JSONDecodeError, TimeoutError, OSError):
        return []

    if not isinstance(payload, dict):
        return []

    tools = payload.get("tools")
    if not isinstance(tools, list):
        return []

    normalized: list[dict[str, object]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = tool.get("name")
        description = tool.get("description")
        risk_level = tool.get("risk_level")
        capabilities = tool.get("capabilities")
        enabled_by_default = tool.get("enabled_by_default")
        if (
            isinstance(name, str)
            and isinstance(description, str)
            and isinstance(risk_level, str)
            and isinstance(capabilities, list)
            and all(isinstance(item, str) for item in capabilities)
            and isinstance(enabled_by_default, bool)
        ):
            normalized.append(
                {
                    "name": name,
                    "description": description,
                    "risk_level": risk_level,
                    "capabilities": capabilities,
                    "enabled_by_default": enabled_by_default,
                }
            )

    return sorted(normalized, key=lambda tool: str(tool["name"]))
