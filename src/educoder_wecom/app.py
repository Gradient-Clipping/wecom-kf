"""Callback-only API. No admin UI, customer UI, message sender or solver."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .crypto import CallbackCrypto, InvalidCallback, parse_xml, xml_field
from .inbox import MySQLInbox

CALLBACK_PATH = "/callbacks/wecom/kf"
MAX_BODY = 65536
logger = logging.getLogger("educoder_wecom")


def create_app(settings: Settings | None = None, inbox=None) -> FastAPI:
    settings = settings or Settings.from_env()
    crypto = CallbackCrypto(settings.corp_id, settings.token, settings.aes_key)
    inbox = inbox if inbox is not None else MySQLInbox(settings)

    @asynccontextmanager
    async def lifespan(app):
        await run_in_threadpool(inbox.initialize)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None,
                  redirect_slashes=False)

    @app.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/healthz")
    def health():
        return {"status": "ok", "mode": "callback-only", "execution_enabled": False,
                "message_processing_enabled": False, "revision": settings.revision}

    @app.get("/readyz")
    def ready():
        try:
            inbox.ping()
        except Exception:
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready", "mode": "callback-only", "revision": settings.revision}

    def query(request: Request, name: str) -> str:
        values = request.query_params.getlist(name)
        if len(values) != 1 or not values[0]:
            raise InvalidCallback("Invalid callback parameters")
        return values[0]

    def decrypt(request: Request, encrypted: str) -> bytes:
        timestamp = query(request, "timestamp")
        message = crypto.decrypt(encrypted, query(request, "msg_signature"), timestamp, query(request, "nonce"))
        if abs(time.time() - int(timestamp)) > settings.max_clock_skew:
            raise InvalidCallback("Expired callback")
        return message

    @app.get(CALLBACK_PATH)
    def verify(request: Request):
        try:
            message = decrypt(request, query(request, "echostr"))
            message.decode("utf-8")
        except (InvalidCallback, UnicodeError):
            return PlainTextResponse("invalid callback", status_code=403)
        return Response(message, media_type="text/plain")

    @app.post(CALLBACK_PATH)
    async def receive(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY:
                return PlainTextResponse("request too large", status_code=413)
        try:
            outer = parse_xml(bytes(body))
            encrypted = xml_field(outer, "Encrypt")
            outer_id = xml_field(outer, "ToUserName", required=False)
            if outer_id and outer_id != settings.corp_id:
                raise InvalidCallback("Wrong receive ID")
            message = decrypt(request, encrypted)
            event = parse_xml(message)
            if (xml_field(event, "ToUserName") != settings.corp_id
                    or xml_field(event, "MsgType") != "event"
                    or xml_field(event, "Event") != "kf_msg_or_event"):
                raise InvalidCallback("Unexpected event")
            if not xml_field(event, "Token") or not xml_field(event, "OpenKfId"):
                raise InvalidCallback("Missing synchronization fields")
        except InvalidCallback:
            return PlainTextResponse("invalid callback", status_code=403)
        try:
            await run_in_threadpool(inbox.record, message, encrypted, crypto.key_id)
        except Exception:
            logger.error("callback_inbox_unavailable")
            return PlainTextResponse("temporarily unavailable", status_code=503)
        return PlainTextResponse("success")

    return app
