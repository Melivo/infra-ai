from __future__ import annotations

from router.providers.base import Provider, ProviderError, request_json, resolve_model
from router.schemas import JSONValue


class GeminiFallbackProvider(Provider):
    name = "gemini_fallback"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_model: str | None,
        timeout_s: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout_s = timeout_s

    def list_models(self) -> tuple[int, JSONValue]:
        if not self.api_key:
            raise _not_configured_error(
                provider_type="gemini_fallback_not_configured",
                message="Set GEMINI_API_KEY locally before enabling the fallback.",
            )

        status_code, body = request_json(
            method="GET",
            url=f"{self.base_url}/models?key={self.api_key}",
            timeout_s=self.timeout_s,
            provider_name="gemini_fallback",
        )
        return status_code, _translate_models(body)

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        if not self.api_key or not self.default_model:
            raise _not_configured_error(
                provider_type="gemini_fallback_not_configured",
                message=(
                    "Set GEMINI_API_KEY and INFRA_AI_GEMINI_DEFAULT_MODEL locally "
                    "before enabling the fallback."
                ),
            )

        model = resolve_model(payload, self.default_model)
        if not model:
            raise _not_configured_error(
                provider_type="gemini_default_model_missing",
                message="Set INFRA_AI_GEMINI_DEFAULT_MODEL locally before using the fallback.",
            )

        gemini_payload = _build_gemini_payload(payload)
        status_code, body = request_json(
            method="POST",
            url=f"{self.base_url}/{_model_path(model)}:generateContent?key={self.api_key}",
            timeout_s=self.timeout_s,
            provider_name="gemini_fallback",
            payload=gemini_payload,
        )
        return status_code, _translate_chat_response(body, model)


def _build_gemini_payload(payload: dict[str, JSONValue]) -> dict[str, JSONValue]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise ProviderError(
            "Gemini fallback expects an OpenAI-style messages array.",
            status_code=400,
            payload=_error_payload(
                "invalid_messages",
                "Provide a JSON array in the messages field.",
            ),
        )

    contents: list[JSONValue] = []
    system_texts: list[str] = []

    for item in messages:
        if not isinstance(item, dict):
            raise ProviderError(
                "Gemini fallback received an invalid message entry.",
                status_code=400,
                payload=_error_payload(
                    "invalid_message",
                    "Each message must be a JSON object with role and content.",
                ),
            )

        role = item.get("role")
        if not isinstance(role, str):
            raise ProviderError(
                "Gemini fallback received a message without a role.",
                status_code=400,
                payload=_error_payload("invalid_role", "Each message needs a string role."),
            )

        text = _extract_text(item.get("content"))
        if role == "system":
            system_texts.append(text)
            continue

        if role == "assistant":
            gemini_role = "model"
        elif role == "user":
            gemini_role = "user"
        else:
            raise ProviderError(
                f"Gemini fallback does not support role {role!r}.",
                status_code=400,
                payload=_error_payload(
                    "unsupported_role",
                    "Only system, user and assistant roles are supported right now.",
                ),
            )

        contents.append(
            {
                "role": gemini_role,
                "parts": [{"text": text}],
            }
        )

    if not contents:
        raise ProviderError(
            "Gemini fallback needs at least one non-system message.",
            status_code=400,
            payload=_error_payload(
                "missing_user_content",
                "Add at least one user or assistant message.",
            ),
        )

    gemini_payload: dict[str, JSONValue] = {"contents": contents}
    if system_texts:
        gemini_payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_texts)}]
        }

    generation_config: dict[str, JSONValue] = {}
    temperature = payload.get("temperature")
    if isinstance(temperature, (int, float)):
        generation_config["temperature"] = float(temperature)

    top_p = payload.get("top_p")
    if isinstance(top_p, (int, float)):
        generation_config["topP"] = float(top_p)

    max_tokens = payload.get("max_tokens")
    if isinstance(max_tokens, int):
        generation_config["maxOutputTokens"] = max_tokens

    if generation_config:
        gemini_payload["generationConfig"] = generation_config

    return gemini_payload


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
        "Gemini fallback currently supports only text message content.",
        status_code=400,
        payload=_error_payload(
            "unsupported_content",
            "Use plain text content for Gemini fallback requests.",
        ),
    )


def _translate_models(body: JSONValue) -> JSONValue:
    if not isinstance(body, dict):
        return {"object": "list", "data": []}

    models = body.get("models")
    if not isinstance(models, list):
        return {"object": "list", "data": []}

    data: list[JSONValue] = []
    for model in models:
        if not isinstance(model, dict):
            continue

        name = model.get("name")
        if not isinstance(name, str):
            continue

        model_id = name.removeprefix("models/")
        data.append(
            {
                "id": model_id,
                "object": "model",
                "owned_by": "google",
            }
        )

    return {"object": "list", "data": data}


def _translate_chat_response(body: JSONValue, model: str) -> JSONValue:
    if not isinstance(body, dict):
        return {
            "id": "gemini-fallback",
            "object": "chat.completion",
            "model": model,
            "choices": [],
        }

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

    usage_payload: JSONValue | None = None
    if isinstance(usage, dict):
        usage_payload = {
            "prompt_tokens": usage.get("promptTokenCount", 0),
            "completion_tokens": usage.get("candidatesTokenCount", 0),
            "total_tokens": usage.get("totalTokenCount", 0),
        }

    response: dict[str, JSONValue] = {
        "id": "gemini-fallback",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": message_text,
                },
                "finish_reason": finish_reason,
            }
        ],
    }
    if usage_payload is not None:
        response["usage"] = usage_payload

    return response


def _model_path(model: str) -> str:
    if model.startswith("models/"):
        return model
    return f"models/{model}"


def _not_configured_error(*, provider_type: str, message: str) -> ProviderError:
    return ProviderError(
        "Gemini fallback is not configured. Keep GEMINI_API_KEY private and set it locally.",
        status_code=501,
        payload=_error_payload(provider_type, message),
        should_fallback=True,
    )


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
