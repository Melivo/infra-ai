from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Iterator
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import timeout as SocketTimeout
from typing import cast
from uuid import uuid4

from router.conversation import turns_to_generation
from router.normalization import GenerationRequest, request_messages_from_payload
from router.policies import (
    RoutingPolicyError,
    provider_for_route,
    provider_slot_for_route,
    route_enabled,
    route_streaming_supported,
    select_provider,
)
from router.providers.base import (
    Provider,
    ProviderError,
    generation_to_chat_completion,
    normalize_provider_error,
)
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
from router.tool_loop import ToolLoopEngine, ToolLoopError
from router.tools.example_tools import register_example_tools
from router.tools.orchestrator import ToolOrchestrator
from router.tools.policy import ToolExecutionDeniedError, ToolPolicy
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext, ToolSpec

CAPABILITIES_SCHEMA_VERSION = "1"
ROUTER_VERSION = "0.1.0"
ALLOWED_MESSAGE_ROLES = {"system", "user", "assistant"}
MODEL_AUTO_ALIASES = {"auto", "default", "router-default"}
LOGGER = logging.getLogger("infra_ai.router")
LOGGER.addHandler(logging.NullHandler())


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
        self.tool_registry = ToolRegistry()
        register_example_tools(self.tool_registry)
        self.tool_policy = ToolPolicy()
        self.tool_orchestrator = ToolOrchestrator(
            registry=self.tool_registry,
            policy=self.tool_policy,
        )
        self.tool_loop_engine = ToolLoopEngine(
            tool_orchestrator=self.tool_orchestrator,
            max_tool_steps=config.max_tool_steps,
            tool_timeout_s=config.tool_timeout_s,
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
                "tool_loop": {
                    "implemented": True,
                    "max_tool_steps": self.config.max_tool_steps,
                    "tool_timeout_s": self.config.tool_timeout_s,
                    "single_tool_call_per_step": True,
                    "parallel_tool_calls": False,
                },
                "tools": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "risk_level": spec.risk_level.value,
                        "capabilities": list(spec.capabilities),
                        "enabled_by_default": spec.enabled_by_default,
                    }
                    for spec in self.tool_registry.list_specs()
                ],
                "not_yet_supported": [
                    "streaming for reasoning route",
                    "streaming for heavy route",
                    "automatic provider selection beyond auto -> local",
                    "openai_realtime router execution path",
                    "openai_agent orchestration layer",
                    "multiple tool calls per model step",
                    "parallel tool calls",
                    "gemini native tool-call translation",
                    "agents and MCP integration",
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

        _log_route_selection(selection, streaming=False)
        try:
            generation_request = self._build_generation_request(
                payload=payload,
                provider_slot=selection.provider_slot,
            )
            result = asyncio.run(
                self.tool_loop_engine.run(
                    provider=self.providers[selection.provider_name],
                    request=generation_request,
                    request_id=cast(str, generation_request.metadata["request_id"]),
                    allowed_tools=_allowed_tool_names(payload.get("allowed_tools")),
                )
            )
        except ValueError as exc:
            return HTTPStatus.BAD_REQUEST, _error_payload("invalid_messages", str(exc))
        except ToolLoopError as exc:
            return exc.status_code, exc.payload
        except ProviderError as exc:
            _log_provider_error(
                provider_name=selection.provider_name,
                error=exc,
                streaming=False,
            )
            return exc.status_code, normalize_provider_error(exc)

        response = cast(
            dict[str, JSONValue],
            generation_to_chat_completion(turns_to_generation(result.turns)),
        )
        if result.tool_steps:
            response["tool_steps"] = result.tool_steps
        return HTTPStatus.OK, response

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> StreamingResponse:
        selection = select_provider(
            path="/v1/chat/completions",
            payload=payload,
            config=self.config,
        )
        provider = self.providers[selection.provider_name]
        payload_with_slot = _with_provider_slot(payload, selection.provider_slot)
        _log_route_selection(selection, streaming=True)
        try:
            upstream = provider.stream_chat_completions(payload_with_slot)
        except ProviderError as exc:
            _log_provider_error(
                provider_name=selection.provider_name,
                error=exc,
                streaming=True,
            )
            raise
        content_type = upstream.headers.get_content_type() or "text/event-stream"
        return StreamingResponse(
            status_code=upstream.getcode(),
            content_type=content_type,
            chunks=_iter_upstream_chunks(upstream),
        )

    def execute_tool_call(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        tool_call_payload = cast(dict[str, JSONValue], payload["tool_call"])
        tool_call = ToolCall(
            call_id=f"toolcall-{uuid4().hex}",
            name=cast(str, tool_call_payload["name"]),
            arguments=cast(dict[str, JSONValue], tool_call_payload["arguments"]),
        )

        try:
            result = asyncio.run(
                self.tool_loop_engine.run_tool_call(
                    tool_call=tool_call,
                    request_id=f"req-{uuid4().hex}",
                    current_tool_step=0,
                    allowed_tools=_allowed_tool_names(payload.get("allowed_tools")),
                )
            )
        except ToolLoopError as exc:
            return exc.status_code, exc.payload

        output_text = result.output_text or (
            json.dumps(result.output_json) if result.output_json is not None else ""
        )
        return (
            HTTPStatus.OK,
            {
                "id": f"chatcmpl-tool-{tool_call.call_id}",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": output_text or "",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "tool_result": {
                    "call_id": result.call_id,
                    "name": result.name,
                    "ok": result.ok,
                    "output_text": result.output_text,
                    "output_json": result.output_json,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                    "metadata": result.metadata,
                },
            },
        )

    def _build_generation_request(
        self,
        *,
        payload: dict[str, JSONValue],
        provider_slot: str | None,
    ) -> GenerationRequest:
        request_id = f"req-{uuid4().hex}"
        return GenerationRequest(
            messages=request_messages_from_payload(payload),
            tools=self._resolve_request_tools(
                allowed_tool_names=_allowed_tool_names(payload.get("allowed_tools")),
                request_id=request_id,
            ),
            model=_resolve_model_hint(payload.get("model")),
            provider_slot=provider_slot,
            temperature=_float_field(payload.get("temperature")),
            top_p=_float_field(payload.get("top_p")),
            max_tokens=_int_field(payload.get("max_tokens")),
            metadata={"request_id": request_id},
        )

    def _resolve_request_tools(
        self,
        *,
        allowed_tool_names: set[str] | None,
        request_id: str,
    ) -> list[ToolSpec]:
        tool_specs: list[ToolSpec] = []
        ctx = ToolContext(
            request_id=request_id,
            max_tool_steps=self.config.max_tool_steps,
            tool_timeout_s=self.config.tool_timeout_s,
        )
        for spec in self.tool_registry.list_specs():
            if allowed_tool_names is not None and spec.name not in allowed_tool_names:
                continue
            try:
                self.tool_policy.check(spec, ctx)
            except ToolExecutionDeniedError:
                continue
            tool_specs.append(spec)
        return tool_specs

    def _run_provider_action(
        self,
        provider_name: str,
        action: Callable[[Provider], tuple[int, JSONValue]],
    ) -> tuple[int, JSONValue]:
        provider = self.providers[provider_name]
        try:
            return action(provider)
        except ProviderError as exc:
            _log_provider_error(provider_name=provider_name, error=exc, streaming=False)
            return exc.status_code, normalize_provider_error(exc)


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

        _log_chat_request(payload)
        if "tool_call" in payload:
            self._write_response(*self.server.app.execute_tool_call(payload))
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
                normalize_provider_error(exc),
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


def _configure_logging() -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _build_log_event(event: str, **fields: object) -> str:
    payload: dict[str, object] = {
        "component": "router",
        "event": event,
    }
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    return json.dumps(payload, sort_keys=True)


def _log_info(event: str, **fields: object) -> None:
    LOGGER.info(_build_log_event(event, **fields))


def _log_warning(event: str, **fields: object) -> None:
    LOGGER.warning(_build_log_event(event, **fields))


def _log_chat_request(payload: dict[str, JSONValue]) -> None:
    route = payload.get("route")
    model = payload.get("model")
    messages = payload.get("messages")
    _log_info(
        "chat_request_received",
        route_requested=route if isinstance(route, str) else "auto",
        streaming=payload.get("stream") is True,
        messages_count=len(messages) if isinstance(messages, list) else None,
        model_mode=_describe_model_mode(model),
        tool_name=_extract_tool_name(payload.get("tool_call")),
    )


def _log_route_selection(selection, *, streaming: bool) -> None:
    _log_info(
        "route_selected",
        routing_mode=selection.routing_mode,
        provider=selection.provider_name,
        provider_slot=selection.provider_slot,
        streaming=streaming,
    )


def _log_provider_error(
    *,
    provider_name: str,
    error: ProviderError,
    streaming: bool,
) -> None:
    normalized_error = normalize_provider_error(error)
    error_type = _extract_error_type(normalized_error)
    log_event = "provider_timeout" if error_type == "timeout" else "provider_error"
    _log_warning(
        log_event,
        provider=provider_name,
        streaming=streaming,
        status_code=error.status_code,
        error_type=error_type,
    )


def _describe_model_mode(model: JSONValue) -> str:
    if not isinstance(model, str):
        return "omitted"
    normalized_model = model.strip().lower()
    if normalized_model in MODEL_AUTO_ALIASES:
        return "auto"
    return "explicit"


def _extract_tool_name(tool_call: JSONValue) -> str | None:
    if not isinstance(tool_call, dict):
        return None
    name = tool_call.get("name")
    if isinstance(name, str):
        return name
    return None


def _extract_error_type(payload: JSONValue) -> str | None:
    if not isinstance(payload, dict):
        return None
    error_payload = payload.get("error")
    if isinstance(error_payload, dict):
        error_type = error_payload.get("type")
        if isinstance(error_type, str):
            return error_type
    return None


def _allowed_tool_names(allowed_tools: JSONValue) -> set[str] | None:
    if allowed_tools is None:
        return None
    if not isinstance(allowed_tools, list):
        return None
    return {
        item.strip()
        for item in allowed_tools
        if isinstance(item, str) and item.strip()
    }


def _resolve_model_hint(model: JSONValue) -> str | None:
    if not isinstance(model, str):
        return None
    normalized_model = model.strip()
    if not normalized_model or normalized_model.lower() in MODEL_AUTO_ALIASES:
        return None
    return normalized_model


def _float_field(value: JSONValue) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int_field(value: JSONValue) -> int | None:
    if isinstance(value, int):
        return value
    return None


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

    if "allowed_tools" in payload:
        _validate_allowed_tools(payload["allowed_tools"])

    if "tool_call" in payload:
        _validate_tool_call(payload["tool_call"])
        if payload.get("stream") is True:
            raise RequestValidationError(
                "invalid_tool_call",
                "tool_call requests do not support stream=true.",
            )

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


def _validate_tool_call(tool_call: JSONValue) -> None:
    if not isinstance(tool_call, dict):
        raise RequestValidationError(
            "invalid_tool_call",
            "The tool_call field must be an object with name and arguments.",
        )

    name = tool_call.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RequestValidationError(
            "invalid_tool_call",
            "The tool_call.name field must be a non-blank string.",
        )

    arguments = tool_call.get("arguments")
    if not isinstance(arguments, dict):
        raise RequestValidationError(
            "invalid_tool_call",
            "The tool_call.arguments field must be a JSON object.",
        )


def _validate_allowed_tools(allowed_tools: JSONValue) -> None:
    if allowed_tools is None:
        return

    if not isinstance(allowed_tools, list):
        raise RequestValidationError(
            "invalid_allowed_tools",
            "The allowed_tools field must be null or a JSON array of tool names.",
        )

    for item in allowed_tools:
        if not isinstance(item, str) or not item.strip():
            raise RequestValidationError(
                "invalid_allowed_tools",
                "Each allowed_tools entry must be a non-blank string.",
            )


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
    if config.max_tool_steps <= 0:
        errors.append("INFRA_AI_MAX_TOOL_STEPS must be greater than 0.")
    if config.tool_timeout_s <= 0:
        errors.append("INFRA_AI_TOOL_TIMEOUT_S must be greater than 0.")

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
        max_tool_steps=int(os.environ.get("INFRA_AI_MAX_TOOL_STEPS", "4")),
        tool_timeout_s=float(os.environ.get("INFRA_AI_TOOL_TIMEOUT_S", "30")),
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
    _configure_logging()
    config = load_config()
    try:
        app = RouterApplication(config)
    except ConfigValidationError as exc:
        raise SystemExit(str(exc)) from exc
    server = RouterHTTPServer((config.host, config.port), RouterRequestHandler, app)
    _log_info(
        "router_started",
        host=config.host,
        port=config.port,
        request_timeout_s=config.request_timeout_s,
        gemini_enabled=config.enable_gemini_fallback,
        openai_enabled=config.enable_openai_fallback,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
