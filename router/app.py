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
    provider_slot_for_route,
    route_enabled,
    route_streaming_supported,
    select_provider,
)
from router.providers.base import Provider, ProviderError
from router.providers.gemini_fallback import GeminiFallbackProvider
from router.providers.local_vllm import LocalVLLMProvider
from router.providers.openai import (
    OPENAI_AGENT_SLOT,
    OPENAI_REALTIME_SLOT,
    OPENAI_RESPONSES_SLOTS,
    OpenAIModelsClient,
    OpenAIResponsesProvider,
)
from router.providers.openai.models import OPENAI_MODELS_SLOT
from router.schemas import JSONValue, RouterConfig, ROUTING_MODES, StreamingResponse

CAPABILITIES_SCHEMA_VERSION = "1"
ROUTER_VERSION = "0.1.0"
ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant"}
MODEL_AUTO_ALIASES = {"auto", "default", "router-default"}


class ConfigValidationError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("invalid router configuration:\n- " + "\n- ".join(self.errors))


class RequestValidationError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.status_code = HTTPStatus.BAD_REQUEST
        self.payload = _error_payload(error_type, message)


class RouterApplication:
    def __init__(self, config: RouterConfig) -> None:
        validate_config(config)
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
            "openai_responses": OpenAIResponsesProvider(
                base_url=config.openai_responses_base_url,
                models_base_url=config.openai_models_base_url,
                api_key=config.openai_api_key,
                text_model=config.openai_text_model,
                reasoning_model=config.openai_reasoning_model,
                tools_model=config.openai_tools_model,
                timeout_s=config.request_timeout_s,
            ),
        }
        self.openai_models = OpenAIModelsClient(
            base_url=config.openai_models_base_url,
            api_key=config.openai_api_key,
            timeout_s=config.request_timeout_s,
        )

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
            "openai_responses": {
                "enabled": self.config.enable_openai_fallback,
                "default_model": self.config.openai_reasoning_model,
                "streaming": False,
                "route": "heavy",
                "api_family": "responses",
            },
        }
        available_routes = {
            route: {
                "enabled": route_enabled(route, self.config),
                "provider": provider_for_route(route),
                "provider_slot": provider_slot_for_route(route),
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
                "frontend_contract": _build_frontend_contract_capabilities(),
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
                    "local_vllm": self.config.local_vllm_default_model,
                    "gemini_fallback": self.config.gemini_default_model,
                    "openai_text": self.config.openai_text_model,
                    "openai_reasoning": self.config.openai_reasoning_model,
                    "openai_tools": self.config.openai_tools_model,
                    "openai_realtime": self.config.openai_realtime_model,
                },
                "openai": _build_openai_capabilities(self.config),
                "not_yet_supported": [
                    "streaming for reasoning route",
                    "streaming for heavy route",
                    "automatic provider selection beyond auto -> local",
                    "openai_realtime router execution path",
                    "openai_agent orchestration layer",
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

        payload_with_slot = _with_provider_slot(payload, selection.provider_slot)
        return self._run_provider_action(
            selection.provider_name,
            lambda provider: provider.chat_completions(payload_with_slot),
        )

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> StreamingResponse:
        selection = select_provider(
            path="/v1/chat/completions",
            payload=payload,
            config=self.config,
        )
        provider = self.providers[selection.provider_name]
        payload_with_slot = _with_provider_slot(payload, selection.provider_slot)
        upstream = provider.stream_chat_completions(payload_with_slot)
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
            return exc.status_code, exc.payload or _error_payload("provider_error", str(exc))


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
            _error_payload("unsupported_path", f"unsupported path: {self.path}"),
        )

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._write_response(
                HTTPStatus.NOT_FOUND,
                _error_payload("unsupported_path", f"unsupported path: {self.path}"),
            )
            return

        payload = self._read_json_body()
        if payload is None:
            return

        try:
            # Validate once at the HTTP edge; downstream router methods assume a valid payload.
            validate_chat_request_payload(payload)
        except RoutingPolicyError as exc:
            self._write_response(exc.status_code, exc.payload)
            return
        except RequestValidationError as exc:
            self._write_response(exc.status_code, exc.payload)
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
                _error_payload("invalid_json", f"invalid JSON body: {exc.msg}"),
            )
            return None

        if not isinstance(payload, dict):
            self._write_response(
                HTTPStatus.BAD_REQUEST,
                _error_payload("invalid_request", "request body must be a JSON object"),
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
            self._write_response(
                exc.status_code,
                exc.payload or _error_payload("provider_error", str(exc)),
            )
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


def _with_provider_slot(
    payload: dict[str, JSONValue],
    provider_slot: str | None,
) -> dict[str, JSONValue]:
    if provider_slot is None:
        return dict(payload)

    payload_with_slot = dict(payload)
    payload_with_slot["provider_slot"] = provider_slot
    return payload_with_slot


def validate_chat_request_payload(payload: dict[str, JSONValue]) -> None:
    _validate_route_field(payload.get("route"))

    if "provider_slot" in payload:
        raise RequestValidationError(
            "invalid_request_field",
            "provider_slot is reserved for internal router use and must not be sent by clients.",
        )

    if "stream" in payload and not isinstance(payload["stream"], bool):
        raise RequestValidationError(
            "invalid_stream",
            "The stream field must be a boolean when provided.",
        )

    if "model" in payload:
        _validate_model_field(payload["model"])

    _validate_messages(payload.get("messages"))


def _validate_route_field(route: JSONValue) -> None:
    if route is None:
        return

    if not isinstance(route, str):
        raise RequestValidationError(
            "invalid_route",
            "The route field must be one of: auto, local, reasoning, heavy.",
        )

    normalized_route = route.strip().lower()
    if normalized_route not in ROUTING_MODES:
        raise RequestValidationError(
            "invalid_route",
            "Supported route values are: auto, local, reasoning, heavy.",
        )


def _validate_model_field(model: JSONValue) -> None:
    if not isinstance(model, str):
        raise RequestValidationError(
            "invalid_model",
            "The model field must be a string when provided.",
        )

    normalized_model = model.strip()
    if not normalized_model:
        raise RequestValidationError(
            "invalid_model",
            "The model field must not be blank. Omit it or use auto for router defaults.",
        )

    if normalized_model.lower() in MODEL_AUTO_ALIASES:
        return


def _validate_messages(messages: JSONValue) -> None:
    if not isinstance(messages, list):
        raise RequestValidationError(
            "invalid_messages",
            "The messages field is required and must be a JSON array.",
        )

    if not messages:
        raise RequestValidationError(
            "invalid_messages",
            "The messages field must contain at least one message.",
        )

    has_non_system_message = False
    for message in messages:
        if not isinstance(message, dict):
            raise RequestValidationError(
                "invalid_message",
                "Each message must be a JSON object with role and content.",
            )

        role = message.get("role")
        if not isinstance(role, str):
            raise RequestValidationError(
                "invalid_role",
                "Each message must include a string role.",
            )

        normalized_role = role.strip().lower()
        if normalized_role not in ALLOWED_MESSAGE_ROLES:
            raise RequestValidationError(
                "unsupported_role",
                "Only system, user and assistant roles are supported right now.",
            )

        if "content" not in message:
            raise RequestValidationError(
                "invalid_message",
                "Each message must include a content field.",
            )

        _validate_message_content(message["content"])
        if normalized_role != "system":
            has_non_system_message = True

    if not has_non_system_message:
        raise RequestValidationError(
            "invalid_messages",
            "Add at least one user or assistant message.",
        )


def _validate_message_content(content: JSONValue) -> None:
    if isinstance(content, str):
        if content.strip():
            return
        raise RequestValidationError(
            "invalid_content",
            "Message content must not be blank.",
        )

    if isinstance(content, list):
        saw_text = False
        for item in content:
            if isinstance(item, str):
                if item.strip():
                    saw_text = True
                    continue
                raise RequestValidationError(
                    "invalid_content",
                    "Text content parts must not be blank.",
                )

            if (
                isinstance(item, dict)
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                if item["text"].strip():
                    saw_text = True
                    continue
                raise RequestValidationError(
                    "invalid_content",
                    "Text content parts must not be blank.",
                )

            raise RequestValidationError(
                "unsupported_content",
                "Only plain text content is supported right now.",
            )

        if saw_text:
            return

    raise RequestValidationError(
        "unsupported_content",
        "Only plain text content is supported right now.",
    )


def _build_openai_capabilities(config: RouterConfig) -> JSONValue:
    responses_enabled = config.enable_openai_fallback
    return {
        "api_families": {
            "responses": {
                "enabled": responses_enabled,
                "implemented": True,
                "standard_path": True,
            },
            "realtime": {
                "enabled": False,
                "implemented": False,
                "prepared": True,
            },
            "models": {
                "enabled": responses_enabled,
                "implemented": True,
                "discovery_only": True,
            },
            "agents": {
                "enabled": False,
                "implemented": False,
                "prepared": True,
                "layer": "orchestration",
            },
        },
        "slots": {
            "openai_text": {
                "api_family": "responses",
                "enabled": responses_enabled,
                "implemented": False,
                "prepared": True,
                "default_model": config.openai_text_model,
                "routed": False,
            },
            "openai_reasoning": {
                "api_family": "responses",
                "enabled": responses_enabled,
                "implemented": True,
                "default_model": config.openai_reasoning_model,
                "routed_via": "heavy",
            },
            "openai_tools": {
                "api_family": "responses",
                "enabled": responses_enabled,
                "implemented": False,
                "prepared": True,
                "default_model": config.openai_tools_model,
                "routed": False,
            },
            OPENAI_AGENT_SLOT: {
                "api_family": "agents_sdk",
                "enabled": False,
                "implemented": False,
                "prepared": True,
                "routed": False,
            },
            OPENAI_REALTIME_SLOT: {
                "api_family": "realtime",
                "enabled": False,
                "implemented": False,
                "prepared": True,
                "default_model": config.openai_realtime_model,
                "routed": False,
            },
            OPENAI_MODELS_SLOT: {
                "api_family": "models",
                "enabled": responses_enabled,
                "implemented": True,
                "discovery_only": True,
                "routed": False,
            },
        },
        "responses_slots": list(OPENAI_RESPONSES_SLOTS),
        "standard_inference_api": "responses",
        "separate_realtime_api": True,
    }


def _build_frontend_contract_capabilities() -> JSONValue:
    return {
        "multi_frontend": True,
        "router_role": "shared_chat_and_inference_platform",
        "reference_frontends": [
            {
                "id": "terminal_cli",
                "status": "implemented",
                "notes": "Reference frontend that talks to the router over HTTP.",
            }
        ],
        "planned_frontends": [
            {
                "id": "code_oss_ide_chat",
                "status": "planned",
                "notes": "Future IDE chat client for Code OSS using the same router contract.",
            }
        ],
        "shared_contract": {
            "capabilities_endpoint": "/v1/router/capabilities",
            "chat_endpoint": "/v1/chat/completions",
            "routing_modes": list(ROUTING_MODES),
            "streaming_via_router": True,
            "provider_logic_in_frontends": False,
            "model_selection_in_frontends": False,
        },
    }


def validate_config(config: RouterConfig) -> None:
    errors: list[str] = []

    if _is_blank(config.host):
        errors.append("INFRA_AI_ROUTER_HOST must not be empty.")
    if not 1 <= config.port <= 65535:
        errors.append("INFRA_AI_ROUTER_PORT must be between 1 and 65535.")
    if config.request_timeout_s <= 0:
        errors.append("INFRA_AI_REQUEST_TIMEOUT_S must be greater than 0.")

    if _is_blank(config.local_vllm_base_url):
        errors.append("INFRA_AI_LOCAL_VLLM_BASE_URL must not be empty.")
    if _is_blank(config.local_vllm_default_model):
        errors.append("INFRA_AI_LOCAL_VLLM_DEFAULT_MODEL must not be empty.")

    if config.enable_gemini_fallback:
        _require_non_empty(errors, "INFRA_AI_GEMINI_BASE_URL", config.gemini_base_url)
        _require_non_empty(errors, "GEMINI_API_KEY", config.gemini_api_key)
        _require_non_empty(errors, "INFRA_AI_GEMINI_DEFAULT_MODEL", config.gemini_default_model)
        if config.gemini_default_model == "gemini-model-id-here":
            errors.append(
                "INFRA_AI_GEMINI_DEFAULT_MODEL must be set to a real Gemini model before "
                "enabling the reasoning route."
            )

    if config.enable_openai_fallback:
        _require_non_empty(
            errors,
            "INFRA_AI_OPENAI_RESPONSES_BASE_URL",
            config.openai_responses_base_url,
        )
        _require_non_empty(
            errors,
            "INFRA_AI_OPENAI_MODELS_BASE_URL",
            config.openai_models_base_url,
        )
        _require_non_empty(errors, "OPENAI_API_KEY", config.openai_api_key)
        _require_non_empty(
            errors,
            "INFRA_AI_OPENAI_REASONING_MODEL",
            config.openai_reasoning_model,
        )

    if errors:
        raise ConfigValidationError(errors)


def _require_non_empty(errors: list[str], env_name: str, value: str | None) -> None:
    if _is_blank(value):
        errors.append(f"{env_name} must not be empty when its provider is enabled.")


def _is_blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _iter_upstream_chunks(upstream) -> Iterator[bytes]:
    with upstream:
        while True:
            chunk = upstream.read(1024)
            if not chunk:
                return
            yield chunk


def load_config() -> RouterConfig:
    legacy_openai_base_url = os.environ.get(
        "INFRA_AI_OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    )
    legacy_openai_default_model = os.environ.get("INFRA_AI_OPENAI_DEFAULT_MODEL", "gpt-5.2")

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
        openai_responses_base_url=os.environ.get(
            "INFRA_AI_OPENAI_RESPONSES_BASE_URL",
            legacy_openai_base_url,
        ),
        openai_realtime_base_url=os.environ.get(
            "INFRA_AI_OPENAI_REALTIME_BASE_URL",
            "https://api.openai.com/v1/realtime",
        ),
        openai_models_base_url=os.environ.get(
            "INFRA_AI_OPENAI_MODELS_BASE_URL",
            legacy_openai_base_url,
        ),
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        openai_text_model=os.environ.get(
            "INFRA_AI_OPENAI_TEXT_MODEL",
            "gpt-5.2",
        ),
        openai_reasoning_model=os.environ.get(
            "INFRA_AI_OPENAI_REASONING_MODEL",
            legacy_openai_default_model,
        ),
        openai_tools_model=os.environ.get(
            "INFRA_AI_OPENAI_TOOLS_MODEL",
            os.environ.get("INFRA_AI_OPENAI_TEXT_MODEL", "gpt-5.2"),
        ),
        openai_realtime_model=os.environ.get(
            "INFRA_AI_OPENAI_REALTIME_MODEL",
            "gpt-realtime",
        ),
    )


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }


def main() -> None:
    config = load_config()
    try:
        app = RouterApplication(config)
    except ConfigValidationError as exc:
        raise SystemExit(str(exc)) from exc
    server = RouterHTTPServer((config.host, config.port), RouterRequestHandler, app)
    print(
        "infra-ai router listening on "
        f"http://{config.host}:{config.port} with routes "
        "auto|local -> local_vllm, reasoning -> gemini_fallback, heavy -> openai_reasoning"
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
