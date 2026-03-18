from __future__ import annotations

import unittest

from router.tools.core_tools import register_core_tools
from router.tools.registry import ToolRegistry
from router.tools.validation import ToolArgumentsValidationError, validate_tool_arguments


class ToolValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        registry = ToolRegistry()
        register_core_tools(registry)
        self.registry = registry

    def test_filesystem_read_rejects_missing_path(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("filesystem.read").input_schema,
                {},
            )

    def test_filesystem_read_rejects_non_string_path(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("filesystem.read").input_schema,
                {"path": 123},
            )

    def test_filesystem_read_rejects_unexpected_arguments(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("filesystem.read").input_schema,
                {"path": "notes.txt", "unexpected": True},
            )

    def test_filesystem_list_rejects_non_object_or_unexpected_arguments(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("filesystem.list").input_schema,
                {"path": ".", "unexpected": True},
            )

    def test_git_status_accepts_empty_arguments(self) -> None:
        validate_tool_arguments(
            self.registry.get_spec("git.status").input_schema,
            {},
        )

    def test_git_status_rejects_boolean_for_integer_field(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("git.status").input_schema,
                {"max_entries": True},
            )

    def test_git_diff_accepts_bounded_optional_arguments(self) -> None:
        validate_tool_arguments(
            self.registry.get_spec("git.diff").input_schema,
            {"context_lines": 5, "max_bytes": 4096},
        )

    def test_git_diff_rejects_invalid_optional_arguments(self) -> None:
        with self.assertRaises(ToolArgumentsValidationError):
            validate_tool_arguments(
                self.registry.get_spec("git.diff").input_schema,
                {"context_lines": "3"},
            )


if __name__ == "__main__":
    unittest.main()
