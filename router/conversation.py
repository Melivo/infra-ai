from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum

from router.normalization import NormalizedGeneration, NormalizedMessage, NormalizedToolCall
from router.schemas import JSONValue
from router.tools.types import ToolResult


class TurnType(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINAL = "final"


@dataclass(frozen=True)
class ConversationTurn:
    type: TurnType
    role: str | None = None
    content: str | None = None
    content_json: JSONValue | None = None
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_arguments: dict[str, JSONValue] | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


def message_to_turns(message: NormalizedMessage) -> list[ConversationTurn]:
    if message.role in {"system", "user"}:
        return [
            ConversationTurn(
                type=TurnType.USER,
                role=message.role,
                content=message.content,
                content_json=message.content_json,
                metadata=dict(message.metadata),
            )
        ]

    if message.role == "assistant":
        turns = [
            ConversationTurn(
                type=TurnType.ASSISTANT,
                role=message.role,
                content=message.content,
                content_json=message.content_json,
                metadata=dict(message.metadata),
            )
        ]
        for tool_call in message.tool_calls:
            turns.append(tool_call_to_turn(tool_call))
        return turns

    if message.role == "tool":
        return [
            ConversationTurn(
                type=TurnType.TOOL_RESULT,
                role=message.role,
                content=message.content,
                content_json=message.content_json,
                tool_name=message.tool_name,
                tool_call_id=message.tool_call_id,
                metadata=dict(message.metadata),
            )
        ]

    raise ValueError(f"Unsupported normalized message role: {message.role!r}")


def messages_to_turns(messages: list[NormalizedMessage]) -> list[ConversationTurn]:
    turns: list[ConversationTurn] = []
    for message in messages:
        turns.extend(message_to_turns(message))
    return turns


def tool_call_to_turn(tool_call: NormalizedToolCall) -> ConversationTurn:
    return ConversationTurn(
        type=TurnType.TOOL_CALL,
        tool_name=tool_call.name,
        tool_call_id=tool_call.call_id,
        tool_arguments=dict(tool_call.arguments),
        metadata=dict(tool_call.metadata),
    )


def generation_to_turns(generation: NormalizedGeneration) -> list[ConversationTurn]:
    turns = message_to_turns(generation.message)
    if generation.final:
        turns.append(
            ConversationTurn(
                type=TurnType.FINAL,
                role="assistant",
                content=generation.message.content,
                content_json=generation.message.content_json,
                metadata=_generation_metadata(generation),
            )
        )
    return turns


def turn_to_message(turn: ConversationTurn) -> NormalizedMessage:
    if turn.type == TurnType.USER:
        role = turn.role if turn.role in {"system", "user"} else "user"
        return NormalizedMessage(
            role=role,
            content=turn.content,
            content_json=turn.content_json,
            metadata=dict(turn.metadata),
        )

    if turn.type in {TurnType.ASSISTANT, TurnType.FINAL}:
        role = turn.role if turn.role == "assistant" else "assistant"
        return NormalizedMessage(
            role=role,
            content=turn.content,
            content_json=turn.content_json,
            metadata=dict(turn.metadata),
        )

    if turn.type == TurnType.TOOL_CALL:
        return NormalizedMessage(
            role="assistant",
            tool_calls=[
                NormalizedToolCall(
                    call_id=turn.tool_call_id or "",
                    name=turn.tool_name or "",
                    arguments=dict(turn.tool_arguments or {}),
                    metadata=dict(turn.metadata),
                )
            ],
        )

    if turn.type == TurnType.TOOL_RESULT:
        return NormalizedMessage(
            role="tool",
            content=turn.content,
            content_json=turn.content_json,
            tool_call_id=turn.tool_call_id,
            tool_name=turn.tool_name,
            metadata=dict(turn.metadata),
        )

    raise ValueError(f"Unsupported conversation turn type: {turn.type!r}")


def turns_to_messages(
    turns: list[ConversationTurn],
    *,
    include_final: bool = False,
) -> list[NormalizedMessage]:
    messages: list[NormalizedMessage] = []
    pending_assistant: NormalizedMessage | None = None

    def flush_pending_assistant() -> None:
        nonlocal pending_assistant
        if pending_assistant is None:
            return
        messages.append(pending_assistant)
        pending_assistant = None

    for turn in turns:
        if turn.type == TurnType.TOOL_CALL:
            tool_call_message = turn_to_message(turn)
            tool_call = tool_call_message.tool_calls[0]
            if pending_assistant is None:
                pending_assistant = NormalizedMessage(role="assistant", tool_calls=[tool_call])
            else:
                pending_assistant = replace(
                    pending_assistant,
                    tool_calls=[*pending_assistant.tool_calls, tool_call],
                )
            continue

        flush_pending_assistant()
        if turn.type == TurnType.FINAL and not include_final:
            continue
        if turn.type == TurnType.ASSISTANT:
            pending_assistant = turn_to_message(turn)
            continue
        messages.append(turn_to_message(turn))

    flush_pending_assistant()
    return messages


def tool_result_to_turn(result: ToolResult) -> ConversationTurn:
    return ConversationTurn(
        type=TurnType.TOOL_RESULT,
        role="tool",
        content=result.output_text if result.output_json is not None else _tool_result_text(result),
        content_json=result.output_json,
        tool_name=result.name,
        tool_call_id=result.call_id,
        metadata=_tool_result_metadata(result),
    )


def _tool_result_text(result: ToolResult) -> str | None:
    if result.output_text is not None:
        return result.output_text
    if result.error_message is not None:
        return result.error_message
    return ""


def _tool_result_metadata(result: ToolResult) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {
        "ok": result.ok,
        "tool_name": result.name,
    }
    if result.error_code is not None:
        metadata["error_code"] = result.error_code
    return metadata


def _generation_metadata(generation: NormalizedGeneration) -> dict[str, JSONValue]:
    metadata = dict(generation.metadata)
    if generation.finish_reason is not None:
        metadata["finish_reason"] = generation.finish_reason
    if generation.response_id is not None:
        metadata["response_id"] = generation.response_id
    if generation.model is not None:
        metadata["model"] = generation.model
    if generation.provider_name is not None:
        metadata["provider_name"] = generation.provider_name
    if generation.provider_slot is not None:
        metadata["provider_slot"] = generation.provider_slot
    if generation.usage is not None:
        metadata["usage"] = generation.usage
    return metadata
