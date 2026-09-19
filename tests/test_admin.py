import base64
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import RedirectResponse
from cryptography.fernet import Fernet

from wecom_kf.admin import install_admin
from wecom_kf.config import Settings


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("corp", "token", "key", oidc_secret="private",
                                 session_secret="s" * 64, data_key=Fernet.generate_key().decode())
        self.oauth = Mock()
        self.remote = self.oauth.register.return_value
        self.remote.authorize_redirect = AsyncMock(return_value=RedirectResponse("https://auth.lazycampus.com/"))
        self.remote.authorize_access_token = AsyncMock()
        self.app = FastAPI()
        self.static_dir = tempfile.TemporaryDirectory()
        static_path = Path(self.static_dir.name)
        (static_path / "assets").mkdir()
        (static_path / "index.html").write_text(
            '<!doctype html><div id="app"></div><script type="module" src="/admin/assets/admin.js"></script>',
            encoding="utf-8",
        )
        (static_path / "assets" / "admin.js").write_text("console.log('admin')", encoding="utf-8")
        with patch("wecom_kf.admin.OAuth", return_value=self.oauth), patch("wecom_kf.admin.Store") as store:
            self.store = store.return_value
            with patch.dict(os.environ, {"ADMIN_STATIC_DIR": self.static_dir.name}):
                install_admin(self.app, self.settings)
        self.client = TestClient(self.app, base_url="https://kf.lazycampus.com")

    def tearDown(self):
        self.static_dir.cleanup()

    def test_automatic_sso_uses_pkce_and_fixed_callback(self):
        result = self.client.get("/")
        self.assertEqual(result.status_code, 200)
        login = self.client.get("/admin/auth/login", follow_redirects=False)
        self.assertEqual(login.status_code, 307)
        self.remote.authorize_redirect.assert_awaited_once()
        self.assertEqual(self.remote.authorize_redirect.call_args.args[1], "https://kf.lazycampus.com/admin/auth/callback")
        self.assertEqual(self.oauth.register.call_args.kwargs["client_kwargs"]["code_challenge_method"], "S256")

    def test_admin_path_remains_compatible_with_root_entry(self):
        from itsdangerous import TimestampSigner
        session = {"admin": {"name": "operator", "until": time.time() + 200}}
        cookie = TimestampSigner(self.settings.session_secret).sign(
            base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        root = self.client.get("/")
        legacy = self.client.get("/admin", follow_redirects=False)
        slash = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(root.status_code, 200)
        self.assertEqual(legacy.status_code, 307)
        self.assertEqual(slash.status_code, 307)
        self.assertIn('<div id="app"></div>', root.text)

    def test_authenticated_admin_uses_external_assets_and_strict_csp(self):
        from itsdangerous import TimestampSigner
        session = {"admin": {"name": "operator", "until": time.time() + 200}}
        cookie = TimestampSigner(self.settings.session_secret).sign(
            base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        result = self.client.get("/")
        self.assertEqual(result.status_code, 200)
        self.assertIn('/admin/assets/admin.js', result.text)
        self.assertEqual(self.client.get('/admin/assets/admin.js').status_code, 200)
        self.assertEqual(self.client.get('/admin/assets/secret.txt').status_code, 404)

    def test_non_admin_denied_without_redirect_loop(self):
        self.remote.authorize_access_token.return_value = {"userinfo": {"sub": "someone", "exp": time.time()+500, "realm_access": {"roles": ["user"]}}}
        result = self.client.get("/admin/auth/callback", follow_redirects=False)
        self.assertEqual(result.status_code, 403)
        self.assertNotIn("location", result.headers)

    def test_admin_cookie_does_not_contain_oauth_secrets(self):
        self.remote.authorize_access_token.return_value = {"access_token": "access-private", "refresh_token": "refresh-private",
            "userinfo": {"sub": "someone", "exp": time.time()+500, "realm_access": {"roles": ["platform-admin"]}}}
        result = self.client.get("/admin/auth/callback", follow_redirects=False)
        self.assertEqual(result.status_code, 303)
        cookie = result.headers["set-cookie"]
        self.assertIn("httponly", cookie.lower())
        self.assertIn("secure", cookie.lower())
        self.assertIn("samesite=lax", cookie.lower())
        import base64, json
        value = cookie.split("=", 1)[1].split(".", 1)[0]
        session = json.loads(base64.b64decode(value))
        self.assertEqual(set(session), {"admin"})
        self.assertNotIn("private", str(session))

    def test_service_switch_accepts_missing_origin_with_csrf(self):
        from itsdangerous import TimestampSigner
        self.assertEqual(self.client.put("/admin/api/services/educoder", json={"enabled": False}).status_code, 401)
        session = {"admin": {"name": "operator", "until": time.time()+200}, "csrf": "known-csrf"}
        cookie = TimestampSigner(self.settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        url = "/admin/api/services/educoder"
        self.assertEqual(self.client.put(url, json={"enabled": False}).status_code, 403)
        headers = {"Origin": self.settings.public_base_url}
        headers["X-CSRF-Token"] = "known-csrf"
        self.assertEqual(self.client.put(url, headers={**headers, "Origin": "https://other.example"}, json={"enabled": False}).status_code, 403)
        self.assertEqual(self.client.put(url, headers={"Origin": self.settings.public_base_url, "X-CSRF-Token": "wrong"}, json={"enabled": False}).status_code, 403)
        response = self.client.put(url, headers=headers, json={"enabled": False})
        self.assertEqual(response.status_code, 200)
        self.store.set_service_enabled.assert_called_once_with("educoder", False, "operator")
        self.client.put(url, headers=headers, json={"enabled": True})
        self.store.set_service_enabled.assert_called_with("educoder", True, "operator")

    def test_human_switch_and_unbind_require_admin_form(self):
        from itsdangerous import TimestampSigner
        session = {"admin": {"name": "operator", "until": time.time()+200}, "csrf": "known-csrf"}
        cookie = TimestampSigner(self.settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        headers = {"Origin": self.settings.public_base_url}
        data = {"enabled": True}
        self.assertEqual(self.client.put("/admin/api/human-support", json=data).status_code, 403)
        self.assertEqual(self.client.put("/admin/api/human-support", headers={**headers, "X-CSRF-Token": "known-csrf"}, json=data).status_code, 200)
        self.store.set_human_support_enabled.assert_called_with(True, "operator")
        customer = "a" * 64
        url = f"/admin/api/bindings/{customer}/unbind"
        mutation_headers = {**headers, "X-CSRF-Token": "known-csrf"}
        self.assertEqual(self.client.post(url, headers=mutation_headers, json={}).status_code, 422)
        self.assertEqual(self.client.post(url, headers=mutation_headers, json={"login_no": "login"}).status_code, 200)
        self.store.unbind.assert_called_once_with(customer, "login")
