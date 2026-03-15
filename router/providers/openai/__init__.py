"""OpenAI provider building blocks split by API family."""

from router.providers.openai.models import OpenAIModelsClient
from router.providers.openai.realtime import OPENAI_REALTIME_SLOT
from router.providers.openai.responses import (
    OPENAI_AGENT_SLOT,
    OPENAI_RESPONSES_SLOTS,
    OpenAIResponsesProvider,
)

__all__ = [
    "OPENAI_AGENT_SLOT",
    "OPENAI_REALTIME_SLOT",
    "OPENAI_RESPONSES_SLOTS",
    "OpenAIModelsClient",
    "OpenAIResponsesProvider",
]
