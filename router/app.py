from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import timeout as SocketTimeout
from typing import cast

from router.policies import (
    RoutingPolicyError,
    provider_for_route,
    route_enabled,
    route_streaming_supported,
    select_provider,
)
from router.providers.base import Provider, ProviderError
from router.providers.gemini_fallback import GeminiFallbackProvider
from router.providers.local_vllm import LocalVLLMProvider
from router.providers.openai_fallback import OpenAIFallbackProvider
from router.schemas import JSONValue, RouterConfig, ROUTING_MODES, StreamingResponse

CAPABILITIES_SCHEMA_VERSION = "1"
ROUTER_VERSION = "0.1.0"


class RouterApplication:
    def __init__(self, config: RouterConfig) -> None:
        self.config = config
        self.providers: dict[str, Provider] = {
            "local_vllm": LocalVLLMProvider(
                base_url=config.local_vllm_base_url,
                default_model=config.local_vllm_default_model,
                timeout_s=config.request_timeout_s,
            ),
            "gemini_fallback": GeminiFallbackProvider(
                base_url=config.gemini_base_url,
                api_key=config.gemini_api_key,
                default_model=config.gemini_default_model,
                timeout_s=config.request_timeout_s,
            ),
            "openai_fallback": OpenAIFallbackProvider(
                base_url=config.openai_base_url,
                api_key=config.openai_api_key,
                default_model=config.openai_default_model,
                timeout_s=config.request_timeout_s,
            ),
        }

    def healthcheck(self) -> tuple[int, JSONValue]:
        return HTTPStatus.OK, {"status": "ok"}

    def capabilities(self) -> tuple[int, JSONValue]:
        enabled_providers = {
            "local_vllm": {
                "enabled": True,
                "default_model": self.config.local_vllm_default_model,
                "streaming": True,
                "route": "local",
            },
            "gemini_fallback": {
                "enabled": self.config.enable_gemini_fallback,
                "default_model": self.config.gemini_default_model,
                "streaming": False,
                "route": "reasoning",
            },
            "openai_fallback": {
                "enabled": self.config.enable_openai_fallback,
                "default_model": self.config.openai_default_model,
                "streaming": False,
                "route": "heavy",
            },
        }
        available_routes = {
            route: {
                "enabled": route_enabled(route, self.config),
                "provider": provider_for_route(route),
                "streaming": route_streaming_supported(route)
                and route_enabled(route, self.config),
            }
            for route in ROUTING_MODES
        }

        return (
            HTTPStatus.OK,
            {
                "object": "router.capabilities",
                "schema_version": CAPABILITIES_SCHEMA_VERSION,
                "router_version": ROUTER_VERSION,
                "available_routes": available_routes,
                "enabled_providers": enabled_providers,
                "streaming_support": {
                    "routes": [
                        route
                        for route in ROUTING_MODES
                        if route_streaming_supported(route) and route_enabled(route, self.config)
                    ],
                    "providers": [
                        provider_name
                        for provider_name, provider_info in enabled_providers.items()
                        if provider_info["enabled"] is True and provider_info["streaming"] is True
                    ],
                },
                "default_models": {
                    provider_name: provider_info["default_model"]
                    for provider_name, provider_info in enabled_providers.items()
                },
                "not_yet_supported": [
                    "streaming for reasoning route",
                    "streaming for heavy route",
                    "automatic provider selection beyond auto -> local",
                    "tools, agents and MCP integration",
                ],
            },
        )

    def list_models(self) -> tuple[int, JSONValue]:
        try:
            selection = select_provider(path="/v1/models", payload=None, config=self.config)
        except RoutingPolicyError as exc:
            return exc.status_code, exc.payload
        return self._run_provider_action(selection.provider_name, lambda provider: provider.list_models())

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        try:
            selection = select_provider(
                path="/v1/chat/completions",
                payload=payload,
                config=self.config,
            )
        except RoutingPolicyError as exc:
            return exc.status_code, exc.payload

        return self._run_provider_action(
            selection.provider_name,
            lambda provider: provider.chat_completions(payload),
        )

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> StreamingResponse:
        selection = select_provider(
            path="/v1/chat/completions",
            payload=payload,
            config=self.config,
        )
        provider = self.providers[selection.provider_name]
        upstream = provider.stream_chat_completions(payload)
        content_type = upstream.headers.get_content_type() or "text/event-stream"
        return StreamingResponse(
            status_code=upstream.getcode(),
            content_type=content_type,
            chunks=_iter_upstream_chunks(upstream),
        )

    def _run_provider_action(
        self,
        provider_name: str,
        action: Callable[[Provider], tuple[int, JSONValue]],
    ) -> tuple[int, JSONValue]:
        provider = self.providers[provider_name]
        try:
            return action(provider)
        except ProviderError as exc:
            return exc.status_code, exc.payload or _error_payload(str(exc))


class RouterHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, app: RouterApplication) -> None:
        super().__init__(server_address, handler_class)
        self.app = app


class RouterRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: RouterHTTPServer

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_response(*self.server.app.healthcheck())
            return

        if self.path == "/v1/models":
            self._write_response(*self.server.app.list_models())
            return

        if self.path == "/v1/router/capabilities":
            self._write_response(*self.server.app.capabilities())
            return

        self._write_response(
            HTTPStatus.NOT_FOUND,
            _error_payload(f"unsupported path: {self.path}"),
        )

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._write_response(
                HTTPStatus.NOT_FOUND,
                _error_payload(f"unsupported path: {self.path}"),
            )
            return

        payload = self._read_json_body()
        if payload is None:
            return

        if payload.get("stream") is True:
            self._write_stream_response(payload)
            return

        self._write_response(*self.server.app.chat_completions(payload))

    def log_message(self, format: str, *args) -> None:
        del format
        del args

    def _read_json_body(self) -> dict[str, JSONValue] | None:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body or b"{}")
        except json.JSONDecodeError as exc:
            self._write_response(
                HTTPStatus.BAD_REQUEST,
                _error_payload(f"invalid JSON body: {exc.msg}"),
            )
            return None

        if not isinstance(payload, dict):
            self._write_response(
                HTTPStatus.BAD_REQUEST,
                _error_payload("request body must be a JSON object"),
            )
            return None

        return cast(dict[str, JSONValue], payload)

    def _write_response(self, status_code: int, body: JSONValue) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _write_stream_response(self, payload: dict[str, JSONValue]) -> None:
        try:
            stream = self.server.app.stream_chat_completions(payload)
        except RoutingPolicyError as exc:
            self._write_response(exc.status_code, exc.payload)
            return
        except ProviderError as exc:
            self._write_response(exc.status_code, exc.payload or _error_payload(str(exc)))
            return

        self.send_response(stream.status_code)
        self.send_header("Content-Type", stream.content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        try:
            for chunk in stream.chunks:
                if not chunk:
                    continue
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, SocketTimeout):
            return


def _iter_upstream_chunks(upstream) -> Iterator[bytes]:
    with upstream:
        while True:
            chunk = upstream.read(1024)
            if not chunk:
                return
            yield chunk


def load_config() -> RouterConfig:
    return RouterConfig(
        host=os.environ.get("INFRA_AI_ROUTER_HOST", "127.0.0.1"),
        port=int(os.environ.get("INFRA_AI_ROUTER_PORT", "8010")),
        request_timeout_s=float(os.environ.get("INFRA_AI_REQUEST_TIMEOUT_S", "120")),
        local_vllm_base_url=os.environ.get(
            "INFRA_AI_LOCAL_VLLM_BASE_URL",
            "http://127.0.0.1:8000/v1",
        ),
        local_vllm_default_model=os.environ.get(
            "INFRA_AI_LOCAL_VLLM_DEFAULT_MODEL",
            "Qwen/Qwen3-14B-AWQ",
        ),
        enable_gemini_fallback=os.environ.get(
            "INFRA_AI_ENABLE_GEMINI_FALLBACK",
            "0",
        ).lower()
        in {"1", "true", "yes"},
        gemini_base_url=os.environ.get(
            "INFRA_AI_GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ),
        gemini_api_key=os.environ.get("GEMINI_API_KEY"),
        gemini_default_model=os.environ.get("INFRA_AI_GEMINI_DEFAULT_MODEL"),
        enable_openai_fallback=os.environ.get(
            "INFRA_AI_ENABLE_OPENAI_FALLBACK",
            "0",
        ).lower()
        in {"1", "true", "yes"},
        openai_base_url=os.environ.get(
            "INFRA_AI_OPENAI_BASE_URL",
            "https://api.openai.com/v1",
        ),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_default_model=os.environ.get("INFRA_AI_OPENAI_DEFAULT_MODEL"),
    )


def _error_payload(message: str) -> JSONValue:
    return {"error": {"message": message}}


def main() -> None:
    config = load_config()
    app = RouterApplication(config)
    server = RouterHTTPServer((config.host, config.port), RouterRequestHandler, app)
    print(
        "infra-ai router listening on "
        f"http://{config.host}:{config.port} with routes "
        "auto|local -> local_vllm, reasoning -> gemini_fallback, heavy -> openai_fallback"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
