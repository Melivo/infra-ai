from __future__ import annotations

import argparse
import json
import os
import sys
from urllib import error, request

ROUTING_MODES = ("auto", "local", "reasoning", "heavy")


def build_payload(
    *,
    prompt: str,
    model: str,
    route: str,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
    stream: bool,
) -> dict[str, object]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    return {
        "model": model,
        "route": route,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream,
    }


def request_chat(*, base_url: str, payload: dict[str, object], timeout_s: float) -> dict[str, object]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            raw_response = response.read().decode("utf-8")
    except error.HTTPError as exc:
        raw_response = exc.read().decode("utf-8") or "{}"
        raise SystemExit(f"router returned HTTP {exc.code}: {raw_response}") from exc
    except error.URLError as exc:
        raise SystemExit(f"could not reach router at {url}: {exc.reason}") from exc

    decoded = json.loads(raw_response)
    if not isinstance(decoded, dict):
        raise SystemExit("router response was not a JSON object")
    return decoded


def stream_chat(
    *,
    base_url: str,
    payload: dict[str, object],
    timeout_s: float,
    raw: bool,
) -> None:
    url = f"{base_url.rstrip('/')}/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_s) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8")
                if raw:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                    continue

                event = line.strip()
                if not event.startswith("data:"):
                    continue

                data = event[5:].strip()
                if not data or data == "[DONE]":
                    continue

                chunk = json.loads(data)
                text = extract_stream_text(chunk)
                if text:
                    sys.stdout.write(text)
                    sys.stdout.flush()
    except error.HTTPError as exc:
        raw_response = exc.read().decode("utf-8") or "{}"
        raise SystemExit(f"router returned HTTP {exc.code}: {raw_response}") from exc
    except error.URLError as exc:
        raise SystemExit(f"could not reach router at {url}: {exc.reason}") from exc

    if not raw:
        sys.stdout.write("\n")


def extract_stream_text(chunk: dict[str, object]) -> str:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""

    delta = first_choice.get("delta")
    if not isinstance(delta, dict):
        return ""

    content = delta.get("content")
    if isinstance(content, str):
        return content

    return ""


def extract_text(response: dict[str, object]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return json.dumps(response, indent=2)

    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return json.dumps(response, indent=2)

    message = first_choice.get("message")
    if not isinstance(message, dict):
        return json.dumps(response, indent=2)

    content = message.get("content")
    if isinstance(content, str):
        return content

    return json.dumps(response, indent=2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a prompt to the infra-ai router.")
    parser.add_argument("prompt", nargs="*", help="Prompt text. Reads stdin when omitted.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("INFRA_AI_ROUTER_BASE_URL", "http://127.0.0.1:8010/v1"),
        help="Router base URL, usually http://127.0.0.1:8010/v1.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("INFRA_AI_ROUTER_MODEL", "auto"),
        help="Router-facing model hint. Use auto to let the backend resolve provider defaults.",
    )
    parser.add_argument(
        "--route",
        choices=ROUTING_MODES,
        default=os.environ.get("INFRA_AI_ROUTER_ROUTE", "auto"),
        help="Explicit router mode: auto, local, reasoning or heavy.",
    )
    parser.add_argument(
        "--system",
        default=os.environ.get("INFRA_AI_ROUTER_SYSTEM_PROMPT"),
        help="Optional system prompt sent through the router.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(os.environ.get("INFRA_AI_ROUTER_TEMPERATURE", "0.2")),
        help="Sampling temperature passed to the router.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("INFRA_AI_ROUTER_MAX_TOKENS", "512")),
        help="Maximum output tokens passed to the router.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("INFRA_AI_ROUTER_TIMEOUT_S", "120")),
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Request streamed output from the router. Currently intended for local routing.",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Print raw JSON, or raw event-stream lines when combined with --stream.",
    )
    return parser.parse_args()


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return " ".join(args.prompt).strip()

    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    raise SystemExit("prompt required as argument or via stdin")


def main() -> None:
    args = parse_args()
    prompt = _read_prompt(args)
    payload = build_payload(
        prompt=prompt,
        model=args.model,
        route=args.route,
        system_prompt=args.system,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        stream=args.stream,
    )

    if args.stream:
        stream_chat(
            base_url=args.base_url,
            payload=payload,
            timeout_s=args.timeout,
            raw=args.raw,
        )
        return

    response = request_chat(
        base_url=args.base_url,
        payload=payload,
        timeout_s=args.timeout,
    )

    if args.raw:
        print(json.dumps(response, indent=2))
        return

    print(extract_text(response))


if __name__ == "__main__":
    main()
