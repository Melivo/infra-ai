from __future__ import annotations

from dataclasses import dataclass, field
import json

from router.conversation import ConversationTurn, TurnType, generation_to_turns, tool_call_to_turn, turns_to_generation
from router.normalization import NormalizedGeneration, NormalizedToolCall
from router.schemas import JSONValue


@dataclass(frozen=True)
class ProviderOutput:
    format: str
    body: JSONValue | NormalizedGeneration
    provider_name: str
    provider_slot: str | None = None
    fallback_model: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)


def parse_provider_generation(provider_response: ProviderOutput | NormalizedGeneration) -> list[ConversationTurn]:
    if isinstance(provider_response, NormalizedGeneration):
        return generation_to_turns(provider_response)

    if provider_response.format == "openai_chat_completion":
        return _parse_openai_chat_completion(provider_response)
    if provider_response.format == "openai_responses":
        return _parse_openai_responses(provider_response)
    if provider_response.format == "gemini_generate_content":
        return _parse_gemini_generate_content(provider_response)
    raise ValueError(f"Unsupported provider output format: {provider_response.format!r}")


def provider_output_to_generation(provider_response: ProviderOutput | NormalizedGeneration) -> NormalizedGeneration:
    if isinstance(provider_response, NormalizedGeneration):
        return provider_response
    return turns_to_generation(parse_provider_generation(provider_response))


