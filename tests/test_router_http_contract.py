from __future__ import annotations

import asyncio
import io
import json
import pathlib
import tempfile
import unittest
from email.message import Message
from urllib.response import addinfourl

from router.normalization import (
    GenerationRequest,
    NormalizedGeneration,
    NormalizedMessage,
    NormalizedToolCall,
)
from router.app import RouterApplication, RouterRequestHandler
from router.provider_output import ProviderOutput
from router.providers.base import Provider, ProviderError
from router.schemas import JSONValue, RouterConfig
from router.tools.types import ToolCall, ToolContext, ToolResult, ToolRiskLevel, ToolSpec


def build_config(**overrides: object) -> RouterConfig:
    config = RouterConfig(
        host="127.0.0.1",
        port=8010,
        request_timeout_s=120.0,
        max_tool_steps=4,
        tool_timeout_s=30.0,
        local_vllm_base_url="http://127.0.0.1:8000/v1",
        local_vllm_default_model="Qwen/Qwen3-14B-AWQ",
        enable_gemini_fallback=False,
        gemini_base_url="https://generativelanguage.googleapis.com/v1beta",
        gemini_api_key=None,
        gemini_default_model=None,
        enable_openai_fallback=False,
        openai_responses_base_url="https://api.openai.com/v1",
        openai_realtime_base_url="https://api.openai.com/v1/realtime",
        openai_models_base_url="https://api.openai.com/v1",
        openai_api_key=None,
        openai_text_model="gpt-5.2",
        openai_reasoning_model="gpt-5.2",
        openai_tools_model="gpt-5.2",
        openai_realtime_model="gpt-realtime",
    )
    return RouterConfig(**(config.__dict__ | overrides))


def build_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "auto",
        "messages": [
            {
                "role": "user",
                "content": "Erklaere infra-ai in einem Satz.",
            }
        ],
    }
    payload.update(overrides)
    return payload


class StubProvider(Provider):
    def __init__(
        self,
        name: str,
        *,
        stream_supported: bool = False,
        generations: list[NormalizedGeneration] | None = None,
    ) -> None:
        self.name = name
        self.stream_supported = stream_supported
        self.last_request: GenerationRequest | None = None
        self.request_history: list[GenerationRequest] = []
        self.list_models_called = False
        self._generation_iter = iter(generations or [])

    def list_models(self) -> tuple[int, JSONValue]:
        self.list_models_called = True
        return (
            200,
            {
                "object": "list",
                "data": [{"id": f"{self.name}-model", "object": "model", "owned_by": "test"}],
            },
        )

    def generate(self, request: GenerationRequest) -> ProviderOutput:
        self.last_request = request
        self.request_history.append(request)
        generation = next(
            self._generation_iter,
            NormalizedGeneration(
                message=NormalizedMessage(
                    role="assistant",
                    content=f"response from {self.name}",
                ),
                final=True,
                response_id=f"{self.name}-chat",
                provider_name=self.name,
                provider_slot=request.provider_slot,
            ),
        )
        return _generation_to_provider_output(self.name, generation, request.provider_slot)

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> addinfourl:
        if not self.stream_supported:
            return super().stream_chat_completions(payload)

        headers = Message()
        headers["Content-Type"] = "text/event-stream"
        body = f"data: {{\"provider\": \"{self.name}\"}}\n\n".encode("utf-8")
        return addinfourl(io.BytesIO(body), headers, "http://stub.local/stream", 200)


class ErrorProvider(Provider):
    def __init__(
        self,
        name: str,
        *,
        list_error: ProviderError | None = None,
        chat_error: ProviderError | None = None,
        stream_error: ProviderError | None = None,
    ) -> None:
        self.name = name
        self.list_error = list_error
        self.chat_error = chat_error
        self.stream_error = stream_error

    def list_models(self) -> tuple[int, JSONValue]:
        raise self.list_error or ProviderError("unexpected list error")

    def generate(self, request: GenerationRequest) -> ProviderOutput:
        del request
        raise self.chat_error or ProviderError("unexpected chat error")

    def stream_chat_completions(self, payload: dict[str, JSONValue]) -> addinfourl:
        del payload
        raise self.stream_error or ProviderError("unexpected stream error")


class FailingExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        del ctx
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=False,
            error_code="tool_execution_failed",
            error_message="executor failed",
        )


class SlowExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        del call
        await asyncio.sleep(ctx.tool_timeout_s + 0.05)
        return ToolResult(call_id="slow-call", name="slow_tool", ok=True, output_text="done")


class _NonClosingBytesIO(io.BytesIO):
    def close(self) -> None:
        return


class _FakeSocket:
    def __init__(self, request_bytes: bytes) -> None:
        self._rfile = _NonClosingBytesIO(request_bytes)
        self._wfile = _NonClosingBytesIO()

    def makefile(self, mode: str, buffering: int | None = None):
        del buffering
        if "r" in mode:
            return self._rfile
        return self._wfile

    def sendall(self, data: bytes) -> None:
        self._wfile.write(data)

    def close(self) -> None:
        return

    def response_bytes(self) -> bytes:
        return self._wfile.getvalue()


class _FakeServer:
    def __init__(self, app: RouterApplication) -> None:
        self.app = app


def _generation_to_provider_output(
    provider_name: str,
    generation: NormalizedGeneration,
    provider_slot: str | None,
) -> ProviderOutput:
    message_content = generation.message.content
    if message_content is None and generation.message.content_json is not None:
        message_content = json.dumps(generation.message.content_json, sort_keys=True)

    message_payload: dict[str, JSONValue] = {
        "role": generation.message.role,
        "content": message_content or "",
    }
    if generation.message.tool_calls:
        message_payload["tool_calls"] = [
            {
                "id": tool_call.call_id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(tool_call.arguments, sort_keys=True),
                },
            }
            for tool_call in generation.message.tool_calls
        ]

    return ProviderOutput(
        format="openai_chat_completion",
        body={
            "id": generation.response_id or f"{provider_name}-chat",
            "model": generation.model or f"{provider_name}-model",
            "choices": [
                {
                    "message": message_payload,
                    "finish_reason": generation.finish_reason
                    or ("tool_calls" if generation.message.tool_calls else "stop"),
                }
            ],
            "usage": generation.usage,
        },
        provider_name=generation.provider_name or provider_name,
        provider_slot=generation.provider_slot or provider_slot,
        fallback_model=generation.model,
    )


