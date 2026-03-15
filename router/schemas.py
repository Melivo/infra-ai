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
    enable_openai_fallback: bool
    openai_base_url: str
    openai_api_key: str | None


@dataclass(frozen=True)
class ProviderSelection:
    primary: str
    fallback: str | None = None
