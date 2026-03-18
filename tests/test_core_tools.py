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


class FilesystemReadBoundednessTests(unittest.TestCase):
    def test_filesystem_read_does_not_call_read_bytes_to_truncate(self) -> None:
        """filesystem.read must not load the full file into memory just to truncate it."""
        executor = FilesystemReadExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("large.txt").write_bytes(b"x" * 1000)

            original_read_bytes = pathlib.Path.read_bytes
            read_bytes_called: list[bool] = []

            def spy_read_bytes(self: pathlib.Path) -> bytes:
                read_bytes_called.append(True)
                return original_read_bytes(self)

            with patch.object(pathlib.Path, "read_bytes", spy_read_bytes):
                result = asyncio.run(
                    executor.execute(
                        ToolCall(
                            call_id="call-read",
                            name="filesystem.read",
                            arguments={"path": "large.txt", "max_bytes": 10},
                        ),
                        _tool_context(workspace_dir),
                    )
                )

        self.assertTrue(result.ok)
        self.assertTrue(result.output_json["truncated"])
        self.assertEqual(result.output_json["bytes_read"], 10)
        self.assertFalse(
            read_bytes_called,
            "filesystem.read must not call Path.read_bytes() to truncate large files",
        )

    def test_filesystem_read_truncation_content_is_correct(self) -> None:
        """Truncated content must be exactly the first max_bytes bytes decoded."""
        executor = FilesystemReadExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("data.txt").write_bytes(b"hello world extra")

            result = asyncio.run(
                executor.execute(
                    ToolCall(
                        call_id="call-read",
                        name="filesystem.read",
                        arguments={"path": "data.txt", "max_bytes": 5},
                    ),
                    _tool_context(workspace_dir),
                )
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.output_json["truncated"])
        self.assertEqual(result.output_json["bytes_read"], 5)
        self.assertEqual(result.output_json["content"], "hello")
        self.assertEqual(result.output_text, "hello")

    def test_filesystem_read_no_truncation_flag_when_file_fits_exactly(self) -> None:
        """truncated must be False when the file fits exactly within max_bytes."""
        executor = FilesystemReadExecutor()

        with tempfile.TemporaryDirectory() as workspace_dir:
            workspace_path = pathlib.Path(workspace_dir)
            workspace_path.joinpath("exact.txt").write_bytes(b"abcde")

            result = asyncio.run(
                executor.execute(
                    ToolCall(
                        call_id="call-read",
                        name="filesystem.read",
                        arguments={"path": "exact.txt", "max_bytes": 5},
                    ),
                    _tool_context(workspace_dir),
                )
            )

        self.assertTrue(result.ok)
        self.assertFalse(result.output_json["truncated"])
        self.assertEqual(result.output_json["bytes_read"], 5)


class GitStatusBoundednessTests(unittest.TestCase):
    def test_git_status_output_text_contains_only_returned_entries(self) -> None:
        """output_text must not include entries that were cut by max_entries."""
        executor = GitStatusExecutor()
        repo_dir, temp_dir = _create_git_repo()
        self.addCleanup(temp_dir.cleanup)

        for i in range(5):
            repo_dir.joinpath(f"file_{i}.txt").write_text(f"content {i}\n", encoding="utf-8")

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-status",
                    name="git.status",
                    arguments={"max_entries": 2},
                ),
                _tool_context(str(repo_dir)),
            )
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.output_json["truncated"])
        self.assertEqual(result.output_json["returned_entry_count"], 2)

        returned_paths = {e["path"] for e in result.output_json["entries"]}
        all_paths = {f"file_{i}.txt" for i in range(5)}
        truncated_paths = all_paths - returned_paths
        for path in truncated_paths:
            self.assertNotIn(path, result.output_text or "")


class GitWorkspaceBoundaryTests(unittest.TestCase):
    def test_git_status_fails_cleanly_when_workspace_is_not_a_git_repo(self) -> None:
        """git.status must not silently use a parent repo above workspace_root."""
        executor = GitStatusExecutor()
        parent_repo_dir, parent_temp = _create_git_repo()
        self.addCleanup(parent_temp.cleanup)

        workspace_dir = parent_repo_dir / "nested_workspace"
        workspace_dir.mkdir()

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-status",
                    name="git.status",
                    arguments={},
                ),
                _tool_context(str(workspace_dir)),
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "git_status_failed")

    def test_git_diff_fails_cleanly_when_workspace_is_not_a_git_repo(self) -> None:
        """git.diff must not silently use a parent repo above workspace_root."""
        executor = GitDiffExecutor()
        parent_repo_dir, parent_temp = _create_git_repo()
        self.addCleanup(parent_temp.cleanup)

        workspace_dir = parent_repo_dir / "nested_workspace"
        workspace_dir.mkdir()

        result = asyncio.run(
            executor.execute(
                ToolCall(
                    call_id="call-diff",
                    name="git.diff",
                    arguments={},
                ),
                _tool_context(str(workspace_dir)),
            )
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.error_code, "git_diff_failed")


if __name__ == "__main__":
    unittest.main()
