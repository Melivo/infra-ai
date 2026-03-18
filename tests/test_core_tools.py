from __future__ import annotations

import asyncio
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from router.tools.core_tools import (
    FilesystemListExecutor,
    FilesystemReadExecutor,
    GitDiffExecutor,
    GitStatusExecutor,
    register_core_tools,
)
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext
from router.tools.validation import ToolArgumentsValidationError


def _tool_context(workspace_root: str) -> ToolContext:
    return ToolContext(
        request_id="req-test",
        workspace_root=workspace_root,
        current_tool_step=1,
        max_tool_steps=4,
        tool_timeout_s=5.0,
        allowed_tool_names=frozenset(),
    )


def _run_git(repo_dir: pathlib.Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def _create_git_repo() -> tuple[pathlib.Path, tempfile.TemporaryDirectory[str]]:
    temp_dir = tempfile.TemporaryDirectory()
    repo_dir = pathlib.Path(temp_dir.name)
    _run_git(repo_dir, "init")
    _run_git(repo_dir, "config", "user.name", "Infra AI Tests")
    _run_git(repo_dir, "config", "user.email", "infra-ai-tests@example.com")
    return repo_dir, temp_dir


class CoreToolRegistrationTests(unittest.TestCase):
    def test_register_core_tools_exposes_phase_one_tools_with_conservative_defaults(self) -> None:
        registry = ToolRegistry()

        register_core_tools(registry)

        specs = {spec.name: spec for spec in registry.list_specs()}
        self.assertEqual(
            sorted(specs),
            ["filesystem.list", "filesystem.read", "git.diff", "git.status"],
        )
        self.assertFalse(specs["filesystem.read"].enabled_by_default)
        self.assertFalse(specs["filesystem.list"].enabled_by_default)
        self.assertFalse(specs["git.status"].enabled_by_default)
        self.assertFalse(specs["git.diff"].enabled_by_default)


class FilesystemToolTests(unittest.TestCase):
    def test_filesystem_read_returns_structured_result(self) -> None:
        executor = FilesystemReadExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("notes.txt").write_text("hello world", encoding="utf-8")

            result = asyncio.run(
                executor.execute(
                    ToolCall(
                        call_id="call-read",
                        name="filesystem.read",
                        arguments={"path": "notes.txt"},
                    ),
                    _tool_context(workspace_dir),
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.output_text, "hello world")
        self.assertEqual(
            result.output_json,
            {
                "path": "notes.txt",
                "content": "hello world",
                "encoding": "utf-8",
                "bytes_read": 11,
                "truncated": False,
            },
        )

    def test_filesystem_read_rejects_workspace_escape(self) -> None:
        executor = FilesystemReadExecutor()

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = pathlib.Path(temp_dir, "workspace")
            workspace_dir.mkdir()
            pathlib.Path(temp_dir, "outside.txt").write_text("secret", encoding="utf-8")

            with self.assertRaises(ToolArgumentsValidationError):
                asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id="call-read",
                            name="filesystem.read",
                            arguments={"path": "../outside.txt"},
                        ),
                        _tool_context(str(workspace_dir)),
                    )
                )

    def test_filesystem_list_returns_sorted_visible_entries(self) -> None:
        executor = FilesystemListExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("b.txt").write_text("b", encoding="utf-8")
            workspace_path.joinpath("a.txt").write_text("a", encoding="utf-8")
            workspace_path.joinpath(".hidden").write_text("hidden", encoding="utf-8")
            workspace_path.joinpath("subdir").mkdir()

            result = asyncio.run(
                executor.execute(
                    ToolCall(
                        call_id="call-list",
                        name="filesystem.list",
                        arguments={"path": "."},
                    ),
                    _tool_context(workspace_dir),
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(
            [entry["name"] for entry in result.output_json["entries"]],
            ["a.txt", "b.txt", "subdir"],
        )
        self.assertEqual(result.output_json["truncated"], False)
        self.assertEqual(result.output_json["path"], ".")


class GitToolTests(unittest.TestCase):
    def test_git_status_returns_structured_repo_state(self) -> None:
        executor = GitStatusExecutor()
        repo_dir, temp_dir = _create_git_repo()
        self.addCleanup(temp_dir.cleanup)
        repo_dir.joinpath("tracked.txt").write_text("hello\n", encoding="utf-8")
        _run_git(repo_dir, "add", "tracked.txt")
        _run_git(repo_dir, "commit", "-m", "Initial commit")
        repo_dir.joinpath("tracked.txt").write_text("changed\n", encoding="utf-8")
        repo_dir.joinpath("new.txt").write_text("new file\n", encoding="utf-8")

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-status",
                    name="git.status",
                    arguments={},
                ),
                _tool_context(str(repo_dir)),
            )
        )

        entries = {entry["path"]: entry for entry in result.output_json["entries"]}
        self.assertTrue(result.ok)
        self.assertEqual(result.output_json["is_clean"], False)
        self.assertEqual(entries["tracked.txt"]["worktree_status"], "M")
        self.assertEqual(entries["new.txt"]["worktree_status"], "?")
        self.assertEqual(result.output_json["counts"]["unstaged"], 1)
        self.assertEqual(result.output_json["counts"]["untracked"], 1)

    def test_git_diff_returns_structured_result_for_path(self) -> None:
        executor = GitDiffExecutor()
        repo_dir, temp_dir = _create_git_repo()
        self.addCleanup(temp_dir.cleanup)
        repo_dir.joinpath("tracked.txt").write_text("before\n", encoding="utf-8")
        _run_git(repo_dir, "add", "tracked.txt")
        _run_git(repo_dir, "commit", "-m", "Initial commit")
        repo_dir.joinpath("tracked.txt").write_text("after\n", encoding="utf-8")

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-diff",
                    name="git.diff",
                    arguments={"path": "tracked.txt"},
                ),
                _tool_context(str(repo_dir)),
            )
        )

        self.assertTrue(result.ok)
        self.assertEqual(result.output_json["path"], "tracked.txt")
        self.assertEqual(result.output_json["cached"], False)
        self.assertIn("-before", result.output_json["diff"])
        self.assertIn("+after", result.output_json["diff"])

    def test_git_status_uses_read_only_command(self) -> None:
        executor = GitStatusExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch("router.tools.core_tools.subprocess.run") as run_command:
                run_command.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="## main\n",
                    stderr="",
                )

                asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id="call-status",
                            name="git.status",
                            arguments={},
                        ),
                        _tool_context(workspace_dir),
                    )
                )

        self.assertEqual(
            run_command.call_args.args[0],
            ["git", "status", "--porcelain=v1", "--branch", "--untracked-files=normal"],
        )

    def test_git_diff_uses_read_only_command(self) -> None:
        executor = GitDiffExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            with patch("router.tools.core_tools.subprocess.run") as run_command:
                run_command.return_value = subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                )

                asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id="call-diff",
                            name="git.diff",
                            arguments={"path": "tracked.txt"},
                        ),
                        _tool_context(workspace_dir),
                    )
                )

        self.assertEqual(
            run_command.call_args.args[0],
            ["git", "diff", "--no-ext-diff", "--unified=3", "--", "tracked.txt"],
        )


if __name__ == "__main__":
    unittest.main()
