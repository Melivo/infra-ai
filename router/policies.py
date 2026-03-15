from __future__ import annotations

from collections.abc import Mapping

from router.schemas import JSONValue, ProviderSelection, RouterConfig, RoutingMode

ALLOWED_ROUTING_MODES = {"auto", "local", "reasoning", "heavy"}


class RoutingPolicyError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        payload: JSONValue,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def select_provider(
    *,
    path: str,
    payload: Mapping[str, object] | None,
    config: RouterConfig,
) -> ProviderSelection:
    if path == "/v1/models":
        return ProviderSelection(routing_mode="local", provider_name="local_vllm")

    routing_mode = resolve_routing_mode(payload)
    if routing_mode in {"auto", "local"}:
        return ProviderSelection(routing_mode=routing_mode, provider_name="local_vllm")

    if routing_mode == "reasoning":
        if not config.enable_gemini_fallback:
            raise RoutingPolicyError(
                "Reasoning route is not enabled.",
                status_code=503,
                payload=_error_payload(
                    "route_unavailable",
                    "route=reasoning requires an enabled Gemini provider in router config.",
                ),
            )
        return ProviderSelection(routing_mode=routing_mode, provider_name="gemini_fallback")

    if not config.enable_openai_fallback:
        raise RoutingPolicyError(
            "Heavy route is not enabled.",
            status_code=503,
            payload=_error_payload(
                "route_unavailable",
                "route=heavy requires an enabled OpenAI provider in router config.",
            ),
        )
    return ProviderSelection(routing_mode=routing_mode, provider_name="openai_fallback")


def resolve_routing_mode(payload: Mapping[str, object] | None) -> RoutingMode:
    if payload is None or "route" not in payload:
        return "auto"

    route = payload.get("route")
    if not isinstance(route, str):
        raise RoutingPolicyError(
            "Route must be a string.",
            status_code=400,
            payload=_error_payload(
                "invalid_route",
                "The route field must be one of: auto, local, reasoning, heavy.",
            ),
        )

    normalized_route = route.strip().lower()
    if normalized_route not in ALLOWED_ROUTING_MODES:
        raise RoutingPolicyError(
            f"Unsupported route {route!r}.",
            status_code=400,
            payload=_error_payload(
                "invalid_route",
                "Supported route values are: auto, local, reasoning, heavy.",
            ),
        )

    return normalized_route  # type: ignore[return-value]


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
