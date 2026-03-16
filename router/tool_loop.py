from __future__ import annotations
import os
from dataclasses import dataclass, replace
from http import HTTPStatus

from router.normalization import GenerationRequest, NormalizedGeneration, tool_result_to_message
from router.providers.base import Provider
from router.schemas import JSONValue
from router.tools.orchestrator import ToolExecutionTimeoutError, ToolOrchestrator
from router.tools.policy import ToolExecutionDeniedError
from router.tools.registry import ToolNotFoundError
from router.tools.types import ToolCall, ToolContext, ToolResult
from router.tools.validation import ToolArgumentsValidationError


class ToolLoopError(RuntimeError):
    def __init__(self, status_code: int, error_type: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload: JSONValue = {
            "error": {
                "type": error_type,
                "message": message,
            }
        }


@dataclass(frozen=True)
class ToolLoopResult:
    generation: NormalizedGeneration
    tool_steps: int


class ToolLoopEngine:
    def __init__(
        self,
        *,
        tool_orchestrator: ToolOrchestrator,
        max_tool_steps: int,
        tool_timeout_s: float,
        workspace_root: str | None = None,
    ) -> None:
        self._tool_orchestrator = tool_orchestrator
        self._max_tool_steps = max_tool_steps
        self._tool_timeout_s = tool_timeout_s
        self._workspace_root = workspace_root or os.getcwd()

    async def run(
        self,
        *,
        provider: Provider,
        request: GenerationRequest,
        request_id: str,
        allowed_tools: set[str] | None,
    ) -> ToolLoopResult:
        current_request = request
        tool_steps = 0

        while True:
            generation = provider.generate(current_request)
            tool_calls = generation.message.tool_calls
            if not tool_calls:
                return ToolLoopResult(generation=generation, tool_steps=tool_steps)

            if len(tool_calls) != 1:
                raise ToolLoopError(
                    HTTPStatus.BAD_GATEWAY,
                    "invalid_model_tool_call",
                    "Model returned more than one tool call in a single step.",
                )

            if tool_steps >= self._max_tool_steps:
                raise ToolLoopError(
                    HTTPStatus.CONFLICT,
                    "max_tool_steps_exceeded",
                    f"Model requested more than {self._max_tool_steps} tool steps.",
                )

            tool_call = tool_calls[0]
            result = await self._run_tool_call(
                tool_call=ToolCall(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    arguments=tool_call.arguments,
                ),
                request_id=request_id,
                current_tool_step=tool_steps,
                allowed_tools=allowed_tools,
            )
            tool_steps += 1
            current_request = replace(
                current_request,
                messages=[
                    *current_request.messages,
                    generation.message,
                    tool_result_to_message(result),
                ],
            )

    async def run_tool_call(
        self,
        *,
        tool_call: ToolCall,
        request_id: str,
        current_tool_step: int,
        allowed_tools: set[str] | None,
    ) -> ToolResult:
        return await self._run_tool_call(
            tool_call=tool_call,
            request_id=request_id,
            current_tool_step=current_tool_step,
            allowed_tools=allowed_tools,
        )

    async def _run_tool_call(
        self,
        *,
        tool_call: ToolCall,
        request_id: str,
        current_tool_step: int,
        allowed_tools: set[str] | None,
    ) -> ToolResult:
        if allowed_tools is not None and tool_call.name not in allowed_tools:
            raise ToolLoopError(
                HTTPStatus.FORBIDDEN,
                "tool_not_allowed",
                f"tool={tool_call.name} is not permitted for this request.",
            )

        try:
            result = await self._tool_orchestrator.run(
                tool_call,
                ToolContext(
                    request_id=request_id,
                    workspace_root=self._workspace_root,
                    max_tool_steps=self._max_tool_steps,
                    current_tool_step=current_tool_step,
                    tool_timeout_s=self._tool_timeout_s,
                ),
            )
        except ToolNotFoundError as exc:
            raise ToolLoopError(HTTPStatus.NOT_FOUND, "tool_not_found", str(exc)) from exc
        except ToolExecutionDeniedError as exc:
            raise ToolLoopError(
                HTTPStatus.FORBIDDEN,
                "tool_not_allowed",
                str(exc),
            ) from exc
        except ToolArgumentsValidationError as exc:
            raise ToolLoopError(
                HTTPStatus.BAD_REQUEST,
                "invalid_tool_arguments",
                str(exc),
            ) from exc
        except ToolExecutionTimeoutError as exc:
            raise ToolLoopError(
                HTTPStatus.GATEWAY_TIMEOUT,
                "tool_timeout",
                str(exc),
            ) from exc
        except Exception as exc:
            raise ToolLoopError(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "tool_execution_failed",
                str(exc),
            ) from exc

        if not result.ok:
            error_type = "tool_timeout" if result.error_code == "tool_timeout" else "tool_execution_failed"
            status_code = (
                HTTPStatus.GATEWAY_TIMEOUT
                if error_type == "tool_timeout"
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            raise ToolLoopError(
                status_code,
                error_type,
                result.error_message or f"tool execution failed: {result.name}",
            )

        return result
