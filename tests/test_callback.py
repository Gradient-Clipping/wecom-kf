import base64
import hashlib
import os
import struct
import time
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

from wecom_kf.app import CALLBACK_PATH, create_app
from wecom_kf.config import Settings
from wecom_kf.crypto import CallbackCrypto, InvalidCallback
from wecom_kf.inbox import MySQLInbox

KEY = base64.b64encode(bytes(range(32))).decode().rstrip("=")
SETTINGS = Settings(corp_id="ww_test_corp", token="testToken123", aes_key=KEY)


def encrypt(message: bytes, *, corp_id=SETTINGS.corp_id, raw=None):
    key = base64.b64decode(KEY + "=")
    if raw is None:
        raw = b"0123456789abcdef" + struct.pack("!I", len(message)) + message + corp_id.encode()
    padder = padding.PKCS7(256).padder()
    plaintext = padder.update(raw) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(cipher.update(plaintext) + cipher.finalize()).decode()


def params(encrypted, *, timestamp=None):
    values = {"timestamp": str(int(time.time()) if timestamp is None else timestamp), "nonce": "123abc"}
    values["msg_signature"] = hashlib.sha1("".join(sorted([
        SETTINGS.token, values["timestamp"], values["nonce"], encrypted,
    ])).encode()).hexdigest()
    return values


def event_xml():
    return (f"<xml><ToUserName>{SETTINGS.corp_id}</ToUserName><MsgType>event</MsgType>"
            "<Event>kf_msg_or_event</Event><Token>sync-token</Token><OpenKfId>wk_test</OpenKfId></xml>").encode()


