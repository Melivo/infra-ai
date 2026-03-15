from __future__ import annotations

from router.providers.base import Provider, ProviderError, request_json, resolve_model, without_router_fields
from router.providers.openai.models import OpenAIModelsClient
from router.schemas import JSONValue

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

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        slot = _resolve_slot(payload)
        model = resolve_model(payload, self.slot_default_models.get(slot))
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

        status_code, body = request_json(
            method="POST",
            url=f"{self.base_url}/responses",
            timeout_s=self.timeout_s,
            provider_name="openai_responses",
            payload=_build_responses_payload(payload, model=model, slot=slot),
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        return status_code, _translate_response(body, slot=slot, model=model)


def _resolve_slot(payload: dict[str, JSONValue]) -> str:
    provider_slot = payload.get("provider_slot")
    if isinstance(provider_slot, str) and provider_slot in OPENAI_RESPONSES_SLOTS:
        return provider_slot
    return "openai_reasoning"


def _build_responses_payload(
    payload: dict[str, JSONValue],
    *,
    model: str,
    slot: str,
) -> dict[str, JSONValue]:
    clean_payload = without_router_fields(payload)
    messages = clean_payload.get("messages")
    if not isinstance(messages, list):
        raise ProviderError(
            "OpenAI Responses fallback expects an OpenAI-style messages array.",
            status_code=400,
            payload=_error_payload(
                "invalid_messages",
                "Provide a JSON array in the messages field.",
            ),
        )

    responses_input: list[JSONValue] = []
    for item in messages:
        if not isinstance(item, dict):
            raise ProviderError(
                "OpenAI Responses fallback received an invalid message entry.",
                status_code=400,
                payload=_error_payload(
                    "invalid_message",
                    "Each message must be a JSON object with role and content.",
                ),
            )

        role = item.get("role")
        if not isinstance(role, str):
            raise ProviderError(
                "OpenAI Responses fallback received a message without a role.",
                status_code=400,
                payload=_error_payload("invalid_role", "Each message needs a string role."),
            )

        responses_input.append(
            {
                "role": role,
                "content": [{"type": "input_text", "text": _extract_text(item.get("content"))}],
            }
        )

    request_payload: dict[str, JSONValue] = {
        "model": model,
        "input": responses_input,
    }

    temperature = clean_payload.get("temperature")
    if isinstance(temperature, (int, float)):
        request_payload["temperature"] = float(temperature)

    max_tokens = clean_payload.get("max_tokens")
    if isinstance(max_tokens, int):
        request_payload["max_output_tokens"] = max_tokens

    request_payload["reasoning"] = {"effort": _REASONING_EFFORTS[slot]}
    return request_payload


def _extract_text(content: JSONValue) -> str:
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

    raise ProviderError(
        "OpenAI Responses fallback currently supports only text message content.",
        status_code=400,
        payload=_error_payload(
            "unsupported_content",
            "Use plain text content for OpenAI Responses requests.",
        ),
    )


def _translate_response(body: JSONValue, *, slot: str, model: str) -> JSONValue:
    if not isinstance(body, dict):
        return {
            "id": "openai-responses",
            "object": "chat.completion",
            "model": model,
            "choices": [],
        }

    response_model = body.get("model")
    output_text = body.get("output_text")
    if not isinstance(output_text, str):
        output_text = _extract_output_text(body.get("output"))

    usage = body.get("usage")
    usage_payload: JSONValue | None = None
    if isinstance(usage, dict):
        usage_payload = {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    response: dict[str, JSONValue] = {
        "id": body.get("id", "openai-responses"),
        "object": "chat.completion",
        "model": response_model if isinstance(response_model, str) else model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": output_text,
                },
                "finish_reason": _finish_reason(body.get("status")),
            }
        ],
        "provider_slot": slot,
    }
    if usage_payload is not None:
        response["usage"] = usage_payload

    return response


def _extract_output_text(output: JSONValue) -> str:
    if not isinstance(output, list):
        return ""

    text_parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue

        content = item.get("content")
        if not isinstance(content, list):
            continue

        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_parts.append(part["text"])

    return "".join(text_parts)


def _finish_reason(status: JSONValue) -> str:
    if status == "completed":
        return "stop"
    return "unknown"


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
