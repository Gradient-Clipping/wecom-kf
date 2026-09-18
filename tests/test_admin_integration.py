"""HTTP-level acceptance against production routes and isolated SELECT fixture."""
import base64
import json
import time
import unittest

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from tests.admin_preview import create_preview


class AdminIntegrationTests(unittest.TestCase):
    def setUp(self):
        app = create_preview()
        self.addCleanup(app.state.fixture_store.close)
        self.client = TestClient(app, base_url="https://localhost:8766")
        self.addCleanup(self.client.close)
        self.assertEqual(self.client.get('/admin/auth/callback', follow_redirects=False).status_code, 303)

    def test_successful_endpoints_have_safe_schema_and_all_pages(self):
        overview = self.client.get('/admin/api/overview')
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(sum(item['count'] for item in overview.json()['counts']), 205)
        ids = []
        for page in range(1, 4):
            response = self.client.get(f'/admin/api/jobs?page_size=100&page={page}')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertNotIn('private', response.text)
            data = response.json()
            self.assertEqual((data['total'], data['pages']), (205, 3))
            for item in data['items']:
                self.assertEqual(set(item), {'id','customer_id','kind','status','created_at','updated_at','account','service','progress'})
                ids.append(item['id'])
        self.assertEqual(len(set(ids)), 205)
        detail = self.client.get('/admin/api/jobs/' + ids[0])
        self.assertEqual(detail.status_code, 200)
        self.assertNotIn('private', detail.text)
        self.assertEqual(detail.json()['job']['progress']['failures'], ['未通过'])
        bindings = self.client.get('/admin/api/bindings?q=login-205')
        self.assertEqual(bindings.status_code, 200)
        self.assertEqual(len(bindings.json()['items']), 1)
        self.assertNotIn('private', bindings.text)

    def test_expired_signed_cookie_is_rejected_and_cleared(self):
        self.client.cookies.clear()
        session = {'admin': {'name': 'expired', 'until': time.time() - 1}}
        cookie = TimestampSigner('preview-only-' * 6).sign(base64.b64encode(json.dumps(session).encode())).decode()
        self.client.cookies.set('__Host-kf-admin', cookie)
        response = self.client.get('/admin/api/overview')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'error': 'session_expired'})
        self.assertIn('expires=Thu, 01 Jan 1970', response.headers['set-cookie'])

    def test_invalid_detail_and_bindings_queries(self):
        for path in ('/admin/api/jobs/not-an-id', '/admin/api/bindings?q=a&q=b', '/admin/api/bindings?x=1'):
            self.assertEqual(self.client.get(path).status_code, 400)
        self.assertEqual(self.client.get('/admin/api/jobs/' + 'f' * 32).status_code, 404)
