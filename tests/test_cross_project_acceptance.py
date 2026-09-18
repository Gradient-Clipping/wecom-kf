"""Independent, offline integration contract checks.

These checks inspect source/DDL and use no production credentials or network.
They intentionally complement (rather than replace) feature tests owned by the
implementation agents.
"""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from wecom_kf.store import DDL, Store
from wecom_kf.payments import Payments
from tests.test_payments import FakeStore, order


ROOT = Path(__file__).resolve().parents[2]


class PaymentContextStore(FakeStore):
    """Use production enqueue/context with the payment test's isolated store."""
    enqueue = Store.enqueue
    _job_context = Store._job_context

    def __init__(self, context):
        super().__init__()
        self.context = context
        self.contexts = []
        self.purchase["document"] = order()

    def pack(self, value):
        return json.dumps(value).encode()

    def execute(self, sql, args=()):
        if sql.startswith("SELECT x.service"):
            assert args == ("purchase", "customer")
            self.fetched = self.context
        elif sql.startswith("INSERT INTO kf_jobs"):
            self.jobs.append(args)
        elif sql.startswith("INSERT INTO kf_job_context"):
            self.contexts.append(args)
        elif sql.startswith("UPDATE kf_jobs SET result"):
            pass
        elif "FROM kf_bindings" in sql:
            raise AssertionError("Payment history must not fall back to current binding")
        else:
            super().execute(sql, args)


class CrossProjectAcceptanceTests(unittest.TestCase):
    def test_paid_order_enqueues_once_with_original_context_or_explicit_unknown(self):
        for context in (None, {"service": "educoder", "account": "original", "login_no": "old-login"}):
            with self.subTest(context=context):
                store = PaymentContextStore(context)
                payments = Payments(SimpleNamespace(store=store, settings=SimpleNamespace(payment_timezone="Asia/Shanghai")))
                payments.observe("purchase", order(payment_status="PAID"))
                payments.observe("purchase", order(payment_status="PAID"))
                self.assertEqual(len(store.jobs), 1)
                self.assertEqual(len(store.contexts), 1)
                expected = context or {}
                self.assertEqual(store.contexts[0][1:4], tuple(expected.get(k) for k in ("service", "account", "login_no")))
                self.assertEqual(store.purchase["solve_job_id"], store.jobs[0][0])
                self.assertEqual(json.loads(store.jobs[0][3])["purchase_id"], "purchase")

    def test_verification_snapshot_excludes_payload_secrets(self):
        cursor = Mock()
        result = Store._job_context(object(), cursor, "customer", "verify", {
            "account": "target", "password": "secret-password", "profile": {"token": "secret-token"}})
        self.assertEqual(result, {"service": "educoder", "account": "target"})
        cursor.execute.assert_not_called()

    def test_published_sql_templates_agree(self):
        expected = (ROOT / "lazycampus-agent/deploy/host/agent-wecom-kf-views.sql").read_text(encoding="utf-8")
        actual = (ROOT / "server-gitops/config/agent-wecom-kf-views.sql").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)
        self.assertIn("`agent_job_context`", expected)
        for secret in ("`password`", "`payload`", "`profile`", "`token`"):
            self.assertNotIn(secret, expected)

    def test_job_context_is_immutable_non_secret_schema(self):
        ddl = "\n".join(DDL).lower()
        self.assertIn("create table if not exists kf_job_context", ddl)
        start = ddl.index("create table if not exists kf_job_context")
        section = ddl[start: ddl.find(") engine", start)]
        for field in ("job_id", "service", "account", "login_no", "created_at"):
            self.assertIn(field, section)
        for secret in ("password", "token", "profile", "payload", "secret"):
            self.assertNotIn(secret, section)

    def test_payment_solve_path_still_uses_store_enqueue(self):
        source = (ROOT / "wecom-kf/src/wecom_kf/payments.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "enqueue"]
        self.assertTrue(calls, "payment completion must enqueue through Store")
        self.assertTrue(any(len(call.args) >= 5 for call in calls),
                        "solve enqueue must include row/state/kind/payload")

    def test_sql_views_do_not_grant_job_context_or_secret_columns(self):
        source = (ROOT / "lazycampus-agent/data_access/catalog.py").read_text(encoding="utf-8")
        self.assertIn('"wecom-kf"', source)
        # Existing agent catalogue must remain explicit and should not expose
        # credential-bearing binding columns while adding historical context.
        self.assertNotIn('password"', source)
        self.assertNotIn('token"', source)

    def test_admin_contract_fields_remain_redacted(self):
        source = (ROOT / "wecom-kf/src/wecom_kf/admin_queries.py").read_text(encoding="utf-8")
        self.assertIn('"progress"', source)
        self.assertIn('SAFE_PROGRESS', source)
        for secret in ("password", "token", "profile"):
            self.assertNotIn(f'"{secret}"', source)


if __name__ == "__main__":
    unittest.main()
