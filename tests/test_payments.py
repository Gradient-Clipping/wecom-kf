import copy
import json
import threading
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from wecom_kf import dialog
from wecom_kf.educoder_service import EduCoderService
from wecom_kf.payments import Payments, business_day, refundable, signature, waiting
from wecom_kf.worker import wecom_pagepath


class FakeStore:
    def __init__(self):
        self.lock = threading.RLock()
        self.purchase = {"id": "purchase", "customer_id": "customer", "document": None,
                         "status": "WAITING", "solve_job_id": None, "snapshot": [{"title": "test"}]}
        self.row = {"id": "customer", "state": {"phase": "paying", "purchase_id": "purchase"}}
        self.penalties, self.jobs, self.replies = {}, [], []
        self.fetched = None

    @contextmanager
    def transaction(self):
        with self.lock:
            yield self

    def execute(self, sql, args=()):
        if sql.startswith("SELECT * FROM kf_purchases"):
            self.fetched = copy.deepcopy(self.purchase)
        elif sql.startswith("SELECT * FROM kf_customers"):
            self.fetched = copy.deepcopy(self.row)
        elif sql.startswith("UPDATE kf_payment_penalties"):
            if args[1] in self.penalties:
                self.penalties[args[1]]["returned_at"] = args[0]
        elif sql.startswith("INSERT IGNORE INTO kf_payment_penalties"):
            self.penalties.setdefault(args[0], {"day": args[2], "returned_at": None})
        elif sql.startswith("SELECT COUNT(*)"):
            self.fetched = {"n": sum(p["day"] == args[1] and p["returned_at"] is None for p in self.penalties.values())}
        elif "status='RUNNING'" in sql:
            self.purchase.update(status="RUNNING", solve_job_id=args[0])
        elif "status='CLOSED'" in sql:
            self.purchase["status"] = "CLOSED"
        elif sql.startswith("UPDATE kf_purchases SET order_id"):
            self.purchase.update(order_id=args[0], document=json.loads(args[1]), status="WAITING")
        elif sql.startswith("UPDATE kf_purchases SET document"):
            self.purchase["document"] = json.loads(args[0])
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self.fetched

    def unpack(self, value):
        return copy.deepcopy(value)

    def enqueue(self, cur, row, state, kind, payload):
        self.jobs.append(payload)
        state["job_id"] = "solve"
        return "solve"

    def reply(self, cur, row, state, replies):
        self.replies.extend(replies)

    def save_customer(self, cur, row, state):
        self.row["state"] = copy.deepcopy(state)


def order(**changes):
    return {"order_id": "order", "order_version": 1, "code_version": 1,
            "code_status": "ACTIVE", "payment_status": "UNPAID", "amount_fen": 500, **changes}


