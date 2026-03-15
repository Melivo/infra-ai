from __future__ import annotations

from collections.abc import Mapping

from router.schemas import (
    JSONValue,
    OpenAISlot,
    ProviderSelection,
    RouterConfig,
    ROUTING_MODES,
    RoutingMode,
)


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
    provider_name = provider_for_route(routing_mode)
    provider_slot = provider_slot_for_route(routing_mode)
    if route_enabled(routing_mode, config):
        return ProviderSelection(
            routing_mode=routing_mode,
            provider_name=provider_name,
            provider_slot=provider_slot,
        )

    raise RoutingPolicyError(
        f"Route {routing_mode} is not enabled.",
        status_code=503,
        payload=_error_payload(
            "route_unavailable",
            f"route={routing_mode} requires an enabled {provider_name} provider in router config.",
        ),
    )


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
    if normalized_route not in ROUTING_MODES:
        raise RoutingPolicyError(
            f"Unsupported route {route!r}.",
            status_code=400,
            payload=_error_payload(
                "invalid_route",
                "Supported route values are: auto, local, reasoning, heavy.",
            ),
        )

    return normalized_route  # type: ignore[return-value]


def route_enabled(route: RoutingMode, config: RouterConfig) -> bool:
    if route in {"auto", "local"}:
        return True
    if route == "reasoning":
        return config.enable_gemini_fallback
    return config.enable_openai_fallback


def provider_for_route(route: RoutingMode) -> str:
    if route in {"auto", "local"}:
        return "local_vllm"
    if route == "reasoning":
        return "gemini_fallback"
    return "openai_responses"


def provider_slot_for_route(route: RoutingMode) -> OpenAISlot | None:
    if route == "heavy":
        return "openai_reasoning"
    return None


def route_streaming_supported(route: RoutingMode) -> bool:
    return route in {"auto", "local"}


def _error_payload(error_type: str, message: str) -> JSONValue:
    return {
        "error": {
            "type": error_type,
            "message": message,
        }
    }
