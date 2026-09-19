import unittest
import json
import sqlite3
from contextlib import contextmanager

from starlette.datastructures import QueryParams

from wecom_kf.admin_queries import AdminQueries, QueryValidationError, _progress, parse_job_filters


class SQLiteCursor:
    """Execute production SELECTs; only translate the driver's placeholders."""
    def __init__(self, connection, statements):
        self.cursor = connection.cursor()
        self.statements = statements

    def execute(self, sql, args=()):
        if not sql.lstrip().upper().startswith("SELECT "):
            raise AssertionError("Admin query attempted a write")
        self.statements.append((sql, args))
        self.cursor.execute(sql.replace("%s", "?"), args)

    def fetchall(self):
        return [dict(row) for row in self.cursor.fetchall()]

    def fetchone(self):
        row = self.cursor.fetchone()
        return dict(row) if row else None


class SQLiteStore:
    """Isolated SQL fixture: no production credentials or MySQL connection."""
    def __init__(self):
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.statements = []
        self.connection.executescript("""
            CREATE TABLE kf_jobs (id TEXT PRIMARY KEY,customer_id TEXT,kind TEXT,status TEXT,
                payload BLOB,result TEXT,created_at REAL,updated_at REAL);
            CREATE TABLE kf_bindings (customer_id TEXT PRIMARY KEY,account TEXT,service TEXT,
                login_no TEXT,password TEXT,profile TEXT,created_at REAL);
            CREATE TABLE kf_job_context (job_id TEXT PRIMARY KEY,service TEXT,account TEXT,
                login_no TEXT,created_at REAL);
            CREATE TABLE kf_customers (id TEXT PRIMARY KEY,external_userid TEXT);
            CREATE TABLE kf_workers (role TEXT PRIMARY KEY,heartbeat REAL);
            CREATE TABLE kf_outbox (status TEXT);
            CREATE TABLE kf_meta (name TEXT PRIMARY KEY,value TEXT);
        """)
        for index in range(1, 206):
            customer = f"{index:064x}"
            # Equal timestamps deliberately test the id tiebreaker.
            self.connection.execute("INSERT INTO kf_jobs VALUES (?,?,?,?,?,?,?,?)", (
                f"{index:032x}", customer, "solve" if index % 2 else "verify",
                "complete" if index % 3 else "failed", "payload-private",
                json.dumps({"passed_homeworks": 1, "total_homeworks": 2, "passed_units": 3,
                            "current": "已结束", "failures": ["未通过"], "final": False,
                            "password": "password-private", "token": "token-private",
                            "profile": {"secret": "profile-private"}}), 1000 + index // 10, 2000))
            self.connection.execute("INSERT INTO kf_bindings VALUES (?,?,?,?,?,?,?)", (
                customer, f"account-{index}", "educoder", f"login-{index}",
                "password-private", '{"token":"profile-private"}', index))
            self.connection.execute("INSERT INTO kf_customers VALUES (?,?)", (customer, f"wx-{index}"))
            self.connection.execute("INSERT INTO kf_job_context VALUES (?,?,?,?,?)", (
                f"{index:032x}", "educoder", f"account-{index}", f"login-{index}", index))
        self.connection.commit()

    @contextmanager
    def transaction(self):
        cursor = SQLiteCursor(self.connection, self.statements)
        try:
            yield cursor
        finally:
            cursor.cursor.close()

    def close(self):
        self.connection.close()

    def bindings_for_admin(self, query=""):
        with self.transaction() as cur:
            if query:
                cur.execute("SELECT b.customer_id,b.account,b.login_no,c.external_userid,b.created_at FROM kf_bindings b JOIN kf_customers c ON c.id=b.customer_id WHERE b.login_no=%s OR b.account=%s OR c.external_userid=%s ORDER BY b.created_at DESC LIMIT 50", (query, query, query))
            else:
                cur.execute("SELECT b.customer_id,b.account,b.login_no,c.external_userid,b.created_at FROM kf_bindings b JOIN kf_customers c ON c.id=b.customer_id ORDER BY b.created_at DESC LIMIT 50")
            return cur.fetchall()


class AdminQueryTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteStore()
        self.addCleanup(self.store.close)
        self.queries = AdminQueries(self.store)

    def test_205_jobs_are_accessible_without_duplicates(self):
        ids = []
        for page, expected_length in ((1, 100), (2, 100), (3, 5), (4, 0)):
            items, total = self.queries.jobs(parse_job_filters(QueryParams(f"page={page}&page_size=100")))
            self.assertEqual(total, 205)
            self.assertEqual(len(items), expected_length)
            ids.extend(item["id"] for item in items)
        self.assertEqual(len(set(ids)), 205)
        self.assertEqual(ids, [f"{index:032x}" for index in range(205, 0, -1)])

    def test_combined_filters_and_exact_identifiers(self):
        for query in (f"{205:032x}", f"{205:064x}", "account-205", "login-205", "wx-205"):
            params = QueryParams({"q": query, "kind": "solve", "status": "complete", "from": "1020", "to": "1020"})
            items, total = self.queries.jobs(parse_job_filters(params))
            self.assertEqual(total, 1)
            self.assertEqual(items[0]["id"], f"{205:032x}")
        items, total = self.queries.jobs(parse_job_filters(QueryParams({"q": "' OR 1=1 --"})))
        self.assertEqual((items, total), ([], 0))
        self.assertTrue(all("' OR 1=1 --" not in sql for sql, _ in self.store.statements))

    def test_job_projection_preserves_terminal_status_without_secrets(self):
        job = self.queries.job(f"{205:032x}")
        self.assertEqual(set(job), {"id", "customer_id", "kind", "status", "created_at", "updated_at", "account", "service", "progress"})
        self.assertEqual(job["status"], "complete")
        self.assertEqual(job["progress"]["failures"], ["未通过"])
        self.assertIsNone(job["progress"]["total_challenges"])
        self.assertNotIn("private", json.dumps(job))
        self.assertIsNone(self.queries.job(f"{204:032x}")["progress"])
        self.assertIsNone(self.queries.job("f" * 32))

    def test_bindings_limit_exact_search_and_safe_projection(self):
        self.assertEqual(len(self.queries.bindings("")), 50)
        self.assertEqual(len(self.queries.bindings("login-205")), 1)
        self.assertEqual(self.queries.bindings("login-"), [])
        self.assertNotIn("private", json.dumps(self.queries.bindings("")))

    def test_task_attribution_survives_rebinding_and_unbinding(self):
        customer, job_id = f"{205:064x}", f"{205:032x}"
        self.store.connection.execute("UPDATE kf_bindings SET account='replacement',service='another' WHERE customer_id=?", (customer,))
        self.assertEqual(self.queries.job(job_id)["account"], "account-205")
        self.assertEqual(self.queries.job(job_id)["service"], "educoder")
        self.assertEqual(self.queries.jobs(parse_job_filters(QueryParams("q=replacement")))[1], 0)
        self.store.connection.execute("DELETE FROM kf_bindings WHERE customer_id=?", (customer,))
        self.assertEqual(self.queries.jobs(parse_job_filters(QueryParams("q=login-205")))[1], 1)
        self.assertEqual(self.queries.job(job_id)["account"], "account-205")

    def test_legacy_task_does_not_claim_current_binding(self):
        job_id = f"{205:032x}"
        self.store.connection.execute("DELETE FROM kf_job_context WHERE job_id=?", (job_id,))
        job = self.queries.job(job_id)
        self.assertIsNone(job["account"])
        self.assertIsNone(job["service"])
        self.assertEqual(self.queries.jobs(parse_job_filters(QueryParams("q=account-205")))[1], 0)
        self.assertEqual(self.queries.jobs(parse_job_filters(QueryParams("q=wx-205")))[1], 1)

    def test_invalid_filters_fail_before_sql(self):
        invalid = ["kind=nope", "status=queued", "page=0", "page=-1", "page=1000001",
                   "page=1.0", "page_size=30", "page=" + "9" * 5000, "from=nan",
                   "from=-1", "to=253402300800", "from=2&to=1", "to=2&to=3", "extra=1"]
        for query in invalid:
            with self.subTest(query=query[:80]), self.assertRaises(QueryValidationError):
                parse_job_filters(QueryParams(query))
        self.assertEqual(self.store.statements, [])

    def test_progress_counter_types_cannot_leak_nested_data(self):
        for bad in ({"password": "private"}, ["private"], "private", True, -1, 2147483648,
                    10 ** 400, float('inf'), float('nan')):
            value = _progress("solve", {"passed_homeworks": bad, "total_homeworks": bad,
                                        "passed_units": bad, "total_challenges": bad,
                                        "current": {"token": "private"}, "failures": [{"password": "private"}]})
            self.assertTrue(all(value[key] is None for key in ("passed_homeworks", "total_homeworks", "passed_challenges", "total_challenges")))
            self.assertNotIn("private", json.dumps(value))
        value = _progress("solve", {"passed_homeworks": 1.5, "total_homeworks": 2.0,
                                    "passed_units": 3.5, "total_challenges": 4.0})
        self.assertEqual(value["passed_challenges"], 3.5)

    def test_job_filters_reject_duplicates_and_oversized_queries(self):
        with self.assertRaises(QueryValidationError):
            parse_job_filters(QueryParams("page=1&page=2"))
        with self.assertRaises(QueryValidationError):
            parse_job_filters(QueryParams("q=" + "x" * 129))

    def test_progress_is_whitelisted_and_maps_units(self):
        value = _progress("solve", {"passed_homeworks": 1, "total_homeworks": 2,
                                    "passed_units": 3, "current": "working",
                                    "failures": ["bad"], "secret": "omit"})
        self.assertEqual(value["passed_challenges"], 3)
        self.assertNotIn("secret", value)
        self.assertEqual(set(value), {"passed_homeworks", "total_homeworks", "passed_challenges",
                                      "total_challenges", "passed_units", "total_units", "current_step",
                                      "total_steps", "current", "failures", "unknown", "has_error"})
