from __future__ import annotations

import asyncio
from pathlib import Path
import subprocess
import tempfile
import unittest

from router.tools.core_tools import register_core_tools
from router.tools.registry import ToolRegistry
from router.tools.types import ToolCall, ToolContext


class CoreToolsTests(unittest.TestCase):
    def _build_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        register_core_tools(registry)
        return registry

    def _run_tool(
        self,
        registry: ToolRegistry,
        *,
        name: str,
        arguments: dict[str, object],
        workspace_root: str,
    ):
        return asyncio.run(
            registry.get_executor(name).execute(
                ToolCall(call_id=f"call-{name}", name=name, arguments=arguments),
                ToolContext(request_id="req-1", workspace_root=workspace_root),
            )
        )

    def test_register_core_tools_exposes_expected_specs(self) -> None:
        registry = self._build_registry()

        self.assertEqual(
            [spec.name for spec in registry.list_specs()],
            [
                "filesystem.list",
                "filesystem.read",
                "git.diff",
                "git.status",
            ],
        )

    def test_filesystem_read_returns_structured_result_for_workspace_file(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            file_path = Path(workspace_root) / "notes.txt"
            file_path.write_text("alpha\nbeta\n", encoding="utf-8")

            result = self._run_tool(
                registry,
                name="filesystem.read",
                arguments={"path": "notes.txt"},
                workspace_root=workspace_root,
            )

        self.assertEqual(result.ok, True)
        self.assertEqual(result.output_json["path"], "notes.txt")
        self.assertEqual(result.output_json["resolved_path"], "notes.txt")
        self.assertEqual(result.output_json["content"], "alpha\nbeta\n")
        self.assertEqual(result.output_json["encoding"], "utf-8")
        self.assertEqual(result.output_json["truncated"], False)

    def test_filesystem_read_rejects_path_outside_workspace(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
                handle.write("outside")
                outside_path = handle.name

            result = self._run_tool(
                registry,
                name="filesystem.read",
                arguments={"path": outside_path},
                workspace_root=workspace_root,
            )

            Path(outside_path).unlink(missing_ok=True)

        self.assertEqual(result.ok, False)
        self.assertEqual(result.error_code, "workspace_boundary_violation")

    def test_filesystem_read_rejects_directory_targets(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            result = self._run_tool(
                registry,
                name="filesystem.read",
                arguments={"path": "."},
                workspace_root=workspace_root,
            )

        self.assertEqual(result.ok, False)
        self.assertEqual(result.error_code, "not_a_file")

    def test_filesystem_list_returns_structured_entries_for_workspace_directory(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            root = Path(workspace_root)
            (root / "b.txt").write_text("b", encoding="utf-8")
            (root / "a.txt").write_text("a", encoding="utf-8")
            (root / "nested").mkdir()

            result = self._run_tool(
                registry,
                name="filesystem.list",
                arguments={"path": "."},
                workspace_root=workspace_root,
            )

        self.assertEqual(result.ok, True)
        self.assertEqual(
            [entry["name"] for entry in result.output_json["entries"]],
            ["a.txt", "b.txt", "nested"],
        )
        self.assertEqual(result.output_json["entry_count"], 3)
        self.assertEqual(result.output_json["truncated"], False)

    def test_filesystem_list_rejects_path_outside_workspace(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            result = self._run_tool(
                registry,
                name="filesystem.list",
                arguments={"path": ".."},
                workspace_root=workspace_root,
            )

        self.assertEqual(result.ok, False)
        self.assertEqual(result.error_code, "workspace_boundary_violation")

    def test_git_status_returns_structured_read_only_status(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            repo_root = Path(workspace_root)
            _init_git_repo(repo_root)
            tracked_file = repo_root / "tracked.txt"
            tracked_file.write_text("initial\n", encoding="utf-8")
            _run_git(repo_root, "add", "tracked.txt")
            _run_git(repo_root, "commit", "-m", "initial")
            head_before = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
            tracked_file.write_text("changed\n", encoding="utf-8")

            result = self._run_tool(
                registry,
                name="git.status",
                arguments={},
                workspace_root=workspace_root,
            )
            head_after = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual(result.ok, True)
        self.assertEqual(head_before, head_after)
        self.assertEqual(result.output_json["clean"], False)
        self.assertEqual(result.output_json["entry_count"], 1)
        self.assertEqual(result.output_json["entries"][0]["path"], "tracked.txt")
        self.assertIn("## ", result.output_json["branch_line"])

    def test_git_diff_returns_structured_read_only_diff_result(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            repo_root = Path(workspace_root)
            _init_git_repo(repo_root)
            tracked_file = repo_root / "tracked.txt"
            tracked_file.write_text("initial\n", encoding="utf-8")
            _run_git(repo_root, "add", "tracked.txt")
            _run_git(repo_root, "commit", "-m", "initial")
            head_before = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
            tracked_file.write_text("changed\n", encoding="utf-8")

            result = self._run_tool(
                registry,
                name="git.diff",
                arguments={},
                workspace_root=workspace_root,
            )
            head_after = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()

        self.assertEqual(result.ok, True)
        self.assertEqual(head_before, head_after)
        self.assertIn("diff --git", result.output_json["diff"])
        self.assertEqual(result.output_json["truncated"], False)

    def test_git_tools_fail_cleanly_outside_git_repository(self) -> None:
        registry = self._build_registry()
        with tempfile.TemporaryDirectory() as workspace_root:
            status_result = self._run_tool(
                registry,
                name="git.status",
                arguments={},
                workspace_root=workspace_root,
            )
            diff_result = self._run_tool(
                registry,
                name="git.diff",
                arguments={},
                workspace_root=workspace_root,
            )

        self.assertEqual(status_result.ok, False)
        self.assertEqual(diff_result.ok, False)
        self.assertEqual(status_result.error_code, "git_status_failed")
        self.assertEqual(diff_result.error_code, "git_diff_failed")


def _init_git_repo(repo_root: Path) -> None:
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.email", "tests@example.com")
    _run_git(repo_root, "config", "user.name", "Infra AI Tests")


def _run_git(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed


if __name__ == "__main__":
    unittest.main()
