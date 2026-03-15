from __future__ import annotations

import json
from abc import ABC, abstractmethod
from urllib import error, request

from router.schemas import JSONValue


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        payload: JSONValue | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class Provider(ABC):
    name: str

    @abstractmethod
    def list_models(self) -> tuple[int, JSONValue]:
        raise NotImplementedError

    @abstractmethod
    def chat_completions(self, payload: dict[str, JSONValue]) -> tuple[int, JSONValue]:
        raise NotImplementedError


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
        ) from exc
    except (error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", str(exc))
        raise ProviderError(
            f"{provider_name} request failed: {reason}",
            payload=_error_payload(
                f"{provider_name}_unavailable",
                str(reason),
            ),
        ) from exc


def _decode_json(raw: bytes, fallback_message: str) -> JSONValue:
    if not raw:
        return {}

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error_payload("upstream_non_json", fallback_message)


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
