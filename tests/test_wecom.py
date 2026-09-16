import unittest
from dataclasses import replace
import httpx
from wecom_kf.config import Settings
from wecom_kf.wecom import WeCom, WeComError


class APITests(unittest.TestCase):
    def test_refresh_once_and_same_message_id(self):
        calls = []
        def handler(req):
            calls.append(req)
            if req.url.path.endswith('gettoken'):
                return httpx.Response(200, json={"access_token": "token", "expires_in": 7200})
            return httpx.Response(200, json={"errcode": 42001 if len(calls) == 2 else 0})
        api = WeCom(Settings("corp", "token", "key", api_secret="secret"), httpx.MockTransport(handler))
        api.send({"msgid": "stable"})
        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[1].content, calls[3].content)

    def test_transport_is_uncertain_and_not_blindly_retried(self):
        calls = []
        def handler(req):
            calls.append(req)
            if req.url.path.endswith('gettoken'):
                return httpx.Response(200, json={"access_token": "token"})
            raise httpx.ReadTimeout("private token and body must not appear", request=req)
        api = WeCom(Settings("corp", "token", "key"), httpx.MockTransport(handler))
        with self.assertRaises(WeComError) as cm:
            api.send({"msgid": "stable"})
        self.assertTrue(cm.exception.uncertain)
        self.assertNotIn("private", str(cm.exception))
        self.assertEqual(len(calls), 2)

    def test_secrets_redacted(self):
        settings = Settings("corp", "token", "aes", api_secret="api-private", data_key="data-private")
        self.assertNotIn("api-private", repr(settings))
        self.assertNotIn("data-private", repr(settings))

    def test_upload_human_service_card_uses_multipart_and_media_id(self):
        calls = []
        def handler(req):
            calls.append(req)
            if req.url.path.endswith("gettoken"):
                return httpx.Response(200, json={"access_token": "token"})
            if req.url.path.endswith("media/upload"):
                self.assertEqual(req.url.params["type"], "image")
                self.assertIn(b'human_service_card.jpg', req.content)
                self.assertIn(b'filelength', req.content)
                return httpx.Response(200, json={"errcode": 0, "media_id": "uploaded"})
            return httpx.Response(200, json={"errcode": 0})
        api = WeCom(Settings("corp", "token", "key", api_secret="secret"), httpx.MockTransport(handler))
        media_id = api.upload_human_service_card()
        api.send({"msgtype": "image", "image": {"media_id": media_id}})
        self.assertEqual(media_id, "uploaded")
        self.assertIn(b'"media_id":"uploaded"', calls[-1].content)
