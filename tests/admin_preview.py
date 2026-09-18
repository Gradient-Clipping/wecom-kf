"""Loopback-only UI acceptance fixture; never use this app for deployment.

Run: uv run --frozen python -m tests.admin_preview
Uses disposable SQLite data and production admin routes/queries. The fake OIDC
client authenticates a test-only operator; no external systems are contacted.
"""
import time
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
import uvicorn

from tests.test_admin_queries import SQLiteStore
from wecom_kf.admin import install_admin
from wecom_kf.config import Settings
from wecom_kf.store import Store


def create_preview():
    store = SQLiteStore()
    store.service_states = lambda: [{"code": "educoder", "name": "头歌（测试）", "enabled": True}]
    store.human_support_enabled = lambda: False
    store.bindings_for_admin = lambda q="": Store.bindings_for_admin(store, q)
    store.set_service_enabled = Mock()
    store.set_human_support_enabled = Mock()
    store.unbind = Mock(side_effect=RuntimeError("Preview is read-only"))
    store.connection.execute("INSERT INTO kf_workers VALUES ('executor', NULL)")
    store.connection.execute("INSERT INTO kf_workers VALUES ('gateway', ?)", (time.time(),))
    store.connection.execute("INSERT INTO kf_outbox VALUES ('pending')")
    # Modern dates in UI without changing the deterministic SQL test fixture.
    store.connection.execute("UPDATE kf_jobs SET created_at=created_at+1789690000, updated_at=?", (time.time(),))
    store.connection.commit()
    oauth = Mock()
    oauth.register.return_value.authorize_redirect = AsyncMock(return_value=RedirectResponse('/admin/auth/callback'))
    oauth.register.return_value.authorize_access_token = AsyncMock(side_effect=lambda *_: {
        "userinfo": {"sub": "preview", "preferred_username": "本地模拟数据", "exp": time.time() + 300,
                     "realm_access": {"roles": ["platform-admin"]}}})
    settings = Settings("fixture", "fixture", "fixture", oidc_secret="fixture",
                        public_base_url="http://localhost:8766", session_secret="preview-only-" * 6,
                        data_key=Fernet.generate_key().decode())
    app = FastAPI()
    app.state.fixture_store = store
    with patch("wecom_kf.admin.Store", return_value=store), patch("wecom_kf.admin.OAuth", return_value=oauth):
        install_admin(app, settings)
    return app


if __name__ == "__main__":
    uvicorn.run(create_preview(), host="127.0.0.1", port=8766)
