from __future__ import annotations

import unittest

from router.app import ConfigValidationError, RouterApplication
from router.schemas import RouterConfig


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


class RouterConfigValidationTests(unittest.TestCase):
    def test_local_only_config_is_valid(self) -> None:
        app = RouterApplication(build_config())
        self.assertEqual(app.config.local_vllm_default_model, "Qwen/Qwen3-14B-AWQ")

    def test_enabled_gemini_requires_key_and_model(self) -> None:
        with self.assertRaises(ConfigValidationError) as exc_info:
            RouterApplication(
                build_config(
                    enable_gemini_fallback=True,
                    gemini_api_key="",
                    gemini_default_model="",
                )
            )

        self.assertIn("GEMINI_API_KEY", str(exc_info.exception))
        self.assertIn("INFRA_AI_GEMINI_DEFAULT_MODEL", str(exc_info.exception))

    def test_gemini_placeholder_model_is_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as exc_info:
            RouterApplication(
                build_config(
                    enable_gemini_fallback=True,
                    gemini_api_key="test-key",
                    gemini_default_model="gemini-model-id-here",
                )
            )

        self.assertIn("real Gemini model", str(exc_info.exception))

    def test_enabled_openai_requires_key_and_reasoning_model(self) -> None:
        with self.assertRaises(ConfigValidationError) as exc_info:
            RouterApplication(
                build_config(
                    enable_openai_fallback=True,
                    openai_api_key="",
                    openai_reasoning_model="",
                )
            )

        self.assertIn("OPENAI_API_KEY", str(exc_info.exception))
        self.assertIn("INFRA_AI_OPENAI_REASONING_MODEL", str(exc_info.exception))

    def test_invalid_port_and_timeout_are_rejected(self) -> None:
        with self.assertRaises(ConfigValidationError) as exc_info:
            RouterApplication(build_config(port=0, request_timeout_s=0, max_tool_steps=0, tool_timeout_s=0))

        self.assertIn("INFRA_AI_ROUTER_PORT", str(exc_info.exception))
        self.assertIn("INFRA_AI_REQUEST_TIMEOUT_S", str(exc_info.exception))
        self.assertIn("INFRA_AI_MAX_TOOL_STEPS", str(exc_info.exception))
        self.assertIn("INFRA_AI_TOOL_TIMEOUT_S", str(exc_info.exception))

    def test_request_timeout_is_propagated_to_all_provider_clients(self) -> None:
        app = RouterApplication(build_config(request_timeout_s=42.5))

        self.assertEqual(app.providers["local_vllm"].timeout_s, 42.5)
        self.assertEqual(app.providers["gemini_fallback"].timeout_s, 42.5)
        self.assertEqual(app.providers["openai_responses"].timeout_s, 42.5)
        self.assertEqual(app.openai_models.timeout_s, 42.5)
        self.assertEqual(app.tool_loop_engine._max_tool_steps, 4)
        self.assertEqual(app.tool_loop_engine._tool_timeout_s, 30.0)


if __name__ == "__main__":
    unittest.main()
