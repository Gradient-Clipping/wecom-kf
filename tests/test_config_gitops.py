"""Public OIDC settings supplied by the existing GitOps ConfigMap."""

import os
import unittest
from unittest.mock import patch

from wecom_kf.config import Settings


class PublicOidcSettingsTests(unittest.TestCase):
    def settings(self, **env):
        with patch.dict(os.environ, env, clear=True):
            return Settings.from_env()

    def test_missing_env_preserves_production_defaults(self):
        settings = self.settings()
        self.assertEqual(settings.oidc_issuer, "https://auth.lazycampus.com/realms/lazycampus")
        self.assertEqual(settings.oidc_client_id, "lazycampus-wecom-kf")
        self.assertEqual(settings.public_base_url, "https://kf.lazycampus.com")

    def test_env_overrides_are_normalized_for_discovery_and_redirect(self):
        settings = self.settings(OIDC_ISSUER=" https://auth.test/realms/test/ ",
                                 OIDC_CLIENT_ID=" test-admin ",
                                 PUBLIC_BASE_URL=" https://admin.test:8443/ ")
        self.assertEqual(settings.oidc_issuer + "/.well-known/openid-configuration",
                         "https://auth.test/realms/test/.well-known/openid-configuration")
        self.assertEqual(settings.oidc_client_id, "test-admin")
        self.assertEqual(settings.public_base_url + "/admin/auth/callback",
                         "https://admin.test:8443/admin/auth/callback")

    def test_http_origin_remains_available_for_isolated_tests(self):
        self.assertEqual(self.settings(PUBLIC_BASE_URL="http://127.0.0.1:8000/").public_base_url,
                         "http://127.0.0.1:8000")

    def test_invalid_urls_fail_without_echoing_the_value(self):
        invalid = ("", "relative", "ftp://example.test", "https://user:private@example.test",
                   "https://example.test?token=private", "https://example.test#private",
                   "https://example.test:bad", "https://bad host.test", "https://[broken",
                   "https://example.test/\nprivate", "https://example.test\\private")
        for key in ("OIDC_ISSUER", "PUBLIC_BASE_URL"):
            for value in invalid:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError) as error:
                    self.settings(**{key: value})
                self.assertIn(key, str(error.exception))
                self.assertNotIn("private", str(error.exception))

    def test_public_base_must_be_origin_but_issuer_can_have_realm_path(self):
        with self.assertRaises(ValueError):
            self.settings(PUBLIC_BASE_URL="https://example.test/subpath")
        self.assertEqual(self.settings(OIDC_ISSUER="https://example.test/realms/test").oidc_issuer,
                         "https://example.test/realms/test")

    def test_explicit_empty_or_whitespace_client_id_is_rejected(self):
        for value in ("", "  ", "two clients", "client\nname"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.settings(OIDC_CLIENT_ID=value)

    def test_secrets_remain_excluded_from_repr(self):
        settings = self.settings(OIDC_CLIENT_SECRET="private-oidc", ADMIN_SESSION_SECRET="private-session")
        self.assertNotIn("private-oidc", repr(settings))
        self.assertNotIn("private-session", repr(settings))
