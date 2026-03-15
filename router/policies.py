from __future__ import annotations

from collections.abc import Mapping

from router.schemas import ProviderSelection, RouterConfig


def select_provider(
    *,
    path: str,
    payload: Mapping[str, object] | None,
    config: RouterConfig,
) -> ProviderSelection:
    del payload

    if path == "/v1/models":
        return ProviderSelection(candidates=("local_vllm",))

    candidates = ["local_vllm"]
    if config.enable_gemini_fallback:
        candidates.append("gemini_fallback")
    if config.enable_openai_fallback:
        candidates.append("openai_fallback")

    return ProviderSelection(candidates=tuple(candidates))