def _parse_openai_chat_completion(provider_response: ProviderOutput) -> list[ConversationTurn]:
    body = provider_response.body
    if not isinstance(body, dict):
        return _assistant_final_turns(
            content="",
            metadata=_generation_metadata(
                provider_name=provider_response.provider_name,
                provider_slot=provider_response.provider_slot,
                model=provider_response.fallback_model,
            ),
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return _assistant_final_turns(
            content="",
            metadata=_generation_metadata(
                response_id=_string_value(body.get("id")),
                provider_name=provider_response.provider_name,
                provider_slot=provider_response.provider_slot,
                model=_string_value(body.get("model")) or provider_response.fallback_model,
            ),
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned an invalid choice payload.")

    message_payload = first_choice.get("message")
    if not isinstance(message_payload, dict):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned a choice without a message.")

    tool_call_turns = _extract_openai_tool_call_turns(message_payload.get("tool_calls"))
    content = _extract_openai_message_content(message_payload.get("content"))
    metadata = _generation_metadata(
        finish_reason=_string_value(first_choice.get("finish_reason")),
        response_id=_string_value(body.get("id")),
        model=_string_value(body.get("model")) or provider_response.fallback_model,
        provider_name=provider_response.provider_name,
        provider_slot=provider_response.provider_slot,
        usage=body.get("usage") if isinstance(body.get("usage"), dict) else None,
    )
    return _assistant_turns(content=content, metadata=metadata, tool_call_turns=tool_call_turns)


def _parse_openai_responses(provider_response: ProviderOutput) -> list[ConversationTurn]:
    body = provider_response.body
    if not isinstance(body, dict):
        return _assistant_final_turns(
            content="",
            metadata=_generation_metadata(
                response_id="openai-responses",
                provider_name=provider_response.provider_name,
                provider_slot=provider_response.provider_slot,
                model=provider_response.fallback_model,
            ),
        )

    output_text = body.get("output_text")
    tool_call_turns = _extract_openai_responses_tool_call_turns(body.get("output"))
    message_text = output_text if isinstance(output_text, str) else _extract_openai_responses_output_text(body.get("output"))
    usage = body.get("usage")
    usage_payload: dict[str, JSONValue] | None = None
    if isinstance(usage, dict):
        usage_payload = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    metadata = _generation_metadata(
        finish_reason=_finish_reason(body.get("status"), has_tool_calls=bool(tool_call_turns)),
        response_id=_string_value(body.get("id")) or "openai-responses",
        model=_string_value(body.get("model")) or provider_response.fallback_model,
        provider_name=provider_response.provider_name,
        provider_slot=provider_response.provider_slot,
        usage=usage_payload,
    )
    return _assistant_turns(content=message_text, metadata=metadata, tool_call_turns=tool_call_turns)


def _parse_gemini_generate_content(provider_response: ProviderOutput) -> list[ConversationTurn]:
    body = provider_response.body
    if not isinstance(body, dict):
        return _assistant_final_turns(
            content="",
            metadata=_generation_metadata(
                finish_reason="stop",
                response_id="gemini-fallback",
                provider_name=provider_response.provider_name,
                provider_slot=provider_response.provider_slot,
                model=provider_response.fallback_model,
            ),
        )

    candidates = body.get("candidates")
    usage = body.get("usageMetadata")
    message_text = ""
    finish_reason = "stop"

    if isinstance(candidates, list) and candidates:
        first_candidate = candidates[0]
        if isinstance(first_candidate, dict):
            finish_reason_value = first_candidate.get("finishReason")
            if isinstance(finish_reason_value, str):
                finish_reason = finish_reason_value.lower()

            content = first_candidate.get("content")
            if isinstance(content, dict):
                parts = content.get("parts")
                if isinstance(parts, list):
                    text_parts: list[str] = []
                    for part in parts:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            text_parts.append(part["text"])
                    message_text = "".join(text_parts)

    usage_payload: dict[str, JSONValue] | None = None
    if isinstance(usage, dict):
        usage_payload = {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

    return _assistant_final_turns(
        content=message_text,
        metadata=_generation_metadata(
            finish_reason=finish_reason,
            response_id="gemini-fallback",
            provider_name=provider_response.provider_name,
            provider_slot=provider_response.provider_slot,
            model=provider_response.fallback_model,
            usage=usage_payload,
        ),
    )


def _assistant_turns(
    *,
    content: str,
    metadata: dict[str, JSONValue],
    tool_call_turns: list[ConversationTurn],
) -> list[ConversationTurn]:
    turns = [
        ConversationTurn(
            type=TurnType.ASSISTANT,
            role="assistant",
            content=content,
            metadata=dict(metadata),
        )
    ]
    turns.extend(tool_call_turns)
    if not tool_call_turns:
        turns.append(
            ConversationTurn(
                type=TurnType.FINAL,
                role="assistant",
                content=content,
                metadata=dict(metadata),
            )
        )
    return turns


def _assistant_final_turns(*, content: str, metadata: dict[str, JSONValue]) -> list[ConversationTurn]:
    return _assistant_turns(content=content, metadata=metadata, tool_call_turns=[])


def _extract_openai_message_content(content: JSONValue) -> str:
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
                and item.get("type") in {"text", "output_text"}
                and isinstance(item.get("text"), str)
            ):
                text_parts.append(item["text"])
        return "".join(text_parts)
    return ""


def _extract_openai_tool_call_turns(tool_calls_payload: JSONValue) -> list[ConversationTurn]:
    if tool_calls_payload is None:
        return []
    if not isinstance(tool_calls_payload, list):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned a non-list tool_calls payload.")

    turns: list[ConversationTurn] = []
    for item in tool_calls_payload:
        if not isinstance(item, dict):
            raise _invalid_tool_call_error("OpenAI-compatible provider returned an invalid tool_calls entry.")
        call_id = item.get("id")
        function_payload = item.get("function")
        if not isinstance(call_id, str) or not isinstance(function_payload, dict):
            raise _invalid_tool_call_error("OpenAI-compatible provider returned a malformed tool call envelope.")
        if not call_id.strip():
            raise _invalid_tool_call_error("OpenAI-compatible provider returned a tool call without a valid id.")
        name = function_payload.get("name")
        arguments_raw = function_payload.get("arguments")
        if not isinstance(name, str) or not name.strip():
            raise _invalid_tool_call_error("OpenAI-compatible provider returned a tool call without a name.")
        turns.append(
            tool_call_to_turn(
                NormalizedToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=_parse_tool_arguments(arguments_raw),
                )
            )
        )
    return turns


def _extract_openai_responses_tool_call_turns(output: JSONValue) -> list[ConversationTurn]:
    if not isinstance(output, list):
        return []

    tool_call_turns: list[ConversationTurn] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function_call":
            continue

        call_id = item.get("call_id")
        name = item.get("name")
        arguments = item.get("arguments")
        if not isinstance(call_id, str) or not call_id.strip():
            raise _invalid_tool_call_error("OpenAI Responses returned a malformed function call.")
        if not isinstance(name, str) or not name.strip():
            raise _invalid_tool_call_error("OpenAI Responses returned a malformed function call.")
        tool_call_turns.append(
            ConversationTurn(
                type=TurnType.TOOL_CALL,
                tool_call_id=call_id,
                tool_name=name,
                tool_arguments=_parse_tool_arguments(arguments),
            )
        )
    return tool_call_turns


def _extract_openai_responses_output_text(output: JSONValue) -> str:
    if not isinstance(output, list):
        return ""

    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue

        if item.get("type") == "message":
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    text_parts.append(part["text"])
            continue

        if item.get("type") == "output_text" and isinstance(item.get("text"), str):
            text_parts.append(item["text"])

    return "".join(text_parts)


def _parse_tool_arguments(arguments_raw: JSONValue) -> dict[str, JSONValue]:
    if isinstance(arguments_raw, dict):
        return arguments_raw
    if isinstance(arguments_raw, str):
        try:
            arguments = json.loads(arguments_raw)
        except json.JSONDecodeError as exc:
            raise _invalid_tool_call_error("Model returned tool arguments that are not valid JSON.") from exc
        if isinstance(arguments, dict):
            return arguments
    raise _invalid_tool_call_error("Model returned tool arguments that are not a JSON object.")


def _finish_reason(status: JSONValue, *, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_calls"
    if status == "completed":
        return "stop"
    return "unknown"


def _generation_metadata(
    *,
    finish_reason: str | None = None,
    response_id: str | None = None,
    model: str | None = None,
    provider_name: str | None = None,
    provider_slot: str | None = None,
    usage: dict[str, JSONValue] | None = None,
) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {}
    if finish_reason is not None:
        metadata["finish_reason"] = finish_reason
    if response_id is not None:
        metadata["response_id"] = response_id
    if model is not None:
        metadata["model"] = model
    if provider_name is not None:
        metadata["provider_name"] = provider_name
    if provider_slot is not None:
        metadata["provider_slot"] = provider_slot
    if usage is not None:
        metadata["usage"] = usage
    return metadata


def _string_value(value: JSONValue) -> str | None:
    return value if isinstance(value, str) else None


def _invalid_tool_call_error(message: str) -> ProviderError:
    from router.providers.base import ProviderError

    return ProviderError(
        message,
        status_code=502,
        payload={
            "error": {
                "type": "invalid_model_tool_call",
                "message": message,
            }
        },
    )
