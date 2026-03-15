#!/usr/bin/env python3
from __future__ import annotations

import json
import os

from cli.main import extract_text, request_chat, stream_chat


def main() -> None:
    route = os.environ.get("INFRA_AI_ROUTER_ROUTE", "auto")
    stream = os.environ.get("INFRA_AI_ROUTER_STREAM", "0").lower() in {"1", "true", "yes"}
    base_url = os.environ.get("INFRA_AI_ROUTER_BASE_URL", "http://127.0.0.1:8010/v1")
    payload = {
        "model": os.environ.get("INFRA_AI_ROUTER_MODEL", "auto"),
        "route": route,
        "messages": [
            {
                "role": "user",
                "content": os.environ.get(
                    "INFRA_AI_SMOKE_PROMPT",
                    "Antworte in einem kurzen Satz: Laeuft der infra-ai Router?",
                ),
            }
        ],
        "temperature": 0.2,
        "max_tokens": 128,
        "stream": stream,
    }
    timeout_s = float(os.environ.get("INFRA_AI_ROUTER_TIMEOUT_S", "120"))

    if stream:
        stream_chat(
            base_url=base_url,
            payload=payload,
            timeout_s=timeout_s,
            raw=os.environ.get("INFRA_AI_SMOKE_RAW", "0").lower() in {"1", "true", "yes"},
        )
        return

    response = request_chat(
        base_url=base_url,
        payload=payload,
        timeout_s=timeout_s,
    )

    if os.environ.get("INFRA_AI_SMOKE_RAW", "0").lower() in {"1", "true", "yes"}:
        print(json.dumps(response, indent=2))
        return

    print(extract_text(response))


if __name__ == "__main__":
    main()
