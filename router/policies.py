from __future__ import annotations

from collections.abc import Mapping

from router.schemas import ProviderSelection, RouterConfig


def select_provider(
    *,
    path: str,
    payload: Mapping[str, object] | None,
    config: RouterConfig,
) -> ProviderSelection:
    del path
    del payload

    fallback = "openai_fallback" if config.enable_openai_fallback else None
    return ProviderSelection(primary="local_vllm", fallback=fallback)
