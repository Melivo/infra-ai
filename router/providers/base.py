from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from socket import timeout as SocketTimeout
from urllib.response import addinfourl
from urllib import error, request

from router.normalization import GenerationRequest, NormalizedGeneration
from router.schemas import JSONValue

AUTO_MODEL_ALIASES = {"", "auto", "default", "router-default"}
ROUTER_CONTROL_FIELDS = {"route", "provider_slot", "tool_call", "allowed_tools"}
PUBLIC_PROVIDER_ERROR_TYPES = {
    "invalid_messages",
    "invalid_message",
    "invalid_role",
    "invalid_model_tool_call",
    "unsupported_role",
    "missing_user_content",
    "unsupported_content",
    "streaming_not_supported",
}


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        payload: JSONValue | None = None,
        should_fallback: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.should_fallback = should_fallback


class Provider(ABC):
    name: str

    @abstractmethod
    def list_models(self) -> tuple[int, JSONValue]:
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: GenerationRequest) -> NormalizedGeneration:
        raise NotImplementedError

    def chat_completions(self, request: GenerationRequest) -> tuple[int, JSONValue]:
        generation = self.generate(request)
        return 200, generation_to_chat_completion(generation)

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> addinfourl:
        del payload
        raise ProviderError(
            f"{self.name} does not support streaming via the router yet.",
            status_code=501,
            payload=_error_payload(
                "streaming_not_supported",
                f"Streaming is not available for {self.name} via the router yet.",
            ),
        )


def request_json(
    *,
    method: str,
    url: str,
    timeout_s: float,
    provider_name: str,
    payload: dict[str, JSONValue] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, JSONValue]:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = request.Request(url, data=data, headers=request_headers, method=method)

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            body = _decode_json(response.read(), response.reason)
            return response.getcode(), body
    except error.HTTPError as exc:
        body = _decode_json(exc.read(), exc.reason)
        raise ProviderError(
            f"{provider_name} returned status {exc.code}",
            status_code=exc.code,
            payload=body,
            should_fallback=exc.code >= 500 or exc.code == 429,
        ) from exc
    except (error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", str(exc))
        if _is_timeout_reason(reason):
            raise ProviderError(
                f"{provider_name} request timed out",
                status_code=504,
                payload=_error_payload(
                    "timeout",
                    "Upstream provider request timed out.",
                ),
                should_fallback=True,
            ) from exc

        raise ProviderError(
            f"{provider_name} request failed: {reason}",
            status_code=502,
            payload=_error_payload(
                f"{provider_name}_unavailable",
                str(reason),
            ),
            should_fallback=True,
        ) from exc


def request_stream(
    *,
    method: str,
    url: str,
    timeout_s: float,
    provider_name: str,
    payload: dict[str, JSONValue] | None = None,
    headers: dict[str, str] | None = None,
) -> addinfourl:
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    req = request.Request(url, data=data, headers=request_headers, method=method)

    try:
        return request.urlopen(req, timeout=timeout_s)
    except error.HTTPError as exc:
        body = _decode_json(exc.read(), exc.reason)
        raise ProviderError(
            f"{provider_name} returned status {exc.code}",
            status_code=exc.code,
            payload=body,
            should_fallback=exc.code >= 500 or exc.code == 429,
        ) from exc
    except (error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", str(exc))
        if _is_timeout_reason(reason):
            raise ProviderError(
                f"{provider_name} request timed out",
                status_code=504,
                payload=_error_payload(
                    "timeout",
                    "Upstream provider request timed out.",
                ),
                should_fallback=True,
            ) from exc

        raise ProviderError(
            f"{provider_name} request failed: {reason}",
            status_code=502,
            payload=_error_payload(
                f"{provider_name}_unavailable",
                str(reason),
            ),
            should_fallback=True,
        ) from exc


def resolve_model(payload: dict[str, JSONValue], default_model: str | None) -> str | None:
    model = payload.get("model")
    if isinstance(model, str) and model.strip().lower() not in AUTO_MODEL_ALIASES:
        return model.strip()
    return default_model


def with_resolved_model(
    payload: dict[str, JSONValue],
    *,
    default_model: str | None,
) -> dict[str, JSONValue]:
    outgoing_payload = without_router_fields(payload)
    resolved_model = resolve_model(payload, default_model)
    if not resolved_model:
        return outgoing_payload

    outgoing_payload["model"] = resolved_model
    return outgoing_payload


def without_router_fields(payload: dict[str, JSONValue]) -> dict[str, JSONValue]:
    return {
        key: value
        for key, value in payload.items()
        if key not in ROUTER_CONTROL_FIELDS
    }


def normalize_provider_error(error: ProviderError) -> JSONValue:
    error_type, message = _extract_payload_error(error.payload)
    if error_type in PUBLIC_PROVIDER_ERROR_TYPES and message:
        return _error_payload(error_type, message)

    normalized_type = _classify_provider_error_type(
        status_code=error.status_code,
        payload_error_type=error_type,
    )
    normalized_message = message or _default_provider_error_message(
        normalized_type,
        fallback_message=str(error),
    )
    return _error_payload(normalized_type, normalized_message)


def generation_to_chat_completion(generation: NormalizedGeneration) -> JSONValue:
    message_payload: dict[str, JSONValue] = {
        "role": generation.message.role,
        "content": generation.message.content or "",
    }
    if generation.message.tool_calls:
        message_payload["tool_calls"] = [
            {
                "id": tool_call.call_id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments),
                },
            }
            for tool_call in generation.message.tool_calls
        ]

    response: dict[str, JSONValue] = {
        "id": generation.response_id or "chatcmpl-router",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": message_payload,
                "finish_reason": generation.finish_reason
                or ("tool_calls" if generation.message.tool_calls else "stop"),
            }
        ],
    }
    if generation.model is not None:
        response["model"] = generation.model
    if generation.provider_name is not None:
        response["provider"] = generation.provider_name
    if generation.provider_slot is not None:
        response["provider_slot"] = generation.provider_slot
    if generation.usage is not None:
        response["usage"] = generation.usage
    return response