class CallbackTests(unittest.TestCase):
    def setUp(self):
        self.inbox = Mock()
        self.client = TestClient(create_app(SETTINGS, self.inbox))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)

    def test_get_returns_exact_decrypted_bytes_without_json_or_newline(self):
        expected = "challenge-\u4e2d\u6587".encode()
        encrypted = encrypt(expected)
        response = self.client.get(CALLBACK_PATH, params={**params(encrypted), "echostr": encrypted})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, expected)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.inbox.record.assert_not_called()

    def test_invalid_signatures_missing_parameters_and_duplicate_parameters_fail(self):
        encrypted = encrypt(b"challenge")
        query = {**params(encrypted), "echostr": encrypted}
        query["msg_signature"] = "0" * 40
        self.assertEqual(self.client.get(CALLBACK_PATH, params=query).status_code, 403)
        self.assertEqual(self.client.get(CALLBACK_PATH).status_code, 403)
        query = list({**params(encrypted), "echostr": encrypted}.items()) + [("nonce", "second")]
        self.assertEqual(self.client.get(CALLBACK_PATH, params=query).status_code, 403)

    def test_expired_signed_callback_fails(self):
        encrypted = encrypt(b"challenge")
        self.assertEqual(self.client.get(CALLBACK_PATH, params={
            **params(encrypted, timestamp=int(time.time()) - 1000), "echostr": encrypted,
        }).status_code, 403)

    def test_wrong_receive_id_and_invalid_lengths_fail(self):
        for encrypted in (encrypt(b"echo", corp_id="other"), encrypt(b"", raw=b"tiny"),
                          encrypt(b"", raw=b"0" * 16 + struct.pack("!I", 99999) + b"a")):
            with self.subTest(encrypted=encrypted):
                query = params(encrypted)
                with self.assertRaises(InvalidCallback):
                    CallbackCrypto(SETTINGS.corp_id, SETTINGS.token, KEY).decrypt(
                        encrypted, query["msg_signature"], query["timestamp"], query["nonce"],
                    )

    def test_malformed_base64_and_bad_padding_fail_after_signature_check(self):
        for encrypted in ("not-base64", base64.b64encode(b"short").decode(), base64.b64encode(b"x" * 32).decode()):
            query = params(encrypted)
            with self.assertRaises(InvalidCallback):
                CallbackCrypto(SETTINGS.corp_id, SETTINGS.token, KEY).decrypt(
                    encrypted, query["msg_signature"], query["timestamp"], query["nonce"],
                )

    def test_authenticated_post_is_durable_before_ack(self):
        message = event_xml()
        encrypted = encrypt(message)
        response = self.client.post(CALLBACK_PATH, params=params(encrypted),
                                    content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"success")
        self.inbox.record.assert_called_once_with(message, encrypted, unittest.mock.ANY)

    def test_inbox_failure_is_not_acknowledged_or_logged_with_payload(self):
        self.inbox.record.side_effect = RuntimeError("sensitive-database-password")
        encrypted = encrypt(event_xml())
        with self.assertLogs("wecom_kf", level="ERROR") as logs:
            response = self.client.post(CALLBACK_PATH, params=params(encrypted),
                                        content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive", " ".join(logs.output))
        self.assertNotIn(encrypted, " ".join(logs.output))

    def test_xml_entities_duplicate_fields_wrong_corp_and_wrong_events_are_rejected(self):
        for message in (
            event_xml().replace(b"kf_msg_or_event", b"unknown_event"),
            event_xml().replace(b"ww_test_corp", b"other"),
            event_xml().replace(b"</xml>", b"<Token>other</Token></xml>"),
            b'<!DOCTYPE xml [<!ENTITY x "secret">]><xml>&x;</xml>',
        ):
            encrypted = encrypt(message)
            response = self.client.post(CALLBACK_PATH, params=params(encrypted),
                                        content=f"<xml><Encrypt>{encrypted}</Encrypt></xml>")
            self.assertEqual(response.status_code, 403)
        self.inbox.record.assert_not_called()

    def test_invalid_outer_xml_and_oversized_body_are_rejected(self):
        self.assertEqual(self.client.post(CALLBACK_PATH, content="<broken>").status_code, 403)
        self.assertEqual(self.client.post(CALLBACK_PATH, content=b"x" * 65537).status_code, 413)
        self.inbox.record.assert_not_called()

    def test_no_frontend_docs_execution_or_redirect(self):
        for path in ("/", "/admin", "/docs", "/openapi.json", CALLBACK_PATH + "/"):
            self.assertEqual(self.client.get(path, follow_redirects=False).status_code, 404)
        health = self.client.get("/healthz").json()
        self.assertFalse(health["execution_enabled"])
        self.assertFalse(health["message_processing_enabled"])
        self.assertEqual(self.client.get("/readyz").status_code, 200)
        self.inbox.ping.side_effect = RuntimeError()
        self.assertEqual(self.client.get("/readyz").status_code, 503)

    def test_settings_redact_secrets_and_forbid_enabling_unimplemented_features(self):
        self.assertNotIn(SETTINGS.token, repr(SETTINGS))
        self.assertNotIn(KEY, repr(SETTINGS))
        with patch.dict(os.environ, {"EDUCODER_EXECUTION_ENABLED": "true"}):
            with self.assertRaises(ValueError):
                Settings.from_env()


@unittest.skipUnless(os.getenv("TEST_MYSQL") == "1", "Requires isolated integration-test MySQL")
class MySQLTests(unittest.TestCase):
    def test_inbox_is_durable_and_deduplicates_without_storing_plaintext(self):
        settings = replace(Settings.from_env(), corp_id=SETTINGS.corp_id, token=SETTINGS.token, aes_key=KEY)
        self.assertTrue(settings.mysql_database.endswith("_test"))
        inbox = MySQLInbox(settings)
        inbox.initialize()
        inbox.ping()
        message = event_xml() + os.urandom(16)
        encrypted = encrypt(message)
        digest = hashlib.sha256(message).hexdigest()
        inbox.record(message, encrypted, "test-key-id")
        inbox.record(message, encrypted, "test-key-id")
        with inbox._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT encrypted_payload, delivery_count FROM wecom_callback_inbox WHERE event_digest=%s", (digest,))
            stored, count = cursor.fetchone()
            self.assertEqual(stored, encrypted.encode())
            self.assertNotIn(b"sync-token", stored)
            self.assertEqual(count, 2)
            cursor.execute("DELETE FROM wecom_callback_inbox WHERE event_digest=%s", (digest,))


if __name__ == "__main__":
    unittest.main()
