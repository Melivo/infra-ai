from __future__ import annotations

from router.providers.base import Provider, ProviderError, request_json, with_resolved_model
from router.schemas import JSONValue


class OpenAIFallbackProvider(Provider):
    name = "openai_fallback"

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
        return self._request("GET", "/models")

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        return self._request("POST", "/chat/completions", payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, JSONValue] | None = None,
    ) -> tuple[int, JSONValue]:
        if not self.api_key or not self.default_model:
            raise ProviderError(
                "OpenAI fallback is not configured. Keep OPENAI_API_KEY private and set it locally.",
                status_code=501,
                payload={
                    "error": {
                        "type": "openai_fallback_not_configured",
                        "message": (
                            "Set OPENAI_API_KEY and INFRA_AI_OPENAI_DEFAULT_MODEL locally "
                            "before enabling the fallback."
                        ),
                    }
                },
                should_fallback=True,
            )

        request_payload = None
        if payload is not None:
            request_payload = with_resolved_model(payload, default_model=self.default_model)

        return request_json(
            method=method,
            url=f"{self.base_url}{path}",
            timeout_s=self.timeout_s,
            provider_name="openai_fallback",
            payload=request_payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
