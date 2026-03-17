from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cli import tool_selector
from cli.main import (
    build_payload,
    extract_visible_text,
    parse_args,
    render_response_text,
    run_interactive,
    should_run_interactive,
)


class CLIEntrypointTests(unittest.TestCase):
    def test_build_payload_preserves_explicit_empty_tool_selection(self) -> None:
        payload = build_payload(
            prompt="Hallo",
            model="auto",
            route="auto",
            system_prompt=None,
            temperature=0.2,
            max_tokens=128,
            stream=False,
            allowed_tools=[],
        )

        self.assertIn("allowed_tools", payload)
        self.assertEqual(payload["allowed_tools"], [])

    def test_parse_args_accepts_router_url_alias(self) -> None:
        args = parse_args(["--router-url", "http://127.0.0.1:8010/v1", "--capabilities"])

        self.assertEqual(args.router_url, "http://127.0.0.1:8010/v1")
        self.assertTrue(args.capabilities)

    def test_parse_args_keeps_legacy_base_url_alias(self) -> None:
        args = parse_args(["--base-url", "http://127.0.0.1:8010/v1", "--capabilities"])

        self.assertEqual(args.router_url, "http://127.0.0.1:8010/v1")
        self.assertTrue(args.capabilities)

    def test_parse_args_uses_current_default_max_tokens(self) -> None:
        args = parse_args(["Sag hallo"])

        self.assertEqual(args.max_tokens, 20000)

    def test_parse_args_keeps_explicit_max_tokens_override(self) -> None:
        args = parse_args(["--max-tokens", "512", "Sag hallo"])

        self.assertEqual(args.max_tokens, 512)

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

    def test_run_interactive_keeps_empty_tool_selection(self) -> None:
        args = parse_args([])

        with (
            patch("cli.main.select_tools", return_value=[]),
            patch("cli.main._run_request") as run_request,
            patch("builtins.input", side_effect=["Hallo", "/exit"]),
        ):
            run_interactive(args)

        run_request.assert_called_once()
        self.assertEqual(run_request.call_args.kwargs["allowed_tools"], [])

    def test_extract_visible_text_hides_leading_think_block(self) -> None:
        thought, visible = extract_visible_text("<think>intern</think>\n\nSichtbare Antwort")

        self.assertEqual(thought, "intern")
        self.assertEqual(visible, "Sichtbare Antwort")

    def test_render_response_text_hides_think_block_by_default(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "<think>internes reasoning</think>\n\nFertige Antwort",
                    },
                }
            ]
        }

        rendered = render_response_text(response, elapsed_s=12.4)

        self.assertIn("Thought for 12s >", rendered)
        self.assertIn("Fertige Antwort", rendered)
        self.assertNotIn("internes reasoning", rendered)

    def test_render_response_text_can_show_think_block(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "<think>internes reasoning</think>\n\nFertige Antwort",
                    },
                }
            ]
        }

        rendered = render_response_text(response, show_thoughts=True, elapsed_s=12.4)

        self.assertIn("internes reasoning", rendered)
        self.assertIn("Fertige Antwort", rendered)
        self.assertNotIn("Thought for 12s >", rendered)

    def test_render_response_text_marks_length_truncation(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {
                        "content": "<think>intern</think>\n\nTeilantwort",
                    },
                }
            ]
        }

        rendered = render_response_text(response, elapsed_s=8.8)

        self.assertIn("Thought for 9s >", rendered)
        self.assertIn("Teilantwort", rendered)
        self.assertIn("output truncated", rendered)

    def test_render_response_text_keeps_normal_completion_clean(self) -> None:
        response = {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": "Fertige Antwort",
                    },
                }
            ]
        }

        rendered = render_response_text(response, elapsed_s=2.0)

        self.assertEqual(rendered, "Fertige Antwort")


class ToolSelectorTests(unittest.TestCase):
    def test_tool_prompt_starts_without_preselected_tools(self) -> None:
        captured: dict[str, object] = {}

        class _FakeTTY(io.StringIO):
            def isatty(self) -> bool:
                return True

        class _Prompt:
            def ask(self) -> list[str]:
                return []

        def _fake_checkbox(message, *, choices, **kwargs):
            captured["message"] = message
            captured["choices"] = choices
            captured["kwargs"] = kwargs
            return _Prompt()

        with (
            patch.object(tool_selector, "_fetch_tools", return_value=[
                {
                    "name": "echo",
                    "description": "Return the provided arguments unchanged.",
                    "risk_level": "low",
                    "capabilities": ["debug"],
                    "enabled_by_default": True,
                }
            ]),
            patch.object(tool_selector, "questionary", SimpleNamespace(checkbox=_fake_checkbox)),
            patch.object(tool_selector, "Choice", side_effect=lambda **kwargs: kwargs),
            patch.object(tool_selector.sys, "stdin", _FakeTTY()),
            patch.object(tool_selector.sys, "stdout", _FakeTTY()),
        ):
            selected = tool_selector.select_tools("http://127.0.0.1:8010/v1")

        self.assertEqual(selected, [])
        choices = captured["choices"]
        self.assertEqual(len(choices), 1)
        self.assertFalse(choices[0]["checked"])


if __name__ == "__main__":
    unittest.main()