def _decode_json(raw: bytes, fallback_message: str) -> JSONValue:
    if not raw:
        return {}

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_payload("upstream_non_json", fallback_message)


def _extract_payload_error(payload: JSONValue | None) -> tuple[str | None, str | None]:
    if not isinstance(payload, Mapping):
        return None, None

    error_payload = payload.get("error")
    if isinstance(error_payload, Mapping):
        error_type = error_payload.get("type")
        message = error_payload.get("message")
        return (
            error_type if isinstance(error_type, str) else None,
            message if isinstance(message, str) else None,
        )

    message = payload.get("message")
    if isinstance(message, str):
        return None, message

    detail = payload.get("detail")
    if isinstance(detail, str):
        return None, detail

    return None, None


def _classify_provider_error_type(
    *,
    status_code: int,
    payload_error_type: str | None,
) -> str:
    if payload_error_type in {"streaming_not_supported", "timeout"}:
        return payload_error_type
    if payload_error_type == "upstream_non_json":
        return "upstream_bad_response"
    if payload_error_type and payload_error_type.endswith("_unavailable"):
        return "provider_unavailable"
    if status_code in {401, 403}:
        return "auth_error"
    if status_code == 429:
        return "rate_limited"
    if status_code in {408, 504}:
        return "timeout"
    if status_code >= 500:
        return "provider_unavailable"
    return "provider_error"


def _default_provider_error_message(error_type: str, *, fallback_message: str) -> str:
    if error_type == "auth_error":
        return "Upstream provider authentication failed."
    if error_type == "rate_limited":
        return "Upstream provider rate limit exceeded."
    if error_type == "timeout":
        return "Upstream provider request timed out."
    if error_type == "provider_unavailable":
        return "Upstream provider is unavailable."
    if error_type == "upstream_bad_response":
        return "Upstream provider returned an invalid response."
    return fallback_message


def _is_timeout_reason(reason: object) -> bool:
    if isinstance(reason, (TimeoutError, SocketTimeout)):
        return True
    if isinstance(reason, str):
        return "timed out" in reason.lower()
    return False


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
