import base64
import json
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import RedirectResponse
from itsdangerous import TimestampSigner

from wecom_kf.admin import install_admin
from wecom_kf.config import Settings


class AdminApiTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("corp", "token", "key", oidc_secret="private",
                                 session_secret="s" * 64, data_key=Fernet.generate_key().decode())
        self.oauth = Mock()
        self.oauth.register.return_value.authorize_redirect = AsyncMock(return_value=RedirectResponse("/login"))
        self.app = FastAPI()
        with patch("wecom_kf.admin.OAuth", return_value=self.oauth), patch("wecom_kf.admin.Store") as store:
            self.store = store.return_value
            install_admin(self.app, self.settings)
        self.client = TestClient(self.app, base_url="https://kf.lazycampus.com")

    def authenticated(self):
        session = {"admin": {"name": "operator", "until": time.time() + 200}}
        value = TimestampSigner(self.settings.session_secret).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set("__Host-kf-admin", value)

    def test_unauthenticated_reads_are_json_401_and_no_store(self):
        for path in ("/admin/api/overview", "/admin/api/jobs", "/admin/api/jobs/" + "a" * 32, "/admin/api/bindings"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"error": "session_expired"})
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_filters_and_missing_job_are_stable_json_errors(self):
        self.authenticated()
        for query in ("page=0", "page_size=30", "status=queued", "page=1&page=2", "unknown=x"):
            response = self.client.get("/admin/api/jobs?" + query)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json(), {"error": "invalid_query"})
            self.assertEqual(response.headers["cache-control"], "no-store")
        with patch("wecom_kf.admin_queries.AdminQueries.job", return_value=None):
            response = self.client.get("/admin/api/jobs/" + "f" * 32)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {"error": "not_found"})

    def test_database_failure_is_sanitized(self):
        self.authenticated()
        with patch("wecom_kf.admin.run_in_threadpool", new=AsyncMock(side_effect=RuntimeError("password token payload"))):
            response = self.client.get("/admin/api/jobs")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"error": "data_unavailable"})
        self.assertNotIn("password", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_failed_jobs_response_excludes_exception_fields(self):
        self.authenticated()
        self.store.transaction.side_effect = RuntimeError("not used")
        response = self.client.get("/admin/api/jobs")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("payload", response.text)


if __name__ == "__main__":
    unittest.main()
