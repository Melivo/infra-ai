from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, TypeAlias

JSONPrimitive: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
RoutingMode: TypeAlias = Literal["auto", "local", "reasoning", "heavy"]
ROUTING_MODES: tuple[RoutingMode, ...] = ("auto", "local", "reasoning", "heavy")


@dataclass(frozen=True)
class RouterConfig:
    host: str
    port: int
    request_timeout_s: float
    local_vllm_base_url: str
    local_vllm_default_model: str
    enable_gemini_fallback: bool
    gemini_base_url: str
    gemini_api_key: str | None
    gemini_default_model: str | None
    enable_openai_fallback: bool
    openai_base_url: str
    openai_api_key: str | None
    openai_default_model: str | None


@dataclass(frozen=True)
class ProviderSelection:
    routing_mode: RoutingMode
    provider_name: str


@dataclass
class StreamingResponse:
    status_code: int
    content_type: str
    chunks: Iterator[bytes]