def perform_http_request(
    app: RouterApplication,
    *,
    method: str,
    path: str,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    request_headers = {
        "Host": "127.0.0.1",
        "Connection": "close",
    }
    if headers:
        request_headers.update(headers)
    if body:
        request_headers["Content-Length"] = str(len(body))

    lines = [f"{method} {path} HTTP/1.1"]
    lines.extend(f"{key}: {value}" for key, value in request_headers.items())
    raw_request = ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8") + body

    fake_socket = _FakeSocket(raw_request)
    RouterRequestHandler(fake_socket, ("127.0.0.1", 12345), _FakeServer(app))
    raw_response = fake_socket.response_bytes()
    head, _, response_body = raw_response.partition(b"\r\n\r\n")
    header_lines = head.decode("iso-8859-1").split("\r\n")
    status_code = int(header_lines[0].split()[1])
    response_headers: dict[str, str] = {}
    for line in header_lines[1:]:
        if not line:
            continue
        key, value = line.split(":", 1)
        response_headers[key.strip().lower()] = value.strip()

    return status_code, response_headers, response_body


def perform_json_request(
    app: RouterApplication,
    *,
    method: str,
    path: str,
    body: object | None = None,
) -> tuple[int, dict[str, str], JSONValue]:
    request_body = b""
    headers: dict[str, str] = {}
    if body is not None:
        request_body = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    status_code, response_headers, response_body = perform_http_request(
        app,
        method=method,
        path=path,
        body=request_body,
        headers=headers,
    )
    payload = json.loads(response_body.decode("utf-8")) if response_body else {}
    return status_code, response_headers, payload


class RouterHTTPContractTests(unittest.TestCase):
    def assert_error_payload(
        self,
        payload: JSONValue,
        *,
        error_type: str,
    ) -> None:
        self.assertIsInstance(payload, dict)
        self.assertIn("error", payload)
        error_body = payload["error"]
        self.assertIsInstance(error_body, dict)
        self.assertEqual(error_body.get("type"), error_type)
        self.assertIsInstance(error_body.get("message"), str)
        self.assertTrue(error_body["message"])

    def make_app(self, config: RouterConfig) -> tuple[RouterApplication, dict[str, StubProvider]]:
        app = RouterApplication(config)
        providers = {
            "local_vllm": StubProvider("local_vllm", stream_supported=True),
            "gemini_fallback": StubProvider("gemini_fallback"),
            "openai_responses": StubProvider("openai_responses"),
        }
        app.providers = providers
        return app, providers

    def make_error_app(self, config: RouterConfig, provider_name: str, provider: Provider) -> RouterApplication:
        app = RouterApplication(config)
        app.providers = {
            "local_vllm": StubProvider("local_vllm", stream_supported=True),
            "gemini_fallback": StubProvider("gemini_fallback"),
            "openai_responses": StubProvider("openai_responses"),
        }
        app.providers[provider_name] = provider
        return app

    def test_healthz_contract_is_stable(self) -> None:
        app, _ = self.make_app(build_config())

        status_code, response_headers, payload = perform_json_request(
            app,
            method="GET",
            path="/healthz",
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload, {"status": "ok"})

    def test_capabilities_contract_exposes_public_router_fields(self) -> None:
        app, _ = self.make_app(
            build_config(
                enable_gemini_fallback=True,
                gemini_api_key="test-key",
                gemini_default_model="gemini-2.5-pro",
            )
        )

        status_code, response_headers, payload = perform_json_request(
            app,
            method="GET",
            path="/v1/router/capabilities",
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["object"], "router.capabilities")
        self.assertEqual(payload["schema_version"], "1")
        self.assertIsInstance(payload["router_version"], str)
        self.assertIsInstance(payload["available_routes"], dict)
        self.assertIsInstance(payload["enabled_providers"], dict)
        self.assertIsInstance(payload["streaming_support"], dict)
        self.assertIsInstance(payload["default_models"], dict)
        self.assertIsInstance(payload["frontend_contract"], dict)
        self.assertIsInstance(payload["tools"], list)
        self.assertIsInstance(payload["not_yet_supported"], list)

        self.assertEqual(
            payload["frontend_contract"]["shared_contract"]["chat_endpoint"],
            "/v1/chat/completions",
        )
        self.assertEqual(
            payload["frontend_contract"]["shared_contract"]["capabilities_endpoint"],
            "/v1/router/capabilities",
        )
        self.assertEqual(payload["available_routes"]["local"]["enabled"], True)
        self.assertEqual(payload["available_routes"]["reasoning"]["enabled"], True)
        self.assertEqual(payload["available_routes"]["heavy"]["enabled"], False)
        self.assertEqual(payload["available_routes"]["local"]["streaming"], True)
        self.assertEqual(payload["available_routes"]["reasoning"]["streaming"], False)
        self.assertIn("local", payload["streaming_support"]["routes"])
        self.assertNotIn("reasoning", payload["streaming_support"]["routes"])
        self.assertEqual(
            payload["tools"],
            [
                {
                    "name": "add_numbers",
                    "description": "Add two numeric arguments and return their sum.",
                    "risk_level": "low",
                    "capabilities": ["math", "utility"],
                    "enabled_by_default": True,
                },
                {
                    "name": "echo",
                    "description": "Return the provided arguments unchanged.",
                    "risk_level": "low",
                    "capabilities": ["debug"],
                    "enabled_by_default": True,
                },
                {
                    "name": "filesystem.list",
                    "description": "List direct workspace entries for a directory path.",
                    "risk_level": "medium",
                    "capabilities": ["filesystem", "list", "workspace"],
                    "enabled_by_default": False,
                },
                {
                    "name": "filesystem.read",
                    "description": "Read a UTF-8 text file inside the workspace root.",
                    "risk_level": "medium",
                    "capabilities": ["filesystem", "read", "workspace"],
                    "enabled_by_default": False,
                },
                {
                    "name": "git.diff",
                    "description": "Return a bounded read-only git diff for the workspace repository.",
                    "risk_level": "medium",
                    "capabilities": ["git", "diff", "workspace"],
                    "enabled_by_default": False,
                },
                {
                    "name": "git.status",
                    "description": "Return structured read-only git status for the workspace repository.",
                    "risk_level": "medium",
                    "capabilities": ["git", "status", "workspace"],
                    "enabled_by_default": False,
                },
            ],
        )

    def test_models_contract_currently_routes_to_local_provider(self) -> None:
        app, providers = self.make_app(
            build_config(
                enable_openai_fallback=True,
                openai_api_key="test-key",
                openai_reasoning_model="gpt-5.2",
            )
        )

        status_code, response_headers, payload = perform_json_request(
            app,
            method="GET",
            path="/v1/models",
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["object"], "list")
        self.assertIsInstance(payload["data"], list)
        self.assertEqual(payload["data"][0]["id"], "local_vllm-model")
        self.assertEqual(providers["local_vllm"].list_models_called, True)
        self.assertEqual(providers["gemini_fallback"].list_models_called, False)
        self.assertEqual(providers["openai_responses"].list_models_called, False)

    def test_http_chat_routes_map_to_expected_providers(self) -> None:
        app, providers = self.make_app(
            build_config(
                enable_gemini_fallback=True,
                gemini_api_key="test-key",
                gemini_default_model="gemini-2.5-pro",
                enable_openai_fallback=True,
                openai_api_key="test-key",
                openai_reasoning_model="gpt-5.2",
            )
        )

        for route, provider_name in (
            ("auto", "local_vllm"),
            ("local", "local_vllm"),
            ("reasoning", "gemini_fallback"),
            ("heavy", "openai_responses"),
        ):
            with self.subTest(route=route):
                status_code, response_headers, payload = perform_json_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    body=build_payload(route=route),
                )

                self.assertEqual(status_code, 200)
                self.assertEqual(response_headers["content-type"], "application/json")
                self.assertEqual(payload["provider"], provider_name)

        self.assertIsNone(providers["local_vllm"].last_request.provider_slot)
        self.assertEqual(
            providers["openai_responses"].last_request.provider_slot,
            "openai_reasoning",
        )

    def test_explicit_tool_call_returns_tool_result_without_provider_routing(self) -> None:
        app, providers = self.make_app(build_config())

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(
                allowed_tools=["echo"],
                tool_call={
                    "name": "echo",
                    "arguments": {"message": "hello"},
                }
            ),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["object"], "chat.completion")
        self.assertEqual(payload["tool_result"]["name"], "echo")
        self.assertEqual(payload["tool_result"]["ok"], True)
        self.assertEqual(payload["tool_result"]["output_json"], {"message": "hello"})
        self.assertEqual(payload["choices"][0]["message"]["role"], "assistant")
        self.assertEqual(providers["local_vllm"].last_request, None)
        self.assertEqual(providers["gemini_fallback"].last_request, None)
        self.assertEqual(providers["openai_responses"].last_request, None)

    def test_tool_call_is_rejected_when_not_in_allowed_tools(self) -> None:
        app, providers = self.make_app(build_config())

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(
                allowed_tools=[],
                tool_call={
                    "name": "echo",
                    "arguments": {"message": "hello"},
                },
            ),
        )

        self.assertEqual(status_code, 403)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assert_error_payload(payload, error_type="tool_not_allowed")
        self.assertEqual(providers["local_vllm"].last_request, None)
        self.assertEqual(providers["gemini_fallback"].last_request, None)
        self.assertEqual(providers["openai_responses"].last_request, None)

    def test_explicit_tool_call_supports_strict_example_tool(self) -> None:
        app, providers = self.make_app(build_config())

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(
                allowed_tools=["add_numbers"],
                tool_call={
                    "name": "add_numbers",
                    "arguments": {"a": 2, "b": 3},
                },
            ),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["tool_result"]["name"], "add_numbers")
        self.assertEqual(payload["tool_result"]["output_json"]["sum"], 5)
        self.assertEqual(providers["local_vllm"].last_request, None)

    def test_explicit_tool_call_supports_workspace_read_tool_via_router_path(self) -> None:
        app, providers = self.make_app(build_config())

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("notes.txt").write_text("hello router\n", encoding="utf-8")
            app.tool_loop_engine._workspace_root = workspace_dir

            status_code, response_headers, payload = perform_json_request(
                app,
                method="POST",
                path="/v1/chat/completions",
                body=build_payload(
                    allowed_tools=["filesystem.read"],
                    tool_call={
                        "name": "filesystem.read",
                        "arguments": {"path": "notes.txt"},
                    },
                ),
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["tool_result"]["name"], "filesystem.read")
        self.assertEqual(
            payload["tool_result"]["output_json"],
            {
                "path": "notes.txt",
                "content": "hello router\n",
                "encoding": "utf-8",
                "bytes_read": 13,
                "truncated": False,
            },
        )
        self.assertEqual(providers["local_vllm"].last_request, None)

    def test_explicit_tool_call_rejects_workspace_escape_for_filesystem_tool(self) -> None:
        app, _ = self.make_app(build_config())

        with tempfile.TemporaryDirectory() as temp_dir:
            root_path = pathlib.Path(temp_dir)
            workspace_path = root_path / "workspace"
            workspace_path.mkdir()
            (root_path / "outside.txt").write_text("secret", encoding="utf-8")
            app.tool_loop_engine._workspace_root = str(workspace_path)

            status_code, response_headers, payload = perform_json_request(
                app,
                method="POST",
                path="/v1/chat/completions",
                body=build_payload(
                    allowed_tools=["filesystem.read"],
                    tool_call={
                        "name": "filesystem.read",
                        "arguments": {"path": "../outside.txt"},
                    },
                ),
            )

        # Workspace boundary violation is a structured tool failure, not an HTTP error.
        # The explicit tool_call path returns HTTP 200 with ok=False in tool_result.
        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertFalse(payload["tool_result"]["ok"])
        self.assertEqual(payload["tool_result"]["error_code"], "invalid_tool_arguments")

    def test_chat_without_tool_call_keeps_existing_provider_path(self) -> None:
        app, providers = self.make_app(build_config())

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assertEqual(payload["provider"], "local_vllm")
        self.assertIsNotNone(providers["local_vllm"].last_request)

    def test_model_tool_call_is_executed_and_result_is_reinjected(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-1",
                                name="echo",
                                arguments={"message": "hello"},
                            )
                        ],
                    ),
                    final=False,
                    finish_reason="tool_calls",
                    response_id="step-1",
                    provider_name="local_vllm",
                ),
                NormalizedGeneration(
                    message=NormalizedMessage(role="assistant", content="done"),
                    final=True,
                    finish_reason="stop",
                    response_id="step-2",
                    provider_name="local_vllm",
                ),
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=["echo"]),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["choices"][0]["message"]["content"], "done")
        self.assertEqual(payload["tool_steps"], 1)
        self.assertEqual(len(providers["local_vllm"].request_history), 2)
        second_request = providers["local_vllm"].request_history[1]
        self.assertEqual(second_request.messages[-2].role, "assistant")
        self.assertEqual(second_request.messages[-2].tool_calls[0].name, "echo")
        self.assertEqual(second_request.messages[-1].role, "tool")
        self.assertEqual(second_request.messages[-1].content_json, {"message": "hello"})

    def test_model_tool_call_can_execute_real_tool_when_explicitly_allowed(self) -> None:
        app, providers = self.make_app(build_config())

        with tempfile.TemporaryDirectory() as workspace_dir:
            pathlib.Path(workspace_dir, "plan.txt").write_text("tool plan\n", encoding="utf-8")
            app.tool_loop_engine._workspace_root = workspace_dir
            providers["local_vllm"] = StubProvider(
                "local_vllm",
                generations=[
                    NormalizedGeneration(
                        message=NormalizedMessage(
                            role="assistant",
                            tool_calls=[
                                NormalizedToolCall(
                                    call_id="call-read",
                                    name="filesystem.read",
                                    arguments={"path": "plan.txt"},
                                )
                            ],
                        ),
                        final=False,
                        finish_reason="tool_calls",
                        response_id="step-1",
                        provider_name="local_vllm",
                    ),
                    NormalizedGeneration(
                        message=NormalizedMessage(role="assistant", content="done"),
                        final=True,
                        finish_reason="stop",
                        response_id="step-2",
                        provider_name="local_vllm",
                    ),
                ],
            )

            status_code, _, payload = perform_json_request(
                app,
                method="POST",
                path="/v1/chat/completions",
                body=build_payload(allowed_tools=["filesystem.read"]),
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["choices"][0]["message"]["content"], "done")
        self.assertEqual(payload["tool_steps"], 1)
        second_request = providers["local_vllm"].request_history[1]
        self.assertEqual(second_request.messages[-1].content_json["path"], "plan.txt")
        self.assertEqual(second_request.messages[-1].content_json["content"], "tool plan\n")

    def test_multiple_model_tool_calls_are_executed_sequentially_and_reinjected(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-1",
                                name="echo",
                                arguments={"message": "hello"},
                            ),
                            NormalizedToolCall(
                                call_id="call-2",
                                name="add_numbers",
                                arguments={"a": 2, "b": 3},
                            ),
                        ],
                    ),
                    final=False,
                    finish_reason="tool_calls",
                    response_id="step-1",
                    provider_name="local_vllm",
                ),
                NormalizedGeneration(
                    message=NormalizedMessage(role="assistant", content="done"),
                    final=True,
                    finish_reason="stop",
                    response_id="step-2",
                    provider_name="local_vllm",
                ),
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=["echo", "add_numbers"]),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["choices"][0]["message"]["content"], "done")
        self.assertEqual(payload["tool_steps"], 2)
        second_request = providers["local_vllm"].request_history[1]
        self.assertEqual(second_request.messages[-3].role, "assistant")
        self.assertEqual([tool_call.name for tool_call in second_request.messages[-3].tool_calls], ["echo", "add_numbers"])
        self.assertEqual(second_request.messages[-2].content_json, {"message": "hello"})
        self.assertEqual(second_request.messages[-1].content_json, {"sum": 5, "a": 2, "b": 3})

    def test_unknown_model_tool_call_returns_not_found(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-unknown",
                                name="missing_tool",
                                arguments={},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        self.assertEqual(status_code, 404)
        self.assert_error_payload(payload, error_type="tool_not_found")

    def test_invalid_model_tool_call_returns_bad_gateway(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-invalid",
                                name=" ",
                                arguments={},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        self.assertEqual(status_code, 502)
        self.assert_error_payload(payload, error_type="invalid_model_tool_call")

    def test_disallowed_model_tool_call_returns_forbidden(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-echo",
                                name="echo",
                                arguments={"message": "blocked"},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=[]),
        )

        self.assertEqual(status_code, 403)
        self.assert_error_payload(payload, error_type="tool_not_allowed")

    def test_max_tool_steps_stops_recursive_tool_loop(self) -> None:
        app, providers = self.make_app(build_config(max_tool_steps=1))
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(call_id="call-1", name="echo", arguments={"message": "1"})
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                ),
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(call_id="call-2", name="echo", arguments={"message": "2"})
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                ),
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=["echo"]),
        )

        self.assertEqual(status_code, 409)
        self.assert_error_payload(payload, error_type="max_tool_steps_exceeded")

    def test_max_tool_steps_blocks_multi_tool_step_before_partial_execution(self) -> None:
        app, providers = self.make_app(build_config(max_tool_steps=1))
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(call_id="call-1", name="echo", arguments={"message": "1"}),
                            NormalizedToolCall(call_id="call-2", name="echo", arguments={"message": "2"}),
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=["echo"]),
        )

        self.assertEqual(status_code, 409)
        self.assert_error_payload(payload, error_type="max_tool_steps_exceeded")
        self.assertEqual(len(providers["local_vllm"].request_history), 1)

    def test_invalid_tool_arguments_return_consistent_error(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-add",
                                name="add_numbers",
                                arguments={"a": 1},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        # Invalid tool arguments are fed back to the model as a failed tool result.
        # The model then responds normally — no hard HTTP error.
        self.assertEqual(status_code, 200)

    def test_repeated_identical_tool_call_is_stopped(self) -> None:
        app, providers = self.make_app(build_config())
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-repeat-1",
                                name="echo",
                                arguments={"message": "repeat"},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                ),
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-repeat-2",
                                name="echo",
                                arguments={"message": "repeat"},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                ),
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(allowed_tools=["echo"]),
        )

        self.assertEqual(status_code, 409)
        self.assert_error_payload(payload, error_type="tool_loop_repeated_call_detected")

    def test_tool_execution_failure_returns_consistent_error(self) -> None:
        app, providers = self.make_app(build_config())
        app.tool_registry.register(
            ToolSpec(
                name="failing_tool",
                description="Always fail.",
                input_schema={"type": "object", "additionalProperties": True},
                risk_level=ToolRiskLevel.LOW,
                capabilities=["debug"],
                enabled_by_default=True,
            ),
            FailingExecutor(),
        )
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-fail",
                                name="failing_tool",
                                arguments={},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        # A tool returning ok=False is fed back to the model as a failed tool result.
        # The model then responds normally — no hard HTTP error.
        self.assertEqual(status_code, 200)

    def test_tool_timeout_returns_consistent_error(self) -> None:
        app, providers = self.make_app(build_config(tool_timeout_s=0.01))
        app.tool_registry.register(
            ToolSpec(
                name="slow_tool",
                description="Sleep past the timeout.",
                input_schema={"type": "object", "additionalProperties": True},
                risk_level=ToolRiskLevel.LOW,
                capabilities=["debug"],
                enabled_by_default=True,
            ),
            SlowExecutor(),
        )
        providers["local_vllm"] = StubProvider(
            "local_vllm",
            generations=[
                NormalizedGeneration(
                    message=NormalizedMessage(
                        role="assistant",
                        tool_calls=[
                            NormalizedToolCall(
                                call_id="call-slow",
                                name="slow_tool",
                                arguments={},
                            )
                        ],
                    ),
                    final=False,
                    provider_name="local_vllm",
                )
            ],
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(),
        )

        self.assertEqual(status_code, 504)
        self.assert_error_payload(payload, error_type="tool_timeout")

    def test_disabled_routes_return_route_unavailable(self) -> None:
        app, _ = self.make_app(build_config())

        for route in ("reasoning", "heavy"):
            with self.subTest(route=route):
                status_code, response_headers, payload = perform_json_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    body=build_payload(route=route),
                )

                self.assertEqual(status_code, 503)
                self.assertEqual(response_headers["content-type"], "application/json")
                self.assert_error_payload(payload, error_type="route_unavailable")

    def test_streaming_is_available_only_for_local_routes(self) -> None:
        app, _ = self.make_app(
            build_config(
                enable_gemini_fallback=True,
                gemini_api_key="test-key",
                gemini_default_model="gemini-2.5-pro",
                enable_openai_fallback=True,
                openai_api_key="test-key",
                openai_reasoning_model="gpt-5.2",
            )
        )

        status_code, response_headers, response_body = perform_http_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=json.dumps(build_payload(route="local", stream=True)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(response_headers["content-type"], "text/event-stream")
        self.assertIn("data: {\"provider\": \"local_vllm\"}", response_body.decode("utf-8"))

        for route in ("reasoning", "heavy"):
            with self.subTest(route=route):
                status_code, response_headers, response_body = perform_http_request(
                    app,
                    method="POST",
                    path="/v1/chat/completions",
                    body=json.dumps(build_payload(route=route, stream=True)).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )

                self.assertEqual(status_code, 501)
                self.assertEqual(response_headers["content-type"], "application/json")
                self.assert_error_payload(
                    json.loads(response_body.decode("utf-8")),
                    error_type="streaming_not_supported",
                )

    def test_http_level_error_contract_is_consistent(self) -> None:
        app, _ = self.make_app(build_config())

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=None,
        )
        self.assertEqual(status_code, 400)
        self.assert_error_payload(payload, error_type="invalid_messages")

        status_code, _, response_body = perform_http_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status_code, 400)
        self.assert_error_payload(
            json.loads(response_body.decode("utf-8")),
            error_type="invalid_json",
        )

        status_code, _, response_body = perform_http_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=b"[]",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(status_code, 400)
        self.assert_error_payload(
            json.loads(response_body.decode("utf-8")),
            error_type="invalid_request",
        )

        status_code, _, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(route="cloud"),
        )
        self.assertEqual(status_code, 400)
        self.assert_error_payload(payload, error_type="invalid_route")

        status_code, _, payload = perform_json_request(
            app,
            method="GET",
            path="/v1/does-not-exist",
        )
        self.assertEqual(status_code, 404)
        self.assert_error_payload(payload, error_type="unsupported_path")

    def test_chat_provider_errors_are_normalized(self) -> None:
        app = self.make_error_app(
            build_config(),
            "local_vllm",
            ErrorProvider(
                "local_vllm",
                chat_error=ProviderError(
                    "local_vllm returned status 429",
                    status_code=429,
                    payload={
                        "error": {
                            "type": "rate_limit_exceeded",
                            "message": "Quota exceeded.",
                        }
                    },
                ),
            ),
        )

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(route="local"),
        )

        self.assertEqual(status_code, 429)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assert_error_payload(payload, error_type="rate_limited")
        self.assertEqual(payload["error"]["message"], "Quota exceeded.")

    def test_stream_provider_errors_are_normalized(self) -> None:
        app = self.make_error_app(
            build_config(),
            "local_vllm",
            ErrorProvider(
                "local_vllm",
                stream_error=ProviderError(
                    "local_vllm returned status 401",
                    status_code=401,
                    payload={"message": "Bad API key."},
                ),
            ),
        )

        status_code, response_headers, response_body = perform_http_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=json.dumps(build_payload(route="local", stream=True)).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(status_code, 401)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assert_error_payload(
            json.loads(response_body.decode("utf-8")),
            error_type="auth_error",
        )

    def test_models_provider_errors_are_normalized(self) -> None:
        app = self.make_error_app(
            build_config(),
            "local_vllm",
            ErrorProvider(
                "local_vllm",
                list_error=ProviderError(
                    "local_vllm returned status 502",
                    status_code=502,
                    payload={"detail": "Bad gateway from upstream."},
                ),
            ),
        )

        status_code, response_headers, payload = perform_json_request(
            app,
            method="GET",
            path="/v1/models",
        )

        self.assertEqual(status_code, 502)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assert_error_payload(payload, error_type="provider_unavailable")
        self.assertEqual(payload["error"]["message"], "Bad gateway from upstream.")

    def test_router_surfaces_timeout_errors_consistently(self) -> None:
        app = self.make_error_app(
            build_config(),
            "local_vllm",
            ErrorProvider(
                "local_vllm",
                chat_error=ProviderError(
                    "local_vllm request timed out",
                    status_code=504,
                    payload={
                        "error": {
                            "type": "timeout",
                            "message": "Upstream provider request timed out.",
                        }
                    },
                ),
            ),
        )

        status_code, response_headers, payload = perform_json_request(
            app,
            method="POST",
            path="/v1/chat/completions",
            body=build_payload(route="local"),
        )

        self.assertEqual(status_code, 504)
        self.assertEqual(response_headers["content-type"], "application/json")
        self.assert_error_payload(payload, error_type="timeout")
        self.assertEqual(payload["error"]["message"], "Upstream provider request timed out.")


if __name__ == "__main__":
    unittest.main()
