from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

JSONPrimitive: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]


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
    candidates: tuple[str, ...]
