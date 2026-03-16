from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal, TypeAlias

JSONPrimitive: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
RoutingMode: TypeAlias = Literal["auto", "local", "reasoning", "heavy"]
ROUTING_MODES: tuple[RoutingMode, ...] = ("auto", "local", "reasoning", "heavy")
OpenAISlot: TypeAlias = Literal[
    "openai_text",
    "openai_reasoning",
    "openai_tools",
    "openai_agent",
    "openai_realtime",
    "openai_models",
]


@dataclass(frozen=True)
class RouterConfig:
    host: str
    port: int
    request_timeout_s: float
    max_tool_steps: int
    tool_timeout_s: float
    local_vllm_base_url: str
    local_vllm_default_model: str
    enable_gemini_fallback: bool
    gemini_base_url: str
    gemini_api_key: str | None
    gemini_default_model: str | None
    enable_openai_fallback: bool
    openai_responses_base_url: str
    openai_realtime_base_url: str
    openai_models_base_url: str
    openai_api_key: str | None
    openai_text_model: str | None
    openai_reasoning_model: str | None
    openai_tools_model: str | None
    openai_realtime_model: str | None


@dataclass(frozen=True)
class ProviderSelection:
    routing_mode: RoutingMode
    provider_name: str
    provider_slot: OpenAISlot | None = None


@dataclass
class StreamingResponse:
    status_code: int
    content_type: str
    chunks: Iterator[bytes]
