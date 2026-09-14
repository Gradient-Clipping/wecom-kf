import base64
from datetime import timedelta
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

import httpx

from educoder_wecom.config import Settings
from educoder_wecom.crypto import CallbackCrypto, InvalidCallback, parse_xml, xml_field

PROBE = runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/verify_callback.py"))
SETTINGS = Settings("ww_test", "testToken", base64.b64encode(bytes(range(32))).decode().rstrip("="))


class PublicProbeTests(unittest.TestCase):
    def test_public_probe_checks_round_trip_and_sends_duplicate_synthetic_event(self):
        crypto = CallbackCrypto(SETTINGS.corp_id, SETTINGS.token, SETTINGS.aes_key)
        posts = []

        def handle(request):
            path = request.url.path
            if path == "/healthz":
                return httpx.Response(200, json={"execution_enabled": False, "message_processing_enabled": False,
                                                "revision": "test-revision"})
            if path == "/readyz":
                return httpx.Response(200, json={"status": "ready"})
            if path == "/admin":
                return httpx.Response(404)
            query = request.url.params
            try:
                encrypted = (query["echostr"] if request.method == "GET"
                             else xml_field(parse_xml(request.content), "Encrypt"))
                message = crypto.decrypt(encrypted, query["msg_signature"], query["timestamp"], query["nonce"])
            except (KeyError, InvalidCallback):
                return httpx.Response(403)
            if request.method == "POST":
                self.assertTrue(xml_field(parse_xml(message), "OpenKfId").startswith("wk_probe_"))
                posts.append(message)
                return httpx.Response(200, content=b"success")
            return httpx.Response(200, content=message, headers={"Cache-Control": "no-store"})

        def timed(request):
            response = handle(request)
            response.elapsed = timedelta(milliseconds=1)
            return response

        original_client = httpx.Client
        with patch.object(httpx, "Client", side_effect=lambda **kw: original_client(transport=httpx.MockTransport(timed), **kw)):
            result = PROBE["probe"](SETTINGS, True)
        self.assertTrue(all(item["passed"] for item in result["checks"]))
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0], posts[1])
        self.assertTrue(result["database_verification_required"])
        self.assertNotIn(SETTINGS.aes_key, str(result))
        self.assertNotIn(SETTINGS.token, str(result))

    def test_http_failure_is_reported_without_response_content(self):
        original_client = httpx.Client
        def unavailable(_):
            response = httpx.Response(503, text="sensitive-provider-response")
            response.elapsed = timedelta(milliseconds=1)
            return response

        transport = httpx.MockTransport(unavailable)
        with patch.object(httpx, "Client", side_effect=lambda **kw: original_client(transport=transport, **kw)):
            with self.assertRaises(RuntimeError) as error:
                PROBE["probe"](SETTINGS)
        self.assertNotIn("sensitive-provider-response", str(error.exception))
        self.assertIn("HTTP 503", str(error.exception))
