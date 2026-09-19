"""Independent, offline integration contract checks.

These checks inspect source/DDL and use no production credentials or network.
They intentionally complement (rather than replace) feature tests owned by the
implementation agents.
"""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from wecom_kf.store import DDL, Store
from wecom_kf.payments import Payments
from tests.test_payments import FakeStore, order


# The local development workspace keeps the related repositories next to
# ``wecom-kf``. CI checks them out below ``CROSS_PROJECT_ROOT`` instead, so
# keep the application root and dependency root independent of each other.
WECOM_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("CROSS_PROJECT_ROOT", Path(__file__).resolve().parents[2]))


def _external_file(relative_path: str, test_case: unittest.TestCase) -> Path:
    """Return an optional sibling-repository file or skip this contract test.

    The related repositories are private and are available in the maintained
    local workspace, but the default token on a public-repository workflow
    cannot read them. Skipping only the checks that require those repositories
    keeps the rest of the suite enforceable without hiding a missing file in a
    workspace where the dependency was expected to be present.
    """
    path = ROOT / relative_path
    if not path.is_file():
        test_case.skipTest(f"optional cross-project dependency is unavailable: {path}")
    return path


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
        expected = _external_file(
            "lazycampus-agent/deploy/host/agent-wecom-kf-views.sql", self
        ).read_text(encoding="utf-8")
        actual = _external_file(
            "server-gitops/config/agent-wecom-kf-views.sql", self
        ).read_text(encoding="utf-8")
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
        source = (WECOM_ROOT / "src/wecom_kf/payments.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == "enqueue"]
        self.assertTrue(calls, "payment completion must enqueue through Store")
        self.assertTrue(any(len(call.args) >= 5 for call in calls),
                        "solve enqueue must include row/state/kind/payload")

    def test_sql_views_do_not_grant_job_context_or_secret_columns(self):
        source = _external_file("lazycampus-agent/data_access/catalog.py", self).read_text(encoding="utf-8")
        self.assertIn('"wecom-kf"', source)
        # Existing agent catalogue must remain explicit and should not expose
        # credential-bearing binding columns while adding historical context.
        self.assertNotIn('password"', source)
        self.assertNotIn('token"', source)

    def test_admin_contract_fields_remain_redacted(self):
        source = (WECOM_ROOT / "src/wecom_kf/admin_queries.py").read_text(encoding="utf-8")
        self.assertIn('"progress"', source)
        self.assertIn('SAFE_PROGRESS', source)
        for secret in ("password", "token", "profile"):
            self.assertNotIn(f'"{secret}"', source)


if __name__ == "__main__":
    unittest.main()
