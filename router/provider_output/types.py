"""Provider-facing raw output types."""

from __future__ import annotations

from dataclasses import dataclass, field

from router.conversation import ConversationTurn, ExecutionStep
from router.schemas import JSONValue


@dataclass(frozen=True)
class ProviderOutput:
    format: str
    body: JSONValue
    provider_name: str
    provider_slot: str | None = None
    fallback_model: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedProviderStep:
    turns: list[ConversationTurn]
    step: ExecutionStep
