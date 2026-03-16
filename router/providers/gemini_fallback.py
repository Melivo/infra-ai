from __future__ import annotations

import json

from router.normalization import GenerationRequest, NormalizedMessage
from router.provider_output import ProviderOutput
from router.providers.base import Provider, ProviderError, request_json
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

    def generate(self, request: GenerationRequest) -> ProviderOutput:
        if not self.api_key or not self.default_model:
            raise _not_configured_error(
                provider_type="gemini_fallback_not_configured",
                message=(
                    "Set GEMINI_API_KEY and INFRA_AI_GEMINI_DEFAULT_MODEL locally "
                    "before enabling the fallback."
                ),
            )

        model = request.model or self.default_model
        if not model:
            raise _not_configured_error(
                provider_type="gemini_default_model_missing",
                message="Set INFRA_AI_GEMINI_DEFAULT_MODEL locally before using the fallback.",
            )

        _, body = request_json(
            method="POST",
            url=f"{self.base_url}/{_model_path(model)}:generateContent?key={self.api_key}",
            timeout_s=self.timeout_s,
            provider_name="gemini_fallback",
            payload=_build_gemini_payload(request),
        )
        return ProviderOutput(
            format="gemini_generate_content",
            body=body,
            provider_name="gemini_fallback",
            fallback_model=model,
        )


def _build_gemini_payload(request: GenerationRequest) -> dict[str, JSONValue]:
    contents: list[JSONValue] = []
    system_texts: list[str] = []

    for message in request.messages:
        text = _message_text(message)
        if message.role == "system":
            system_texts.append(text)
            continue

        if message.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [{"text": f"Tool {message.tool_name or 'tool'} result:\n{text}"}],
                }
            )
            continue

        if message.role == "assistant":
            gemini_role = "model"
        elif message.role == "user":
            gemini_role = "user"
        else:
            raise ProviderError(
                f"Gemini fallback does not support role {message.role!r}.",
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
    if isinstance(request.temperature, (int, float)):
        generation_config["temperature"] = float(request.temperature)
    if isinstance(request.top_p, (int, float)):
        generation_config["topP"] = float(request.top_p)
    if isinstance(request.max_tokens, int):
        generation_config["maxOutputTokens"] = request.max_tokens
    if generation_config:
        gemini_payload["generationConfig"] = generation_config

    return gemini_payload


def _message_text(message: NormalizedMessage) -> str:
    if message.content_json is not None:
        return json.dumps(message.content_json, sort_keys=True)
    return message.content or ""


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
