from __future__ import annotations

import json
from urllib.response import addinfourl

from router.normalization import (
    GenerationRequest,
    NormalizedGeneration,
    NormalizedMessage,
    NormalizedToolCall,
)
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

    def generate(self, request: GenerationRequest) -> NormalizedGeneration:
        payload = _build_openai_chat_payload(request, default_model=self.default_model)
        _, body = request_json(
            method="POST",
            url=f"{self.base_url}/chat/completions",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=payload,
        )
        return _normalize_openai_chat_response(
            body,
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
            "content": message.content or "",
        }

    payload: dict[str, JSONValue] = {
        "role": message.role,
        "content": message.content or "",
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


def _tool_spec_to_openai_tool(tool: ToolSpec) -> JSONValue:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _normalize_openai_chat_response(
    body: JSONValue,
    *,
    provider_name: str,
    provider_slot: str | None,
    fallback_model: str | None,
) -> NormalizedGeneration:
    if not isinstance(body, dict):
        return NormalizedGeneration(
            message=NormalizedMessage(role="assistant", content=""),
            final=True,
            provider_name=provider_name,
            provider_slot=provider_slot,
            model=fallback_model,
        )

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return NormalizedGeneration(
            message=NormalizedMessage(role="assistant", content=""),
            final=True,
            response_id=body.get("id") if isinstance(body.get("id"), str) else None,
            provider_name=provider_name,
            provider_slot=provider_slot,
            model=body.get("model") if isinstance(body.get("model"), str) else fallback_model,
        )

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned an invalid choice payload.")

    message_payload = first_choice.get("message")
    if not isinstance(message_payload, dict):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned a choice without a message.")

    tool_calls = _extract_openai_tool_calls(message_payload.get("tool_calls"))
    content = _extract_openai_message_content(message_payload.get("content"))
    finish_reason = first_choice.get("finish_reason")
    usage = body.get("usage")

    return NormalizedGeneration(
        message=NormalizedMessage(
            role="assistant",
            content=content,
            tool_calls=tool_calls,
        ),
        final=not tool_calls,
        finish_reason=finish_reason if isinstance(finish_reason, str) else None,
        response_id=body.get("id") if isinstance(body.get("id"), str) else None,
        model=body.get("model") if isinstance(body.get("model"), str) else fallback_model,
        provider_name=provider_name,
        provider_slot=provider_slot,
        usage=usage if isinstance(usage, dict) else None,
    )


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


def _extract_openai_tool_calls(tool_calls_payload: JSONValue) -> list[NormalizedToolCall]:
    if tool_calls_payload is None:
        return []
    if not isinstance(tool_calls_payload, list):
        raise _invalid_tool_call_error("OpenAI-compatible provider returned a non-list tool_calls payload.")

    normalized_calls: list[NormalizedToolCall] = []
    for item in tool_calls_payload:
        if not isinstance(item, dict):
            raise _invalid_tool_call_error("OpenAI-compatible provider returned an invalid tool_calls entry.")
        call_id = item.get("id")
        function_payload = item.get("function")
        if not isinstance(call_id, str) or not isinstance(function_payload, dict):
            raise _invalid_tool_call_error("OpenAI-compatible provider returned a malformed tool call envelope.")
        name = function_payload.get("name")
        arguments_raw = function_payload.get("arguments")
        if not isinstance(name, str):
            raise _invalid_tool_call_error("OpenAI-compatible provider returned a tool call without a name.")
        arguments = _parse_tool_arguments(arguments_raw)
        normalized_calls.append(
            NormalizedToolCall(
                call_id=call_id,
                name=name,
                arguments=arguments,
            )
        )
    return normalized_calls


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


def _invalid_tool_call_error(message: str) -> ProviderError:
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
