import time
import unittest
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
        with patch("wecom_kf.admin.OAuth", return_value=self.oauth), patch("wecom_kf.admin.Store") as store:
            self.store = store.return_value
            install_admin(self.app, self.settings)
        self.client = TestClient(self.app, base_url="https://kf.lazycampus.com")

    def test_automatic_sso_uses_pkce_and_fixed_callback(self):
        result = self.client.get("/admin", follow_redirects=False)
        self.assertIn(result.status_code, (302, 307))
        self.remote.authorize_redirect.assert_awaited_once()
        self.assertEqual(self.remote.authorize_redirect.call_args.args[1], "https://kf.lazycampus.com/admin/auth/callback")
        self.assertEqual(self.oauth.register.call_args.kwargs["client_kwargs"]["code_challenge_method"], "S256")

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
        import base64, json
        from itsdangerous import TimestampSigner
        self.assertEqual(self.client.post("/admin/services/educoder").status_code, 403)
        session = {"admin": {"name": "operator", "until": time.time()+200}, "csrf": "known-csrf"}
        cookie = TimestampSigner(self.settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        url = "/admin/services/educoder"
        self.assertEqual(self.client.post(url, data={"csrf": "wrong"}).status_code, 403)
        headers = {"Origin": self.settings.public_base_url}
        self.assertEqual(self.client.post(url, headers={"Origin": "https://other.example"}, data={"csrf": "known-csrf"}).status_code, 403)
        self.assertEqual(self.client.post(url, headers=headers, data={"csrf": "wrong"}).status_code, 403)
        response = self.client.post(url, headers=headers, data={"csrf": "known-csrf"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.store.set_service_enabled.assert_called_once_with("educoder", False, "operator")
        response = self.client.post(url, data={"csrf": "known-csrf", "enabled": "1"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.post(url, headers={"Origin": "null"}, data={"csrf": "known-csrf", "enabled": "1"}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.client.post(url, headers=headers, data={"csrf": "known-csrf", "enabled": "1"}, follow_redirects=False)
        self.store.set_service_enabled.assert_called_with("educoder", True, "operator")

    def test_human_switch_and_unbind_require_admin_form(self):
        import base64, json
        from itsdangerous import TimestampSigner
        session = {"admin": {"name": "operator", "until": time.time()+200}, "csrf": "known-csrf"}
        cookie = TimestampSigner(self.settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", cookie)
        headers = {"Origin": self.settings.public_base_url}
        data = {"csrf": "known-csrf", "enabled": "1"}
        self.assertEqual(self.client.post("/admin/human-support", data={"csrf": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post("/admin/human-support", data=data, follow_redirects=False).status_code, 303)
        self.assertEqual(self.client.post("/admin/human-support", headers=headers, data=data, follow_redirects=False).status_code, 303)
        self.store.set_human_support_enabled.assert_called_with(True, "operator")
        customer = "a" * 64
        url = f"/admin/bindings/{customer}/delete"
        self.assertEqual(self.client.post(url, headers=headers, data={"csrf": "known-csrf"}).status_code, 400)
        self.assertEqual(self.client.post(url, headers=headers, data={"csrf": "known-csrf", "login_no": "login"}, follow_redirects=False).status_code, 303)
        self.store.unbind.assert_called_once_with(customer, "login")
