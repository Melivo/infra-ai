"""Compatibility-layer models for request parsing and provider-facing message serialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from router.schemas import JSONValue
from router.tools.types import ToolResult, ToolSpec

if TYPE_CHECKING:
    from router.conversation import ConversationTurn

NormalizedRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class NormalizedToolCall:
    call_id: str
    name: str
    arguments: dict[str, JSONValue]
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedMessage:
    role: NormalizedRole
    content: str | None = None
    content_json: JSONValue | None = None
    tool_calls: list[NormalizedToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedGeneration:
    message: NormalizedMessage
    final: bool
    finish_reason: str | None = None
    response_id: str | None = None
    model: str | None = None
    provider_name: str | None = None
    provider_slot: str | None = None
    usage: dict[str, JSONValue] | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def first_tool_call(self) -> NormalizedToolCall | None:
        if not self.message.tool_calls:
            return None
        return self.message.tool_calls[0]


@dataclass(frozen=True)
class GenerationRequest:
    turns: list["ConversationTurn"]
    tools: list[ToolSpec]
    model: str | None = None
    provider_slot: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)
    _provider_messages: tuple[NormalizedMessage, ...] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def to_provider_messages(self) -> list[NormalizedMessage]:
        from router.conversation import turns_to_messages

        if self._provider_messages is not None:
            return list(self._provider_messages)
        return turns_to_messages(self.turns)

    @property
    def messages(self) -> list[NormalizedMessage]:
        return self.to_provider_messages()

    @classmethod
    def from_messages(
        cls,
        *,
        messages: list[NormalizedMessage],
        tools: list[ToolSpec],
        model: str | None = None,
        provider_slot: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        metadata: dict[str, JSONValue] | None = None,
    ) -> "GenerationRequest":
        from router.conversation import messages_to_turns

        return cls(
            turns=messages_to_turns(messages),
            tools=tools,
            model=model,
            provider_slot=provider_slot,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            metadata=dict(metadata or {}),
            _provider_messages=tuple(messages),
        )


def extract_text_content(content: JSONValue) -> str:
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
                continue
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                text_parts.append(item["text"])

        text = "\n".join(part for part in text_parts if part)
        if text:
            return text

    raise ValueError("Only plain text content is supported.")


def request_messages_from_payload(payload: dict[str, JSONValue]) -> list[NormalizedMessage]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ValueError("The messages field must be a JSON array.")

    normalized_messages: list[NormalizedMessage] = []
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError("Each message must be a JSON object.")
        role = message.get("role")
        if not isinstance(role, str):
            raise ValueError("Each message needs a string role.")
        normalized_messages.append(
            NormalizedMessage(
                role=role.strip().lower(),  # validated at the HTTP edge
                content=extract_text_content(message.get("content")),
            )
        )
    return normalized_messages


def tool_result_to_message(result: ToolResult) -> NormalizedMessage:
    if result.output_json is not None:
        content_json: JSONValue | None = result.output_json
        content = result.output_text
    else:
        content_json = None
        if result.output_text is not None:
            content = result.output_text
        elif result.error_message is not None:
            content = result.error_message
        else:
            content = ""

    metadata: dict[str, JSONValue] = {
        "ok": result.ok,
        "tool_name": result.name,
    }
    if result.error_code is not None:
        metadata["error_code"] = result.error_code

    return NormalizedMessage(
        role="tool",
        content=content,
        content_json=content_json,
        tool_call_id=result.call_id,
        tool_name=result.name,
        metadata=metadata,
    )
