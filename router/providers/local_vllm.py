from __future__ import annotations

from router.providers.base import Provider, request_json
from router.schemas import JSONValue


class LocalVLLMProvider(Provider):
    name = "local_vllm"

    def __init__(self, *, base_url: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
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
        return request_json(
            method=method,
            url=f"{self.base_url}{path}",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=payload,
        )
