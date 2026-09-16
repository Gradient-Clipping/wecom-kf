"""Bounded WeCom API transport, without logging credentials or response bodies."""

import threading
import time
from pathlib import Path

import httpx


class WeComError(RuntimeError):
    def __init__(self, code, *, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(f"WeCom API code={code}")


class WeCom:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.client = httpx.Client(base_url="https://qyapi.weixin.qq.com/cgi-bin/",
                                   timeout=10, transport=transport, follow_redirects=False)
        self._token = ""
        self._expires = 0
        self._lock = threading.Lock()

    def _decode(self, response):
        try:
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, httpx.HTTPError):
            raise WeComError("invalid_response", uncertain=True) from None

    def token(self):
        with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            try:
                result = self._decode(self.client.get("gettoken", params={
                    "corpid": self.settings.corp_id, "corpsecret": self.settings.api_secret}))
            except httpx.HTTPError:
                raise WeComError("token_transport") from None
            if result.get("errcode", 0) or not result.get("access_token"):
                raise WeComError(result.get("errcode", "missing_token"))
            self._token = result["access_token"]
            self._expires = time.monotonic() + max(1, int(result.get("expires_in", 7200)) - 120)
            return self._token

    def call(self, path, payload):
        for attempt in range(2):
            token = self.token()
            try:
                result = self._decode(self.client.post(path, params={"access_token": token}, json=payload))
            except httpx.HTTPError:
                raise WeComError("transport", uncertain=True) from None
            code = result.get("errcode", 0)
            if not code:
                return result
            if code in {40014, 42001} and not attempt:
                with self._lock:
                    if self._token == token:
                        self._expires = 0
                continue
            raise WeComError(code)
        raise WeComError("token_refresh_exhausted")

    def sync(self, open_kfid, cursor="", token=""):
        payload = {"open_kfid": open_kfid, "limit": 1000, "voice_format": 0}
        if cursor:
            payload["cursor"] = cursor
        if token:
            payload["token"] = token
        return self.call("kf/sync_msg", payload)

    def send(self, payload):
        return self.call("kf/send_msg_on_event" if "code" in payload else "kf/send_msg", payload)

    def upload_human_service_card(self):
        path = Path(__file__).resolve().parents[2] / "assets" / "human_service_card.jpg"
        for attempt in range(2):
            token = self.token()
            try:
                with path.open("rb") as image:
                    result = self._decode(self.client.post("media/upload", params={"access_token": token, "type": "image"},
                                                            files={"media": (path.name, image, "image/jpeg",
                                                                             {"filelength": str(path.stat().st_size)})}))
            except httpx.HTTPError:
                raise WeComError("media_upload_transport") from None
            code = result.get("errcode", 0)
            if code in {40014, 42001} and not attempt:
                with self._lock:
                    if self._token == token:
                        self._expires = 0
                continue
            if code or not result.get("media_id"):
                raise WeComError(code or "missing_media_id")
            return result["media_id"]
        raise WeComError("media_upload_refresh_exhausted")
