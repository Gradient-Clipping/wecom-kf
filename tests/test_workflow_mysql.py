"""Real MySQL transactions with fake external services: never submit real work."""
import hashlib
import os
import time
import unittest
import uuid
from dataclasses import replace
from unittest.mock import Mock

from cryptography.fernet import Fernet

from wecom_kf.config import Settings
from wecom_kf.educoder_service import InvalidCredentials
from wecom_kf.store import Store
from wecom_kf.worker import Worker
from wecom_kf import dialog


@unittest.skipUnless(os.getenv("TEST_MYSQL") == "1", "Requires isolated integration-test MySQL")
class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = replace(Settings.from_env(), corp_id="testcorp", token="testtoken",
                               aes_key="a" * 43, api_secret="fake", data_key=Fernet.generate_key().decode(),
                               open_kfid="testkf", processing_enabled=True, execution_enabled=True)
        assert cls.settings.mysql_database.endswith("_test")
        cls.store = Store(cls.settings)
        cls.store.initialize()

    def setUp(self):
        with self.store.transaction() as cur:
            for table in ("kf_customers", "kf_bindings", "kf_jobs", "kf_messages", "kf_outbox", "kf_cursors"):
                cur.execute(f"DELETE FROM {table}")
        self.api, self.service = Mock(), Mock()
        self.worker = Worker(self.settings, self.store, self.api, self.service)
        self.service.verify.return_value = {"login": "loginno", "username": "user", "phone": "138****1234"}
        self.service.list_homeworks.return_value = [
            {"title": f"实训{i}", "course_name": "课堂", "homework_id": str(i), "course_identifier": "c"} for i in range(20)]
        self.service.solve.return_value = [{"title": "实训1", "ok": True}]

    def state(self, user="customer"):
        with self.store.transaction() as cur:
            cur.execute("SELECT state FROM kf_customers WHERE id=%s", (self.store.customer_id(user),))
            return self.store.unpack(cur.fetchone()["state"])

    def click(self, op):
        return next(k for k,v in self.state()["actions"].items() if v["op"] == op)

    def send(self, content, menu_id="", mid=None, user="customer"):
        mid = mid or uuid.uuid4().hex
        message = {"msgid": mid, "origin": 3, "send_time": time.time(), "open_kfid": "testkf",
                   "external_userid": user, "msgtype": "text", "text": {"content": content, "menu_id": menu_id}}
        with self.store.transaction() as cur:
            cur.execute("INSERT IGNORE INTO kf_messages (id,open_kfid,payload,created_at) VALUES (%s,%s,%s,%s)",
                        (mid, "testkf", self.store.pack(message), time.time()))
        self.worker.message()
        return mid

    def bind(self):
        self.send("hello")
        self.send("头歌", self.click("educoder"))
        self.send("account")
        self.send(" passＡ word ")
        self.worker.action()
        self.send("确认绑定", self.click("bind"))
        self.worker.action()

    def test_full_flow_plaintext_confirmed_only_and_no_duplicate_submission(self):
        self.bind()
        with self.store.transaction() as cur:
            binding = self.store.binding(cur, self.store.customer_id("customer"))
            self.assertEqual(binding["password"], " passＡ word ")
            cur.execute("SELECT payload FROM kf_messages")
            self.assertTrue(all(r["payload"] is None for r in cur.fetchall()))
        self.send("１、２")
        stale = self.click("run")
        self.send("３")
        self.send("确认", stale)
        self.assertEqual(self.state()["phase"], "confirm")
        self.service.solve.assert_not_called()
        mid = self.send("确认", self.click("run"))
        self.send("确认", stale, mid=mid)
        self.worker.action(execute=True)
        self.worker.action(execute=True)
        self.service.solve.assert_called_once()
        self.assertEqual(self.service.solve.call_args.args[1][0]["homework_id"], "2")
        self.assertEqual(self.state()["phase"], "idle")

    def test_expiration_cancels_verification_and_erases_pending_password(self):
        self.send("头歌")
        self.send("account")
        self.send("secret")
        with self.store.transaction() as cur:
            row, state = self.store.customer(cur, "customer", "testkf")
            state["expires_at"] = time.time() - 1
            self.store.save_customer(cur, row, state)
        self.worker.action()
        self.service.verify.assert_not_called()
        self.send("anything")
        self.assertEqual(self.state()["phase"], "idle")
        self.assertNotIn("pending", self.state())

    def test_failure_limit_survives_worker_restart_and_isolates_users(self):
        self.service.verify.side_effect = InvalidCredentials()
        self.send("头歌")
        for _ in range(3):
            self.send("account")
            self.send("wrong")
            self.worker.action()
        self.assertGreater(self.state()["blocked_until"], time.time() + 86000)
        self.worker = Worker(self.settings, self.store, self.api, self.service)
        self.send("头歌")
        self.assertEqual(self.state()["failures"], 3)
        self.send("头歌", user="another")
        self.assertEqual(self.state("another")["phase"], "account")

    def test_restart_interrupts_running_job_instead_of_replaying(self):
        self.bind()
        self.send("1")
        self.send("确认", self.click("run"))
        self.store.claim(("solve",))
        self.worker.recover("executor")
        self.worker.action(execute=True)
        self.service.solve.assert_not_called()
        self.assertEqual(self.state()["phase"], "idle")

    def test_outbox_budget_and_ambiguous_send_not_retried(self):
        from wecom_kf.wecom import WeComError
        for _ in range(7):
            self.send("hello")
        for _ in range(8):
            self.worker.outbox()
        self.assertEqual(self.api.send.call_count, 5)
        self.send("hello")
        self.api.send.side_effect = WeComError("timeout", uncertain=True)
        self.worker.outbox()
        before = self.api.send.call_count
        self.worker.outbox()
        self.assertEqual(self.api.send.call_count, before)

    def test_sync_empty_page_with_has_more_and_durable_dedup(self):
        self.api.sync.side_effect = [
            {"next_cursor": "first", "has_more": 1, "msg_list": []},
            {"next_cursor": "second", "has_more": 0, "msg_list": []}]
        self.worker.sync()
        self.assertEqual(self.api.sync.call_count, 2)
        with self.store.transaction() as cur:
            cur.execute("SELECT cursor_value FROM kf_cursors WHERE open_kfid='testkf'")
            self.assertEqual(cur.fetchone()["cursor_value"], "second")

    def test_welcome_uses_event_endpoint_payload(self):
        message = {"msgid": "welcome", "origin": 4, "send_time": time.time(), "msgtype": "event",
                   "event": {"event_type": "enter_session", "open_kfid": "testkf", "external_userid": "customer", "welcome_code": "once"}}
        with self.store.transaction() as cur:
            cur.execute("INSERT INTO kf_messages (id,open_kfid,payload,created_at) VALUES ('welcome','testkf',%s,%s)",
                        (self.store.pack(message), time.time()))
        self.worker.message()
        self.worker.outbox()
        payload = self.api.send.call_args.args[0]
        self.assertEqual(payload["code"], "once")
        self.assertNotIn("touser", payload)
        self.assertEqual(payload["msgtype"], "msgmenu")

    def test_cleanup_keeps_active_execution(self):
        self.bind()
        self.send("0")
        self.send("确认", self.click("run"))
        with self.store.transaction() as cur:
            cur.execute("UPDATE kf_customers SET updated_at=%s", (time.time() - 600,))
        self.worker.cleanup()
        self.assertEqual(self.state()["phase"], "running")
        self.assertIsNotNone(self.store.claim(("solve",)))
