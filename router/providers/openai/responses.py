from __future__ import annotations

import json

from router.normalization import (
    GenerationRequest,
    NormalizedGeneration,
    NormalizedMessage,
    NormalizedToolCall,
)
from router.providers.base import Provider, ProviderError, request_json
from router.providers.openai.models import OpenAIModelsClient
from router.schemas import JSONValue
from router.tools.types import ToolSpec

OPENAI_RESPONSES_SLOTS = (
    "openai_text",
    "openai_reasoning",
    "openai_tools",
)
OPENAI_AGENT_SLOT = "openai_agent"
_REASONING_EFFORTS = {
    "openai_text": "low",
    "openai_reasoning": "high",
    "openai_tools": "medium",
}


class OpenAIResponsesProvider(Provider):
    name = "openai_responses"

    def __init__(
        self,
        *,
        base_url: str,
        models_base_url: str,
        api_key: str | None,
        text_model: str | None,
        reasoning_model: str | None,
        tools_model: str | None,
        timeout_s: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.slot_default_models = {
            "openai_text": text_model,
            "openai_reasoning": reasoning_model,
            "openai_tools": tools_model,
        }
        self.models_client = OpenAIModelsClient(
            base_url=models_base_url,
            api_key=api_key,
            timeout_s=timeout_s,
        )

    def list_models(self) -> tuple[int, JSONValue]:
        return self.models_client.list_models()

    def generate(self, request: GenerationRequest) -> NormalizedGeneration:
        slot = _resolve_slot(request.provider_slot)
        model = request.model or self.slot_default_models.get(slot)
        if not self.api_key or not model:
            raise ProviderError(
                "OpenAI Responses API is not configured. Keep OPENAI_API_KEY private and set it locally.",
                status_code=501,
                payload={
                    "error": {
                        "type": "openai_responses_not_configured",
                        "message": (
                            "Set OPENAI_API_KEY plus the slot-specific OpenAI model locally "
                            "before using this route."
                        ),
                    }
                },
            )

        _, body = request_json(
            method="POST",
            url=f"{self.base_url}/responses",
            timeout_s=self.timeout_s,
            provider_name="openai_responses",
            payload=_build_responses_payload(request, model=model, slot=slot),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return _normalize_response(body, slot=slot, model=model)


def _resolve_slot(provider_slot: str | None) -> str:
    if provider_slot in OPENAI_RESPONSES_SLOTS:
        return provider_slot
    return "openai_reasoning"


def _build_responses_payload(
    request: GenerationRequest,
    *,
    model: str,
    slot: str,
) -> dict[str, JSONValue]:
    request_payload: dict[str, JSONValue] = {
        "model": model,
        "input": _build_responses_input(request.messages),
        "reasoning": {"effort": _REASONING_EFFORTS[slot]},
    }
    if request.tools:
        request_payload["tools"] = [_tool_spec_to_responses_tool(tool) for tool in request.tools]
        request_payload["tool_choice"] = "auto"
    if isinstance(request.temperature, (int, float)):
        request_payload["temperature"] = float(request.temperature)
    if isinstance(request.max_tokens, int):
        request_payload["max_output_tokens"] = request.max_tokens
    return request_payload


def _build_responses_input(messages: list[NormalizedMessage]) -> list[JSONValue]:
    responses_input: list[JSONValue] = []
    for message in messages:
        if message.role == "tool":
            responses_input.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id or "",
                    "output": _message_output_value(message),
                }
            )
            continue

        if message.tool_calls:
            assistant_text = _message_output_value(message)
            if assistant_text:
                responses_input.append(
                    {
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": assistant_text}],
                    }
                )
            for tool_call in message.tool_calls:
                responses_input.append(
                    {
                        "type": "function_call",
                        "call_id": tool_call.call_id,
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments),
                    }
                )
            continue

        responses_input.append(
            {
                "role": message.role,
                "content": [{"type": "input_text", "text": _message_output_value(message)}],
            }
        )
    return responses_input


def _message_output_value(message: NormalizedMessage) -> str:
    if message.content_json is not None:
        return json.dumps(message.content_json, sort_keys=True)
    return message.content or ""


def _tool_spec_to_responses_tool(tool: ToolSpec) -> JSONValue:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


def _normalize_response(body: JSONValue, *, slot: str, model: str) -> NormalizedGeneration:
    if not isinstance(body, dict):
        return NormalizedGeneration(
            message=NormalizedMessage(role="assistant", content=""),
            final=True,
            response_id="openai-responses",
            model=model,
            provider_name="openai_responses",
            provider_slot=slot,
        )

    output_text = body.get("output_text")
    tool_calls = _extract_tool_calls(body.get("output"))
    message_text = output_text if isinstance(output_text, str) else _extract_output_text(body.get("output"))
    usage = body.get("usage")
    usage_payload: dict[str, JSONValue] | None = None
    if isinstance(usage, dict):
        usage_payload = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    return NormalizedGeneration(
        message=NormalizedMessage(
            role="assistant",
            content=message_text,
            tool_calls=tool_calls,
        ),
        final=not tool_calls,
        finish_reason=_finish_reason(body.get("status"), has_tool_calls=bool(tool_calls)),
        response_id=body.get("id") if isinstance(body.get("id"), str) else "openai-responses",
        model=body.get("model") if isinstance(body.get("model"), str) else model,
        provider_name="openai_responses",
        provider_slot=slot,
        usage=usage_payload,
    )


def _extract_tool_calls(output: JSONValue) -> list[NormalizedToolCall]:
    if not isinstance(output, list):
        return []

    tool_calls: list[NormalizedToolCall] = []
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
        tool_calls.append(
            NormalizedToolCall(
                call_id=call_id,
                name=name,
                arguments=_parse_tool_arguments(arguments),
            )
        )
    return tool_calls


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


def _extract_output_text(output: JSONValue) -> str:
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


def _finish_reason(status: JSONValue, *, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_calls"
    if status == "completed":
        return "stop"
    return "unknown"


def _invalid_tool_call_error(message: str) -> ProviderError:
    return ProviderError(
        message,
        status_code=502,
        payload=_error_payload("invalid_model_tool_call", message),
    )


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
