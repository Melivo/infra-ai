from __future__ import annotations

import json

from router.normalization import (
    GenerationRequest,
    NormalizedMessage,
)
from router.provider_output import ProviderOutput
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

    def generate(self, request: GenerationRequest) -> ProviderOutput:
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
        return ProviderOutput(
            format="openai_responses",
            body=body,
            provider_name="openai_responses",
            provider_slot=slot,
            fallback_model=model,
        )


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
        "input": _build_responses_input(request.to_provider_messages()),
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
