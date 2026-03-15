from __future__ import annotations

from router.providers.base import ProviderError, request_json
from router.schemas import JSONValue

OPENAI_MODELS_SLOT = "openai_models"


class OpenAIModelsClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_s: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s

    def list_models(self) -> tuple[int, JSONValue]:
        if not self.api_key:
            raise ProviderError(
                "OpenAI models discovery is not configured. Keep OPENAI_API_KEY private and set it locally.",
                status_code=501,
                payload={
                    "error": {
                        "type": "openai_models_not_configured",
                        "message": "Set OPENAI_API_KEY locally before using OpenAI models discovery.",
                    }
                },
            )

        return request_json(
            method="GET",
            url=f"{self.base_url}/models",
            timeout_s=self.timeout_s,
            provider_name="openai_models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
