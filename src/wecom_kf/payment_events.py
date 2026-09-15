"""Authenticate and durably retain payment events before acknowledging them."""
import hmac
import hashlib
import json
import re
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .payments import signature
from .store import Store


def install_payment_events(app, settings):
    store = Store(settings)

    @app.post("/callbacks/payments")
    async def receive(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                return JSONResponse({"error": "too_large"}, status_code=413)
        try:
            data = json.loads(body)
            headers = request.headers
            timestamp, nonce = headers.get("x-timestamp", ""), headers.get("x-nonce", "")
            if (not re.fullmatch(r"\d{10}", timestamp) or abs(time.time() - int(timestamp)) > 300
                    or not re.fullmatch(r"[a-zA-Z0-9-]{16,80}", nonce)
                    or headers.get("x-platform-code") != settings.payment_platform
                    or data.get("platform_code") != settings.payment_platform
                    or not re.fullmatch(r"[a-f0-9-]{36}", data.get("event_id", ""))):
                raise ValueError()
            expected = signature(settings.payment_secret, "POST", "/callbacks/payments", timestamp, nonce, data)
            if not hmac.compare_digest(expected, headers.get("x-signature", "")):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "invalid_signature"}, status_code=401)

        def retain():
            with store.transaction() as cur:
                cur.execute("DELETE FROM kf_payment_nonces WHERE expires_at<%s LIMIT 1000", (time.time(),))
                cur.execute("INSERT IGNORE INTO kf_payment_nonces VALUES (%s,%s)",
                            (hashlib.sha256((settings.payment_platform + ':' + nonce).encode()).hexdigest(), time.time() + 600))
                if cur.rowcount != 1:
                    raise ValueError("replayed")
                cur.execute("INSERT IGNORE INTO kf_payment_events (id,payload,received_at) VALUES (%s,%s,%s)",
                            (data["event_id"], json.dumps(data), time.time()))
                # The worker reads authoritative order state, not callback claims.
                cur.execute("UPDATE kf_purchases SET updated_at=0 WHERE order_id=%s AND status='WAITING'", (data.get("order_id"),))
        try:
            await run_in_threadpool(retain)
        except ValueError:
            return JSONResponse({"error": "replayed"}, status_code=401)
        except Exception:
            return JSONResponse({"error": "unavailable"}, status_code=503)
        return {"accepted": True}
