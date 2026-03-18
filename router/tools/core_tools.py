from __future__ import annotations

import os
from pathlib import Path
import subprocess

from router.tools.registry import ToolRegistry
from router.tools.types import (
    ToolCall,
    ToolContext,
    ToolResult,
    ToolRiskLevel,
    ToolSpec,
)

_DEFAULT_READ_MAX_BYTES = 16_384
_MAX_READ_MAX_BYTES = 65_536
_DEFAULT_LIST_MAX_ENTRIES = 100
_MAX_LIST_MAX_ENTRIES = 500
_DEFAULT_GIT_STATUS_MAX_ENTRIES = 200
_MAX_GIT_STATUS_MAX_ENTRIES = 500
_DEFAULT_GIT_DIFF_CONTEXT_LINES = 3
_MAX_GIT_DIFF_CONTEXT_LINES = 20
_DEFAULT_GIT_DIFF_MAX_BYTES = 32_768
_MAX_GIT_DIFF_MAX_BYTES = 131_072


class FilesystemReadExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _workspace_root_path(ctx)
        if workspace_root is None:
            return _failure(
                call,
                error_code="workspace_root_missing",
                error_message="filesystem.read requires a configured workspace root.",
            )

        max_bytes = _read_positive_int(
            call.arguments,
            key="max_bytes",
            default=_DEFAULT_READ_MAX_BYTES,
            maximum=_MAX_READ_MAX_BYTES,
        )
        if max_bytes is None:
            return _failure(
                call,
                error_code="invalid_max_bytes",
                error_message=f"filesystem.read max_bytes must be between 1 and {_MAX_READ_MAX_BYTES}.",
            )

        resolved = _resolve_workspace_path(workspace_root, call.arguments["path"])
        if resolved is None:
            return _failure(
                call,
                error_code="workspace_boundary_violation",
                error_message="filesystem.read path must stay inside the configured workspace.",
            )

        if not resolved.is_file():
            return _failure(
                call,
                error_code="not_a_file",
                error_message=f"filesystem.read path is not a readable file: {call.arguments['path']}",
            )

        file_bytes = resolved.read_bytes()
        returned_bytes = file_bytes[:max_bytes]
        try:
            content = returned_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return _failure(
                call,
                error_code="invalid_encoding",
                error_message=f"filesystem.read only supports UTF-8 text files: {call.arguments['path']}",
            )

        resolved_path = _relative_workspace_path(workspace_root, resolved)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=content,
            output_json={
                "path": call.arguments["path"],
                "resolved_path": resolved_path,
                "content": content,
                "encoding": "utf-8",
                "size_bytes": len(file_bytes),
                "bytes_returned": len(returned_bytes),
                "truncated": len(file_bytes) > max_bytes,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class FilesystemListExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _workspace_root_path(ctx)
        if workspace_root is None:
            return _failure(
                call,
                error_code="workspace_root_missing",
                error_message="filesystem.list requires a configured workspace root.",
            )

        max_entries = _read_positive_int(
            call.arguments,
            key="max_entries",
            default=_DEFAULT_LIST_MAX_ENTRIES,
            maximum=_MAX_LIST_MAX_ENTRIES,
        )
        if max_entries is None:
            return _failure(
                call,
                error_code="invalid_max_entries",
                error_message=f"filesystem.list max_entries must be between 1 and {_MAX_LIST_MAX_ENTRIES}.",
            )

        resolved = _resolve_workspace_path(workspace_root, call.arguments["path"])
        if resolved is None:
            return _failure(
                call,
                error_code="workspace_boundary_violation",
                error_message="filesystem.list path must stay inside the configured workspace.",
            )

        if not resolved.is_dir():
            return _failure(
                call,
                error_code="not_a_directory",
                error_message=f"filesystem.list path is not a directory: {call.arguments['path']}",
            )

        all_entries = sorted(resolved.iterdir(), key=lambda entry: entry.name)
        returned_entries = all_entries[:max_entries]
        payload_entries: list[dict[str, object]] = []
        for entry in returned_entries:
            entry_payload: dict[str, object] = {
                "name": entry.name,
                "path": _relative_workspace_path(workspace_root, entry),
                "kind": _entry_kind(entry),
            }
            if entry.is_file():
                entry_payload["size_bytes"] = entry.stat().st_size
            payload_entries.append(entry_payload)

        resolved_path = _relative_workspace_path(workspace_root, resolved)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text="\n".join(entry["path"] for entry in payload_entries),
            output_json={
                "path": call.arguments["path"],
                "resolved_path": resolved_path,
                "entries": payload_entries,
                "entry_count": len(all_entries),
                "returned_entry_count": len(payload_entries),
                "truncated": len(all_entries) > max_entries,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class GitStatusExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _workspace_root_path(ctx)
        if workspace_root is None:
            return _failure(
                call,
                error_code="workspace_root_missing",
                error_message="git.status requires a configured workspace root.",
            )

        max_entries = _read_positive_int(
            call.arguments,
            key="max_entries",
            default=_DEFAULT_GIT_STATUS_MAX_ENTRIES,
            maximum=_MAX_GIT_STATUS_MAX_ENTRIES,
        )
        if max_entries is None:
            return _failure(
                call,
                error_code="invalid_max_entries",
                error_message=f"git.status max_entries must be between 1 and {_MAX_GIT_STATUS_MAX_ENTRIES}.",
            )

        completed = _run_git(
            workspace_root,
            [
                "status",
                "--porcelain=v1",
                "--branch",
                "--untracked-files=normal",
            ],
        )
        if completed.returncode != 0:
            return _failure(
                call,
                error_code="git_status_failed",
                error_message=_git_error_message(completed, "git.status failed."),
            )

        status_text = completed.stdout.decode("utf-8", errors="replace")
        lines = status_text.splitlines()
        branch_line = lines[0] if lines and lines[0].startswith("## ") else ""
        entry_lines = lines[1:] if branch_line else lines
        entries = [_parse_git_status_line(line) for line in entry_lines if line.strip()]
        returned_entries = entries[:max_entries]
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=status_text.strip(),
            output_json={
                "repo_root": ".",
                "branch_line": branch_line,
                "entries": returned_entries,
                "entry_count": len(entries),
                "returned_entry_count": len(returned_entries),
                "truncated": len(entries) > max_entries,
                "clean": len(entries) == 0,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class GitDiffExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _workspace_root_path(ctx)
        if workspace_root is None:
            return _failure(
                call,
                error_code="workspace_root_missing",
                error_message="git.diff requires a configured workspace root.",
            )

        context_lines = _read_non_negative_int(
            call.arguments,
            key="context_lines",
            default=_DEFAULT_GIT_DIFF_CONTEXT_LINES,
            maximum=_MAX_GIT_DIFF_CONTEXT_LINES,
        )
        if context_lines is None:
            return _failure(
                call,
                error_code="invalid_context_lines",
                error_message=(
                    f"git.diff context_lines must be between 0 and {_MAX_GIT_DIFF_CONTEXT_LINES}."
                ),
            )

        max_bytes = _read_positive_int(
            call.arguments,
            key="max_bytes",
            default=_DEFAULT_GIT_DIFF_MAX_BYTES,
            maximum=_MAX_GIT_DIFF_MAX_BYTES,
        )
        if max_bytes is None:
            return _failure(
                call,
                error_code="invalid_max_bytes",
                error_message=f"git.diff max_bytes must be between 1 and {_MAX_GIT_DIFF_MAX_BYTES}.",
            )

        completed = _run_git(
            workspace_root,
            [
                "diff",
                "--no-ext-diff",
                "--no-color",
                "--no-renames",
                f"--unified={context_lines}",
            ],
        )
        if completed.returncode != 0:
            return _failure(
                call,
                error_code="git_diff_failed",
                error_message=_git_error_message(completed, "git.diff failed."),
            )

        diff_bytes = completed.stdout
        returned_bytes = diff_bytes[:max_bytes]
        diff_text = returned_bytes.decode("utf-8", errors="replace")
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=diff_text,
            output_json={
                "repo_root": ".",
                "context_lines": context_lines,
                "diff": diff_text,
                "bytes_returned": len(returned_bytes),
                "truncated": len(diff_bytes) > max_bytes,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


def register_core_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="filesystem.list",
            description="List files and directories inside the configured workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_entries": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["filesystem", "list"],
            enabled_by_default=True,
        ),
        FilesystemListExecutor(),
    )
    registry.register(
        ToolSpec(
            name="filesystem.read",
            description="Read a UTF-8 text file inside the configured workspace.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_bytes": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["filesystem", "read"],
            enabled_by_default=True,
        ),
        FilesystemReadExecutor(),
    )
    registry.register(
        ToolSpec(
            name="git.diff",
            description="Return a read-only git diff for the current workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "context_lines": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["git", "diff", "read"],
            enabled_by_default=True,
        ),
        GitDiffExecutor(),
    )
    registry.register(
        ToolSpec(
            name="git.status",
            description="Return a read-only git status for the current workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "max_entries": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["git", "read", "status"],
            enabled_by_default=True,
        ),
        GitStatusExecutor(),
    )


def _entry_kind(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


def _workspace_root_path(ctx: ToolContext) -> Path | None:
    if ctx.workspace_root is None or not str(ctx.workspace_root).strip():
        return None
    return Path(ctx.workspace_root).resolve()


def _resolve_workspace_path(workspace_root: Path, requested_path: object) -> Path | None:
    if not isinstance(requested_path, str) or not requested_path.strip():
        return None
    candidate = Path(requested_path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(workspace_root)
    except ValueError:
        return None
    return resolved


def _relative_workspace_path(workspace_root: Path, path: Path) -> str:
    relative = path.relative_to(workspace_root)
    value = relative.as_posix()
    return value if value else "."


def _read_positive_int(
    arguments: dict[str, object],
    *,
    key: str,
    default: int,
    maximum: int,
) -> int | None:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 1 or value > maximum:
        return None
    return value


def _read_non_negative_int(
    arguments: dict[str, object],
    *,
    key: str,
    default: int,
    maximum: int,
) -> int | None:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 0 or value > maximum:
        return None
    return value


def _run_git(workspace_root: Path, arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *arguments],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        env={
            **os.environ,
            "GIT_PAGER": "cat",
            "LC_ALL": "C",
            "LANG": "C",
        },
    )


def _git_error_message(completed: subprocess.CompletedProcess[bytes], fallback: str) -> str:
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    return stderr or stdout or fallback


def _parse_git_status_line(line: str) -> dict[str, object]:
    status = line[:2]
    path_text = line[3:]
    previous_path: str | None = None
    if " -> " in path_text:
        previous_path, path_text = path_text.split(" -> ", 1)
    entry: dict[str, object] = {
        "status": status,
        "path": path_text,
        "raw": line,
    }
    if previous_path is not None:
        entry["previous_path"] = previous_path
    return entry


def _failure(call: ToolCall, *, error_code: str, error_message: str) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        name=call.name,
        ok=False,
        error_code=error_code,
        error_message=error_message,
    )
