from __future__ import annotations

from urllib.response import addinfourl

from router.providers.base import Provider, request_json, request_stream, with_resolved_model
from router.schemas import JSONValue


class LocalVLLMProvider(Provider):
    name = "local_vllm"

    def __init__(self, *, base_url: str, default_model: str, timeout_s: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_s = timeout_s

    def list_models(self) -> tuple[int, JSONValue]:
        return self._request("GET", "/models")

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        return self._request("POST", "/chat/completions", payload)

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> addinfourl:
        request_payload = with_resolved_model(payload, default_model=self.default_model)
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
            request_payload = with_resolved_model(payload, default_model=self.default_model)

        return request_json(
            method=method,
            url=f"{self.base_url}{path}",
            timeout_s=self.timeout_s,
            provider_name="local_vllm",
            payload=request_payload,
        )
