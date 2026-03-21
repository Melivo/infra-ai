from __future__ import annotations

from typing import TypeAlias

from router.tools.types import ToolExecutor, ToolSpec

RegistryEntry: TypeAlias = tuple[ToolSpec, ToolExecutor]


class ToolRegistryError(Exception):
    """Base error for tool registry failures."""


class ToolAlreadyRegisteredError(ToolRegistryError):
    """Raised when a tool name is registered more than once."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a tool name is not present in the registry."""


class ToolRegistry:
    """In-memory registry for tool specifications and executors."""

    def __init__(self) -> None:
        self._entries: dict[str, RegistryEntry] = {}

    def register(self, spec: ToolSpec, executor: ToolExecutor) -> None:
        """Register a tool definition and its executor."""
        if spec.name in self._entries:
            raise ToolAlreadyRegisteredError(
                f"tool already registered: {spec.name}"
            )
        self._entries[spec.name] = (spec, executor)

    def get_spec(self, name: str) -> ToolSpec:
        """Return the registered tool specification for a tool name."""
        return self._get_entry(name)[0]

    def get_executor(self, name: str) -> ToolExecutor:
        """Return the registered executor for a tool name."""
        return self._get_entry(name)[1]

    def has(self, name: str) -> bool:
        """Return whether a tool name is present in the registry."""
        return name in self._entries

    def unregister(self, name: str) -> None:
        """Remove a registered tool definition and executor."""
        if name not in self._entries:
            raise ToolNotFoundError(f"tool not found: {name}")
        del self._entries[name]

    def list_specs(self) -> list[ToolSpec]:
        """Return all registered tool specifications sorted by tool name."""
        return [entry[0] for _, entry in sorted(self._entries.items())]

    def list_enabled_specs(self) -> list[ToolSpec]:
        """Return enabled-by-default tool specifications sorted by tool name."""
        return [spec for spec in self.list_specs() if spec.enabled_by_default]

    def _get_entry(self, name: str) -> RegistryEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"tool not found: {name}") from exc
