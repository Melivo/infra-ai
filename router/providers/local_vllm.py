from __future__ import annotations

import json
from urllib.response import addinfourl

from router.normalization import (
    GenerationRequest,
    NormalizedMessage,
)
from router.provider_output import ProviderOutput
from router.providers.base import Provider, ProviderError, request_json, request_stream
from router.schemas import JSONValue
from router.tools.types import ToolSpec


class LocalVLLMProvider(Provider):
    name = "local_vllm"

    def __init__(self, *, base_url: str, default_model: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_s = timeout_s

    def list_models(self) -> tuple[int, JSONValue]:
        return self._request("GET", "/models")

    def generate(self, request: GenerationRequest) -> ProviderOutput:
        payload = _build_openai_chat_payload(request, default_model=self.default_model)
        _, body = request_json(
            method="POST",
            url=f"{self.base_url}/chat/completions",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=payload,
        )
        return ProviderOutput(
            format="openai_chat_completion",
            body=body,
            provider_name=self.name,
            provider_slot=request.provider_slot,
            fallback_model=str(payload.get("model")) if isinstance(payload.get("model"), str) else None,
        )

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> addinfourl:
        request_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"route", "provider_slot", "tool_call", "allowed_tools"}
        }
        if not isinstance(request_payload.get("model"), str) or request_payload["model"].strip().lower() in {
            "",
            "auto",
            "default",
            "router-default",
        }:
            request_payload["model"] = self.default_model
        return request_stream(
            method="POST",
            url=f"{self.base_url}/chat/completions",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=request_payload,
            headers={"Accept": "text/event-stream"},
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, JSONValue] | None = None,
    ) -> tuple[int, JSONValue]:
        request_payload = None
        if payload is not None:
            request_payload = {
                key: value
                for key, value in payload.items()
                if key not in {"route", "provider_slot", "tool_call", "allowed_tools"}
            }
            model = request_payload.get("model")
            if not isinstance(model, str) or model.strip().lower() in {
                "",
                "auto",
                "default",
                "router-default",
            }:
                request_payload["model"] = self.default_model

        return request_json(
            method=method,
            url=f"{self.base_url}{path}",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=request_payload,
        )


def _build_openai_chat_payload(
    request: GenerationRequest,
    *,
    default_model: str,
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "model": request.model or default_model,
        "messages": [_normalized_message_to_openai(message) for message in request.messages],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [_tool_spec_to_openai_tool(tool) for tool in request.tools]
        payload["tool_choice"] = "auto"
    return payload


def _normalized_message_to_openai(message: NormalizedMessage) -> JSONValue:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": _message_content_text(message),
        }

    payload: dict[str, JSONValue] = {
        "role": message.role,
        "content": _message_content_text(message),
    }
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tool_call.call_id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in message.tool_calls
        ]
    return payload


def _message_content_text(message: NormalizedMessage) -> str:
    if message.content_json is not None:
        return json.dumps(message.content_json, sort_keys=True)
    return message.content or ""


def _tool_spec_to_openai_tool(tool: ToolSpec) -> JSONValue:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }

