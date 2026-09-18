"""Exercise production enqueue SQL offline, including payment attribution."""
import json
import sqlite3
import unittest

from wecom_kf.store import Store


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def execute(self, sql, args=()):
        self.cursor.execute(sql.replace("%s", "?"), args)

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None


class JobContextTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE kf_jobs (id TEXT PRIMARY KEY,customer_id TEXT,kind TEXT,
                payload BLOB,created_at REAL,updated_at REAL,result TEXT);
            CREATE TABLE kf_job_context (job_id TEXT PRIMARY KEY,service TEXT,
                account TEXT,login_no TEXT,created_at REAL);
            CREATE TABLE kf_bindings (customer_id TEXT PRIMARY KEY,service TEXT,
                account TEXT,login_no TEXT,password TEXT,profile TEXT);
            INSERT INTO kf_bindings VALUES ('customer','educoder','original','login-old',
                'NEVER-EXPORT','NEVER-EXPORT');
        """)
        self.store = Store.__new__(Store)
        # Encryption itself is covered elsewhere; leave production SQL unchanged.
        self.store.pack = lambda payload: json.dumps(payload)
        self.cursor = Cursor(self.db)

    def enqueue(self, kind, payload=None, customer="customer"):
        return self.store.enqueue(self.cursor, {"id": customer}, {}, kind, payload or {})

    def context(self, job):
        return dict(self.db.execute("SELECT * FROM kf_job_context WHERE job_id=?", (job,)).fetchone())

    def test_binding_snapshot_remains_immutable(self):
        job = self.enqueue("list")
        self.db.execute("UPDATE kf_bindings SET account='replacement',login_no='login-new'")
        self.assertEqual(self.context(job)["account"], "original")
        self.assertEqual(self.context(job)["login_no"], "login-old")
        self.assertNotIn("NEVER-EXPORT", json.dumps(self.context(job)))

    def test_verification_snapshots_only_account(self):
        job = self.enqueue("verify", {"account": "candidate", "password": "NEVER-EXPORT"})
        context = self.context(job)
        self.assertEqual(context["account"], "candidate")
        self.assertEqual(context["service"], "educoder")
        self.assertIsNone(context["login_no"])
        self.assertNotIn("NEVER-EXPORT", json.dumps(context))

    def test_paid_solve_and_payment_check_inherit_purchase(self):
        purchase = self.enqueue("purchase")
        self.db.execute("UPDATE kf_bindings SET account='replacement',service='future'")
        for kind in ("solve", "payment_check"):
            job = self.enqueue(kind, {"purchase_id": purchase, "items": []})
            self.assertEqual(self.context(job)["account"], "original")
            self.assertEqual(self.context(job)["service"], "educoder")

    def test_missing_or_foreign_purchase_never_uses_current_binding(self):
        purchase = self.enqueue("purchase", customer="someone-else")
        for parent in ("legacy-order", purchase):
            job = self.enqueue("solve", {"purchase_id": parent, "items": []})
            self.assertIsNone(self.context(job)["account"])
            self.assertIsNone(self.context(job)["service"])

    def test_context_failure_rolls_back_job_transaction(self):
        self.db.execute("CREATE TRIGGER fail_context BEFORE INSERT ON kf_job_context BEGIN SELECT RAISE(ABORT, 'fixture failure'); END")
        self.db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.enqueue("list")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM kf_jobs").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
