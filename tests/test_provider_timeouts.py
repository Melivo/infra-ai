from __future__ import annotations

import unittest
from socket import timeout as SocketTimeout
from unittest.mock import patch
from urllib import error

from router.providers.base import ProviderError, request_json, request_stream


class ProviderTimeoutTests(unittest.TestCase):
    @patch("router.providers.base.request.urlopen")
    def test_request_json_passes_router_timeout_to_upstream_call(self, mock_urlopen) -> None:
        mock_response = mock_urlopen.return_value.__enter__.return_value
        mock_response.read.return_value = b"{}"
        mock_response.getcode.return_value = 200

        request_json(
            method="GET",
            url="http://provider.test/models",
            timeout_s=7.5,
            provider_name="local_vllm",
        )

        _, kwargs = mock_urlopen.call_args
        self.assertEqual(kwargs["timeout"], 7.5)

    @patch("router.providers.base.request.urlopen")
    def test_request_stream_passes_router_timeout_to_upstream_call(self, mock_urlopen) -> None:
        request_stream(
            method="POST",
            url="http://provider.test/chat/completions",
            timeout_s=9.0,
            provider_name="local_vllm",
            payload={"messages": []},
        )

        _, kwargs = mock_urlopen.call_args
        self.assertEqual(kwargs["timeout"], 9.0)

    @patch("router.providers.base.request.urlopen")
    def test_request_json_maps_upstream_timeout_to_consistent_provider_error(
        self,
        mock_urlopen,
    ) -> None:
        mock_urlopen.side_effect = error.URLError(SocketTimeout("timed out"))

        with self.assertRaises(ProviderError) as exc_info:
            request_json(
                method="GET",
                url="http://provider.test/models",
                timeout_s=5.0,
                provider_name="gemini_fallback",
            )

        self.assertEqual(exc_info.exception.status_code, 504)
        self.assertEqual(exc_info.exception.payload["error"]["type"], "timeout")
        self.assertEqual(
            exc_info.exception.payload["error"]["message"],
            "Upstream provider request timed out.",
        )

    @patch("router.providers.base.request.urlopen")
    def test_request_stream_maps_upstream_timeout_to_consistent_provider_error(
        self,
        mock_urlopen,
    ) -> None:
        mock_urlopen.side_effect = SocketTimeout("timed out")

        with self.assertRaises(ProviderError) as exc_info:
            request_stream(
                method="POST",
                url="http://provider.test/chat/completions",
                timeout_s=5.0,
                provider_name="openai_responses",
                payload={"messages": []},
            )

        self.assertEqual(exc_info.exception.status_code, 504)
        self.assertEqual(exc_info.exception.payload["error"]["type"], "timeout")
        self.assertEqual(
            exc_info.exception.payload["error"]["message"],
            "Upstream provider request timed out.",
        )


if __name__ == "__main__":
    unittest.main()
