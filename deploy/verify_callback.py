"""Probe the deployed callback without printing credentials or signed URLs.

uv run --env-file .env python deploy/verify_callback.py [--post] [--report PATH]
--post sends the same synthetic event twice for a separate database dedup check.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import uuid

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wecom_kf.config import Settings
from wecom_kf.crypto import CallbackCrypto

BASE_URL = "https://kf.lazycampus.com"
CALLBACK = BASE_URL + "/callbacks/wecom/kf"


def envelope(message, settings):
    key = base64.b64decode(settings.aes_key + "=", validate=True)
    raw = os.urandom(16) + struct.pack("!I", len(message)) + message + settings.corp_id.encode()
    padder = padding.PKCS7(256).padder()
    padded = padder.update(raw) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    encrypted = base64.b64encode(cipher.update(padded) + cipher.finalize()).decode()
    timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
    signature = hashlib.sha1("".join(sorted([settings.token, timestamp, nonce, encrypted])).encode()).hexdigest()
    return encrypted, {"timestamp": timestamp, "nonce": nonce, "msg_signature": signature}


def probe(settings, post=False):
    CallbackCrypto(settings.corp_id, settings.token, settings.aes_key)
    report = {"base_url": BASE_URL, "checked_at": int(time.time()), "checks": []}

    def record(name, response, expected_status, expected_body=None):
        passed = response.status_code == expected_status
        if expected_body is not None:
            passed = passed and response.content == expected_body
        report["checks"].append({"name": name, "status": response.status_code,
                                 "milliseconds": round(response.elapsed.total_seconds() * 1000, 1),
                                 "passed": passed})
        if not passed:
            raise RuntimeError(f"{name} failed: HTTP {response.status_code}")

    with httpx.Client(timeout=15, follow_redirects=False) as client:
        health = client.get(BASE_URL + "/healthz")
        record("health", health, 200)
        state = health.json()
        if state.get("execution_enabled") is not False or state.get("message_processing_enabled") is not False:
            raise RuntimeError("Callback-only feature gates differ")
        report["revision"] = state.get("revision")
        record("database_ready", client.get(BASE_URL + "/readyz"), 200)
        record("unsigned_rejected", client.get(CALLBACK), 403)
        record("no_frontend", client.get(BASE_URL + "/admin"), 404)
        expected = ("verification-" + uuid.uuid4().hex).encode()
        encrypted, query = envelope(expected, settings)
        response = client.get(CALLBACK, params={**query, "echostr": encrypted})
        record("signed_echo_exact", response, 200, expected)
        if response.headers.get("cache-control") != "no-store":
            raise RuntimeError("Callback cache-control is not no-store")
        record("wrong_signature_rejected", client.get(CALLBACK, params={
            **query, "echostr": encrypted, "msg_signature": "0" * 40,
        }), 403)
        if post:
            probe_id = uuid.uuid4().hex
            message = (f"<xml><ToUserName>{settings.corp_id}</ToUserName>"
                       f"<CreateTime>{int(time.time())}</CreateTime><MsgType>event</MsgType>"
                       f"<Event>kf_msg_or_event</Event><Token>probe_{probe_id}</Token>"
                       f"<OpenKfId>wk_probe_{probe_id}</OpenKfId></xml>").encode()
            encrypted, query = envelope(message, settings)
            packet = f"<xml><Encrypt><![CDATA[{encrypted}]]></Encrypt></xml>"
            for name in ("encrypted_post", "duplicate_post"):
                record(name, client.post(CALLBACK, params=query, content=packet,
                                        headers={"Content-Type": "application/xml"}), 200, b"success")
            report["synthetic_event_digest"] = hashlib.sha256(message).hexdigest()
            report["database_verification_required"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        report = probe(Settings.from_env(), args.post)
    except httpx.HTTPError:
        raise SystemExit("Public callback network request failed; signed URL and payload withheld") from None
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from None
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
