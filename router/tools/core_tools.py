from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any

from router.tools.registry import ToolRegistry
from router.tools.types import (
    ToolCall,
    ToolContext,
    ToolResult,
    ToolRiskLevel,
    ToolSpec,
)
from router.tools.validation import ToolArgumentsValidationError

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
        workspace_root = _require_workspace_root(ctx, tool_name=call.name)
        max_bytes = _read_positive_int(
            call.arguments,
            key="max_bytes",
            default=_DEFAULT_READ_MAX_BYTES,
            maximum=_MAX_READ_MAX_BYTES,
            tool_name=call.name,
        )
        resolved = _resolve_workspace_path(workspace_root, call.arguments.get("path"))
        if not resolved.is_file():
            raise ToolArgumentsValidationError(
                f"{call.name} path is not a readable file: {call.arguments['path']}"
            )

        with open(resolved, "rb") as fh:
            probe = fh.read(max_bytes + 1)
        truncated = len(probe) > max_bytes
        raw_bytes = probe[:max_bytes]
        try:
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolArgumentsValidationError(
                f"{call.name} only supports UTF-8 text files: {call.arguments['path']}"
            ) from exc

        relative_path = _relative_workspace_path(workspace_root, resolved)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=content,
            output_json={
                "path": relative_path,
                "content": content,
                "encoding": "utf-8",
                "bytes_read": len(raw_bytes),
                "truncated": truncated,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class FilesystemListExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _require_workspace_root(ctx, tool_name=call.name)
        max_entries = _read_positive_int(
            call.arguments,
            key="max_entries",
            default=_DEFAULT_LIST_MAX_ENTRIES,
            maximum=_MAX_LIST_MAX_ENTRIES,
            tool_name=call.name,
        )
        include_hidden = _read_bool(
            call.arguments,
            key="include_hidden",
            default=False,
            tool_name=call.name,
        )
        resolved = _resolve_workspace_path(workspace_root, call.arguments.get("path"))
        if not resolved.is_dir():
            raise ToolArgumentsValidationError(
                f"{call.name} path is not a directory: {call.arguments['path']}"
            )

        entries = _list_directory_entries(resolved, include_hidden)
        returned_entries = entries[:max_entries]
        payload_entries = [
            _filesystem_entry_payload(workspace_root, entry)
            for entry in returned_entries
        ]
        relative_path = _relative_workspace_path(workspace_root, resolved)
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text="\n".join(entry["path"] for entry in payload_entries),
            output_json={
                "path": relative_path,
                "entries": payload_entries,
                "entry_count": len(entries),
                "returned_entry_count": len(payload_entries),
                "truncated": len(entries) > max_entries,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class GitStatusExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _require_workspace_root(ctx, tool_name=call.name)
        max_entries = _read_positive_int(
            call.arguments,
            key="max_entries",
            default=_DEFAULT_GIT_STATUS_MAX_ENTRIES,
            maximum=_MAX_GIT_STATUS_MAX_ENTRIES,
            tool_name=call.name,
        )

        try:
            completed = _run_git(
                workspace_root,
                ["status", "--porcelain=v1", "--branch", "--untracked-files=normal"],
                timeout_s=ctx.tool_timeout_s,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                call,
                error_code="tool_timeout",
                error_message=f"{call.name} timed out after {ctx.tool_timeout_s} seconds.",
            )
        if completed.returncode != 0:
            return _failure(
                call,
                error_code="git_status_failed",
                error_message=_git_error_message(completed, "git.status failed."),
            )

        status_text = completed.stdout
        lines = status_text.splitlines()
        branch_line = lines[0] if lines and lines[0].startswith("## ") else ""
        entry_lines = lines[1:] if branch_line else lines
        entries = [_parse_git_status_line(line) for line in entry_lines if line.strip()]
        returned_entries = entries[:max_entries]

        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=_git_status_output_text(branch_line, returned_entries),
            output_json={
                "branch": _parse_git_branch_line(branch_line),
                "entries": returned_entries,
                "entry_count": len(entries),
                "returned_entry_count": len(returned_entries),
                "truncated": len(entries) > max_entries,
                "is_clean": len(entries) == 0,
                "counts": _git_status_counts(entries),
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


class GitDiffExecutor:
    async def execute(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        workspace_root = _require_workspace_root(ctx, tool_name=call.name)
        context_lines = _read_non_negative_int(
            call.arguments,
            key="context_lines",
            default=_DEFAULT_GIT_DIFF_CONTEXT_LINES,
            maximum=_MAX_GIT_DIFF_CONTEXT_LINES,
            tool_name=call.name,
        )
        max_bytes = _read_positive_int(
            call.arguments,
            key="max_bytes",
            default=_DEFAULT_GIT_DIFF_MAX_BYTES,
            maximum=_MAX_GIT_DIFF_MAX_BYTES,
            tool_name=call.name,
        )
        cached = _read_bool(
            call.arguments,
            key="cached",
            default=False,
            tool_name=call.name,
        )

        command = [
            "diff",
            "--no-ext-diff",
            f"--unified={context_lines}",
        ]
        if cached:
            command.append("--cached")

        relative_path: str | None = None
        if "path" in call.arguments:
            resolved = _resolve_workspace_path(workspace_root, call.arguments.get("path"))
            relative_path = _relative_workspace_path(workspace_root, resolved)
            command.extend(["--", relative_path])

        try:
            completed = _run_git(
                workspace_root,
                command,
                timeout_s=ctx.tool_timeout_s,
            )
        except subprocess.TimeoutExpired:
            return _failure(
                call,
                error_code="tool_timeout",
                error_message=f"{call.name} timed out after {ctx.tool_timeout_s} seconds.",
            )
        if completed.returncode != 0:
            return _failure(
                call,
                error_code="git_diff_failed",
                error_message=_git_error_message(completed, "git.diff failed."),
            )

        diff_text = completed.stdout[:max_bytes]
        return ToolResult(
            call_id=call.call_id,
            name=call.name,
            ok=True,
            output_text=diff_text,
            output_json={
                "path": relative_path or ".",
                "cached": cached,
                "context_lines": context_lines,
                "diff": diff_text,
                "bytes_read": len(diff_text.encode("utf-8")),
                "truncated": len(completed.stdout.encode("utf-8")) > max_bytes,
            },
            metadata={"tool_step": ctx.current_tool_step},
        )


def register_core_tools(registry: ToolRegistry) -> None:
    registry.register(
        ToolSpec(
            name="filesystem.list",
            description="List direct workspace entries for a directory path.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_entries": {"type": "integer"},
                    "include_hidden": {"type": "boolean"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["filesystem", "list", "workspace"],
            enabled_by_default=False,
        ),
        FilesystemListExecutor(),
    )
    registry.register(
        ToolSpec(
            name="filesystem.read",
            description="Read a UTF-8 text file inside the workspace root.",
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
            capabilities=["filesystem", "read", "workspace"],
            enabled_by_default=False,
        ),
        FilesystemReadExecutor(),
    )
    registry.register(
        ToolSpec(
            name="git.diff",
            description="Return a bounded read-only git diff for the workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "cached": {"type": "boolean"},
                    "context_lines": {"type": "integer"},
                    "max_bytes": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["git", "diff", "workspace"],
            enabled_by_default=False,
        ),
        GitDiffExecutor(),
    )
    registry.register(
        ToolSpec(
            name="git.status",
            description="Return structured read-only git status for the workspace repository.",
            input_schema={
                "type": "object",
                "properties": {
                    "max_entries": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            risk_level=ToolRiskLevel.MEDIUM,
            capabilities=["git", "status", "workspace"],
            enabled_by_default=False,
        ),
        GitStatusExecutor(),
    )


def _list_directory_entries(directory: Path, include_hidden: bool) -> list[Path]:
    entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
    if include_hidden:
        return entries
    return [entry for entry in entries if not entry.name.startswith(".")]


def _filesystem_entry_payload(workspace_root: Path, entry: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": entry.name,
        "path": _relative_workspace_path(workspace_root, entry),
        "type": _entry_type(entry),
    }
    if entry.is_file():
        payload["size_bytes"] = entry.stat().st_size
    return payload


def _entry_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "other"


def _require_workspace_root(ctx: ToolContext, *, tool_name: str) -> Path:
    if ctx.workspace_root is None or not str(ctx.workspace_root).strip():
        raise RuntimeError(f"{tool_name} requires a configured workspace root.")
    return Path(ctx.workspace_root).resolve()


def _resolve_workspace_path(workspace_root: Path, requested_path: object) -> Path:
    if not isinstance(requested_path, str) or not requested_path.strip():
        raise ToolArgumentsValidationError("Path argument must be a non-blank string.")
    candidate = Path(requested_path)
    if not candidate.is_absolute():
        candidate = workspace_root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ToolArgumentsValidationError(
            f"Path escapes the configured workspace root: {requested_path}"
        ) from exc
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
    tool_name: str,
) -> int:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > maximum:
        raise ToolArgumentsValidationError(
            f"{tool_name} {key} must be between 1 and {maximum}."
        )
    return value


def _read_non_negative_int(
    arguments: dict[str, object],
    *,
    key: str,
    default: int,
    maximum: int,
    tool_name: str,
) -> int:
    value = arguments.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > maximum:
        raise ToolArgumentsValidationError(
            f"{tool_name} {key} must be between 0 and {maximum}."
        )
    return value


def _read_bool(
    arguments: dict[str, object],
    *,
    key: str,
    default: bool,
    tool_name: str,
) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ToolArgumentsValidationError(
            f"{tool_name} {key} must be a boolean."
        )
    return value


def _run_git(
    workspace_root: Path,
    arguments: list[str],
    *,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=workspace_root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **os.environ,
            "GIT_PAGER": "cat",
            "LC_ALL": "C",
            "LANG": "C",
            "GIT_CEILING_DIRECTORIES": str(workspace_root.parent),
        },
        timeout=timeout_s,
    )


def _git_error_message(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    return stderr or stdout or fallback


def _parse_git_status_line(line: str) -> dict[str, Any]:
    index_status = line[0]
    worktree_status = line[1]
    path_text = line[3:]
    previous_path: str | None = None
    if " -> " in path_text:
        previous_path, path_text = path_text.split(" -> ", 1)

    entry: dict[str, Any] = {
        "path": path_text,
        "index_status": index_status,
        "worktree_status": worktree_status,
        "status": line[:2],
        "staged": index_status not in {" ", "?"},
        "unstaged": worktree_status not in {" ", "?"},
        "untracked": line[:2] == "??",
        "raw": line,
    }
    if previous_path is not None:
        entry["previous_path"] = previous_path
    return entry


def _parse_git_branch_line(line: str) -> dict[str, Any]:
    if not line:
        return {"raw": ""}

    content = line[3:]
    head = content
    upstream: str | None = None
    ahead = 0
    behind = 0

    if "..." in content:
        head, remainder = content.split("...", 1)
        upstream = remainder.split(" ", 1)[0]
    if "[ahead " in content:
        ahead = int(content.split("[ahead ", 1)[1].split("]", 1)[0].split(",", 1)[0])
    if "behind " in content:
        behind_text = content.split("behind ", 1)[1].split("]", 1)[0].split(",", 1)[0]
        behind = int(behind_text)

    return {
        "raw": line,
        "head": head,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
    }


def _git_status_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "staged": sum(1 for entry in entries if entry["staged"]),
        "unstaged": sum(1 for entry in entries if entry["unstaged"]),
        "untracked": sum(1 for entry in entries if entry["untracked"]),
    }


def _git_status_output_text(branch_line: str, entries: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if branch_line:
        parts.append(branch_line)
    parts.extend(e["raw"] for e in entries)
    return "\n".join(parts)


def _failure(call: ToolCall, *, error_code: str, error_message: str) -> ToolResult:
    return ToolResult(
        call_id=call.call_id,
        name=call.name,
        ok=False,
        error_code=error_code,
        error_message=error_message,
    )
