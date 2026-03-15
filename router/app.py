from __future__ import annotations

import json
import os
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from router.policies import select_provider
from router.providers.base import Provider, ProviderError
from router.providers.gemini_fallback import GeminiFallbackProvider
from router.providers.local_vllm import LocalVLLMProvider
from router.providers.openai_fallback import OpenAIFallbackProvider
from router.schemas import JSONValue, RouterConfig


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

    def list_models(self) -> tuple[int, JSONValue]:
        selection = select_provider(path="/v1/models", payload=None, config=self.config)
        return self._run_with_optional_fallback(selection, lambda provider: provider.list_models())

    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        if payload.get("stream") is True:
            return (
                HTTPStatus.NOT_IMPLEMENTED,
                {
                    "error": {
                        "type": "streaming_not_implemented",
                        "message": (
                            "Streaming passthrough is planned for the router frontend path "
                            "but is not implemented in this commit."
                        ),
                    }
                },
            )

        selection = select_provider(
            path="/v1/chat/completions",
            payload=payload,
            config=self.config,
        )
        return self._run_with_optional_fallback(
            selection,
            lambda provider: provider.chat_completions(payload),
        )

    def _run_with_optional_fallback(
        self,
        selection,
        action: Callable[[Provider], tuple[int, JSONValue]],
    ) -> tuple[int, JSONValue]:
        last_error: ProviderError | None = None

        for provider_name in selection.candidates:
            provider = self.providers[provider_name]
            try:
                return action(provider)
            except ProviderError as exc:
                last_error = exc
                if not exc.should_fallback:
                    break

        if last_error is None:
            return HTTPStatus.INTERNAL_SERVER_ERROR, _error_payload("no provider candidates")

        return last_error.status_code, last_error.payload or _error_payload(str(last_error))


class RouterHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, app: RouterApplication) -> None:
        super().__init__(server_address, handler_class)
        self.app = app


class RouterRequestHandler(BaseHTTPRequestHandler):
    server: RouterHTTPServer

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_response(*self.server.app.healthcheck())
            return

        if self.path == "/v1/models":
            self._write_response(*self.server.app.list_models())
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
        f"http://{config.host}:{config.port} with provider chain "
        f"local_vllm -> gemini_fallback -> openai_fallback"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