class PaymentTests(unittest.TestCase):
    def test_charge_items_group_by_homework_without_leaking_challenges(self):
        snapshot = [
            {"course_identifier": "course", "homework_id": "1", "title": "实训一", "challenges": [{"challenge_id": 1}, {"challenge_id": 2}]},
            {"course_identifier": "course", "homework_id": "2", "title": "实训二", "challenges": [{"challenge_id": 3}, {"challenge_id": 4}, {"challenge_id": 5}]},
            {"course_identifier": "course", "homework_id": "3", "title": "已完成", "challenges": []},
        ]
        original = copy.deepcopy(snapshot)
        self.assertEqual(EduCoderService.billing_items(snapshot), [
            {"id": "course:1", "name": "实训一", "quantity": 2, "billing_attributes": {"kind": "unit"}},
            {"id": "course:2", "name": "实训二", "quantity": 3, "billing_attributes": {"kind": "unit"}},
        ])
        self.assertEqual(snapshot, original)
        with self.assertRaises(ValueError):
            EduCoderService.billing_items([snapshot[0], snapshot[0]])
        snapshot[0]["challenges"].append({"challenge_id": 1})
        with self.assertRaises(ValueError):
            EduCoderService.billing_items(snapshot)

    def test_one_charge_item_with_two_units_is_payable_and_retries_keep_snapshot(self):
        payments, store = self.setup_payment()
        store.purchase["snapshot"] = [{"course_identifier": "course", "homework_id": "1", "title": "实训",
                                       "challenges": [{"challenge_id": 1}, {"challenge_id": 2}]}]
        payments.worker.service = SimpleNamespace(billing_items=EduCoderService.billing_items)
        payments.worker.settings.payment_platform = "educoder"
        requests = []
        def request(method, path, body):
            requests.append(copy.deepcopy(body))
            return order(service_items=body["service_items"], billable_units=2, amount_fen=100)
        payments.client = SimpleNamespace(request=request)
        job = {"id": "purchase", "customer_id": "customer", "payload": {"items": []}}
        for _ in range(2):
            result = payments.create(job, {"password": "must-not-leave-adapter"})
            self.assertEqual(len(result["service_items"]), 1)
            self.assertEqual(result["service_items"][0]["quantity"], 2)
        self.assertEqual(requests[0], requests[1])
        self.assertNotIn("password", json.dumps(requests))
        self.assertNotIn("challenge_id", json.dumps(requests))
        store.purchase["snapshot"][0]["challenges"].pop()
        with self.assertRaises(ValueError):
            payments.create(job, {})
        self.assertEqual(len(requests), 2)

    def setup_payment(self):
        store = FakeStore()
        store.purchase["document"] = order()
        worker = SimpleNamespace(store=store, settings=SimpleNamespace(payment_timezone="Asia/Shanghai"))
        payments = Payments(worker)
        payments.client = SimpleNamespace(request=lambda *args: None)
        return payments, store

    def test_minimum_retention_and_full_failure(self):
        self.assertEqual(refundable(500, 10, 0), 500)
        self.assertEqual(refundable(500, 10, 1), 400)
        self.assertEqual(refundable(500, 10, 3), 350)
        self.assertEqual(refundable(100, 2, 1), 0)

    def test_business_timezone_midnight(self):
        self.assertEqual(business_day(0, "Asia/Shanghai"), "1970-01-01")
        self.assertEqual(business_day(0, "America/New_York"), "1969-12-31")

    def test_pending_message_keeps_newline_and_does_not_count_check(self):
        payments, store = self.setup_payment()
        payments.observe("purchase", order(), check_id="pending", status="PROCESSING")
        self.assertEqual(store.replies[0], dialog.text("支付结果待确认，请稍后重试。\n确认后将立刻开始任务。"))
        self.assertEqual(store.purchase["document"].get("manual_checks", []), [])

    def test_zero_refund_is_omitted_from_fulfillment_summary(self):
        for units, successful, expected in [(2, 2, "已通过2/2关。"), (2, 1, "已通过1/2关。"),
                                             (3, 2, "已通过2/3关，待退¥0.50。")]:
            with self.subTest(units=units, successful=successful):
                payments, store = self.setup_payment()
                payments.client = MagicMock()
                payments.client.request.return_value = {"status": "SUCCEEDED"}
                purchase = {"id": "purchase", "order_id": "order", "solve_job_id": "solve",
                            "document": {"amount_fen": units * 50, "billable_units": units}}
                with patch.object(store, "transaction") as transaction:
                    cur = transaction.return_value.__enter__.return_value
                    cur.fetchone.return_value = {"status": "complete", "result": {"final": True, "passed_units": successful}}
                    payments.settle(purchase)
                calls = payments.client.request.call_args_list
                self.assertEqual(calls[0].args[2]["summary"], expected)
                self.assertEqual(len(calls), 2 if units == 3 else 1)

    def test_error_processing_duplicate_and_auto_checks_do_not_count(self):
        payments, store = self.setup_payment()
        for status in ("UNKNOWN", "PROCESSING", "CLOSED"):
            payments.observe("purchase", order(), check_id=status, status=status)
        payments.observe("purchase", order())
        self.assertEqual(store.purchase["document"].get("manual_checks", []), [])
        payments.observe("purchase", order(), check_id="one", status="UNPAID")
        self.assertEqual(store.replies[-1]["msgmenu"]["tail_content"], "1/5")
        payments.observe("purchase", order(), check_id="one", status="UNPAID")
        self.assertEqual(store.purchase["document"]["manual_checks"], ["one"])
        self.assertEqual(store.replies[-1]["msgmenu"]["tail_content"], "1/5")
        payments.observe("purchase", order(), check_id="two", status="UNPAID")
        self.assertEqual(store.replies[-1]["msgmenu"]["tail_content"], "2/5")
        payments.observe("purchase", order(), check_id="pending", status="UNKNOWN")
        self.assertEqual(store.replies[-1]["msgmenu"]["tail_content"], "2/5")

    def test_closed_order_notifies_once_then_shows_service_menu(self):
        for manual in (False, True):
            with self.subTest(manual=manual):
                payments, store = self.setup_payment()
                store.row["state"]["available_services"] = [{"code": "educoder", "name": "头歌", "enabled": True}]
                payments.observe("purchase", order(code_status="EXPIRED", payment_status="CLOSED", order_version=2),
                                 check_id="check" if manual else None, status="CLOSED" if manual else None)
                self.assertEqual(store.replies[0]["text"]["content"], "订单已超时，请重新选择服务。")
                self.assertEqual(store.replies[1]["msgmenu"]["head_content"], "请选择服务：")
                self.assertEqual(store.row["state"]["phase"], "idle")
                payments.observe("purchase", order(code_status="EXPIRED", payment_status="CLOSED", order_version=2))
                self.assertEqual(len(store.replies), 2)

    def test_five_failures_debit_once_and_late_payment_returns_original_day(self):
        payments, store = self.setup_payment()
        with patch("wecom_kf.payments.time.time", return_value=0):
            for n in range(5):
                payments.observe("purchase", order(code_status="REVOKED" if n == 4 else "ACTIVE"), check_id=str(n), status="UNPAID")
        self.assertEqual(len(store.penalties), 1)
        self.assertEqual(store.penalties["purchase"]["day"], "1970-01-01")
        with patch("wecom_kf.payments.time.time", return_value=86401):
            payments.observe("purchase", order(payment_status="PAID", order_version=2))
            payments.observe("purchase", order(payment_status="PAID", order_version=2))
        self.assertEqual(store.penalties["purchase"]["returned_at"], 86401)
        self.assertEqual(len(store.jobs), 1)

    def test_payment_wins_over_stale_unpaid_result(self):
        payments, store = self.setup_payment()
        payments.observe("purchase", order(payment_status="PAID", order_version=10))
        payments.observe("purchase", order(), check_id="old", status="UNPAID")
        self.assertEqual(len(store.jobs), 1)
        self.assertEqual(len(store.penalties), 0)

    def test_pending_payment_ignores_chat_timeout_and_running_has_progress(self):
        state = {"phase": "paying", "expires_at": 1}
        dialog.advance(state, True, "hello", now=100000, payment_enabled=True)
        self.assertEqual(state["phase"], "paying")
        state = {"phase": "running"}
        message = dialog.queued(state)
        key = message["msgmenu"]["list"][0]["click"]["id"]
        self.assertEqual(dialog.advance(state, True, "", key)[1], "progress")

    def test_waiting_shows_compact_check_count(self):
        state = {}
        order = {"order_id": "order", "code_version": 1, "manual_checks": []}
        self.assertEqual(waiting(state, order)["msgmenu"]["tail_content"], "0/5")
        order["manual_checks"] = ["a", "b"]
        self.assertEqual(waiting(state, order)["msgmenu"]["tail_content"], "2/5")

    def test_wecom_miniprogram_pagepath_keeps_order_code(self):
        self.assertEqual(
            wecom_pagepath("features/pages/service-order/index?code=Ab_12-3"),
            "features/pages/service-order/index.html?code=Ab_12-3",
        )
        self.assertEqual(wecom_pagepath("pages/index.html?code=x"), "pages/index.html?code=x")
        with self.assertRaises(ValueError):
            wecom_pagepath("https://example.com/pages/index")

    def test_signature_matches_node_canonical_wire_format(self):
        self.assertEqual(signature("key", "POST", "/orders", "1", "nonce", {"b": 2, "a": 1}),
                         signature("key", "POST", "/orders", "1", "nonce", {"a": 1, "b": 2}))
        self.assertNotEqual(signature("key", "POST", "/orders", "1", "nonce", {}),
                            signature("key", "GET", "/orders", "1", "nonce", {}))
