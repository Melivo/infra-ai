from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest

from cli.main import parse_args, should_run_interactive


class CLIEntrypointTests(unittest.TestCase):
    def test_parse_args_accepts_router_url_alias(self) -> None:
        args = parse_args(["--router-url", "http://127.0.0.1:8010/v1", "--capabilities"])

        self.assertEqual(args.router_url, "http://127.0.0.1:8010/v1")
        self.assertTrue(args.capabilities)

    def test_parse_args_keeps_legacy_base_url_alias(self) -> None:
        args = parse_args(["--base-url", "http://127.0.0.1:8010/v1", "--capabilities"])

        self.assertEqual(args.router_url, "http://127.0.0.1:8010/v1")
        self.assertTrue(args.capabilities)

    def test_interactive_mode_is_selected_for_tty_without_prompt(self) -> None:
        args = parse_args([])

        self.assertTrue(
            should_run_interactive(
                args,
                stdin_isatty=True,
                stdout_isatty=True,
            )
        )

    def test_interactive_mode_is_disabled_for_prompt_or_piped_input(self) -> None:
        prompt_args = parse_args(["Sag hallo"])
        ttyless_args = parse_args([])

        self.assertFalse(
            should_run_interactive(
                prompt_args,
                stdin_isatty=True,
                stdout_isatty=True,
            )
        )
        self.assertFalse(
            should_run_interactive(
                ttyless_args,
                stdin_isatty=False,
                stdout_isatty=True,
            )
        )

    def test_python_module_entrypoint_supports_help(self) -> None:
        repo_root = pathlib.Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [sys.executable, "-m", "cli", "--help"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("infra-ai router", result.stdout)


if __name__ == "__main__":
    unittest.main()
