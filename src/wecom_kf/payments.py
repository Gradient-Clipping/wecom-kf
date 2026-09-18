"""Signed generic order integration; no account passwords cross this boundary."""
import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from . import dialog


class PaymentRejected(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def signature(secret, method, path, timestamp, nonce, body):
    digest = hashlib.sha256(canonical(body).encode()).hexdigest()
    return hmac.new(secret.encode(), "\n".join([method, path, timestamp, nonce, digest]).encode(), hashlib.sha256).hexdigest()


def business_day(now, timezone):
    return datetime.fromtimestamp(now, ZoneInfo(timezone)).date().isoformat()


def refundable(total, units, successful):
    if not 0 <= successful <= units or total != units * 50:
        raise ValueError("Invalid fulfillment accounting")
    return total if successful == 0 else max(0, total - max(100, successful * 50))


class PaymentClient:
    def __init__(self, settings):
        self.settings = settings

    def request(self, method, path, body=None):
        if not self.settings.payment_url.startswith("https://") or not self.settings.payment_secret:
            raise RuntimeError("Payment integration not configured")
        path = "/integration/v1" + path
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        headers = {"X-Platform-Code": self.settings.payment_platform, "X-Timestamp": timestamp,
                   "X-Nonce": nonce, "X-Signature": signature(self.settings.payment_secret, method, path, timestamp, nonce, body)}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = httpx.request(method, self.settings.payment_url.rstrip("/") + path,
                                     content=canonical(body).encode() if body is not None else None,
                                     headers=headers, timeout=15, follow_redirects=False)
            if response.status_code in {400, 403, 409}:
                raise PaymentRejected("订单暂不可创建，请核对选择或联系管理员。")
            response.raise_for_status()
            return response.json()["data"]
        except PaymentRejected:
            raise
        except Exception:
            raise RuntimeError("Payment service unavailable") from None


def waiting(state, order):
    checks = len(order.get("manual_checks", []))
    return dialog.menu(state, "等待付款\n\n完成支付后，再点击下方按钮查询结果。",
                       [("我已付款，查询到账", {"op": "payment_check", "order": order["order_id"], "code_version": order["code_version"]})],
                       f"{checks}/5")


class Payments:
    def __init__(self, worker):
        self.worker, self.store = worker, worker.store
        self.client = PaymentClient(worker.settings)
        self.last_poll = 0

    def create(self, job, binding, service=None):
        # The preassigned external number survives worker restarts and lost responses.
        items = job["payload"]["items"]
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM kf_purchases WHERE id=%s", (job["id"],))
            retained = cur.fetchone()
        if retained:
            snapshot = self.store.unpack(retained["snapshot"])
        else:
            adapter = service or self.worker.service
            snapshot = adapter.snapshot(binding, items)
            with self.store.transaction() as cur:
                cur.execute("INSERT IGNORE INTO kf_purchases (id,customer_id,snapshot,status,updated_at) VALUES (%s,%s,%s,'CREATING',%s)",
                            (job["id"], job["customer_id"], self.store.pack(snapshot), time.time()))
        adapter = service or self.worker.service
        service_items = adapter.billing_items(snapshot)
        order = self.client.request("POST", "/orders", {"platform_code": self.worker.settings.payment_platform,
            "external_order_no": job["id"], "customer_ref": job["customer_id"], "sku": "service_units",
            "selection_version": job["id"], "service_items": service_items})
        with self.store.transaction() as cur:
            cur.execute("UPDATE kf_purchases SET order_id=%s,document=%s,status='WAITING',updated_at=%s WHERE id=%s",
                        (order["order_id"], json.dumps(order), time.time(), job["id"]))
        return order

    def poll(self):
        if not self.worker.settings.payment_enabled or time.time() - self.last_poll < 5:
            return
        self.last_poll = time.time()
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM kf_purchases WHERE status IN ('CREATING','WAITING','RUNNING','SETTLING') ORDER BY updated_at LIMIT 10")
            purchases = cur.fetchall()
        for purchase in purchases:
            try:
                if purchase["status"] == "CREATING":
                    # Creation action owns retry; never invent a new external number.
                    continue
                if purchase["status"] in {"RUNNING", "SETTLING"}:
                    self.settle(purchase)
                    continue
                order = self.client.request("GET", "/orders/" + purchase["order_id"])
                self.observe(purchase["id"], order)
            except Exception:
                continue

    def manual(self, purchase_id, check_id):
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM kf_purchases WHERE id=%s", (purchase_id,))
            purchase = cur.fetchone()
        document = json.loads(purchase["document"]) if isinstance(purchase["document"], str) else purchase["document"]
        result = self.client.request("POST", f"/orders/{purchase['order_id']}/payment-checks", {
            "check_id": check_id, "code_version": document["code_version"],
            "revoke_if_unpaid": len(document.get("manual_checks", [])) >= 4})
        self.observe(purchase_id, result["order"], check_id=check_id, status=result["status"])

    def observe(self, purchase_id, order, *, check_id=None, status=None):
        store = self.store
        with store.transaction() as cur:
            cur.execute("SELECT * FROM kf_purchases WHERE id=%s FOR UPDATE", (purchase_id,))
            purchase = cur.fetchone()
            cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (purchase["customer_id"],))
            row = cur.fetchone(); state = store.unpack(row["state"])
            document = json.loads(purchase["document"]) if isinstance(purchase["document"], str) else purchase["document"]
            if order["order_version"] < document.get("order_version", 0):
                order = document
            replies = []
            if order["payment_status"] == "PAID":
                cur.execute("UPDATE kf_payment_penalties SET returned_at=%s WHERE purchase_id=%s AND returned_at IS NULL", (time.time(), purchase_id))
                fully_refunded = sum(r["amount_fen"] for r in order.get("refunds", []) if r["status"] == "SUCCEEDED") >= order["amount_fen"]
                if fully_refunded and not purchase["solve_job_id"]:
                    cur.execute("UPDATE kf_purchases SET status='REFUNDED' WHERE id=%s", (purchase_id,))
                    state.update(phase="idle", actions={})
                    replies = [dialog.text("此订单已全额退款，未启动服务。"), dialog.services(state)]
                elif not purchase["solve_job_id"]:
                    state.update(phase="running", purchase_id=purchase_id)
                    snapshot = store.unpack(purchase["snapshot"])
                    job_id = store.enqueue(cur, row, state, "solve", {"items": snapshot, "purchase_id": purchase_id})
                    cur.execute("UPDATE kf_purchases SET status='RUNNING',solve_job_id=%s WHERE id=%s", (job_id, purchase_id))
                    replies = [dialog.queued(state, paid=True)]
            elif check_id:
                checks = document.get("manual_checks", [])
                if check_id not in checks and status == "UNPAID" and (order["code_status"] == "ACTIVE" or (len(checks) == 4 and order["code_status"] == "REVOKED")):
                    checks.append(check_id)
                document["manual_checks"] = checks
                if len(checks) >= 5:
                    day = business_day(time.time(), self.worker.settings.payment_timezone)
                    cur.execute("INSERT IGNORE INTO kf_payment_penalties (purchase_id,customer_id,business_day) VALUES (%s,%s,%s)", (purchase_id, row["id"], day))
                    cur.execute("SELECT COUNT(*) AS n FROM kf_payment_penalties WHERE customer_id=%s AND business_day=%s AND returned_at IS NULL", (row["id"], day))
                    remaining = max(0, 3 - cur.fetchone()["n"])
                    document["revoke_pending"] = True
                    state["actions"] = {}
                    replies = [dialog.text(f"5次查款均未支付，订单码已停用。当天剩余{remaining}次机会；已有交易仍会继续核对。")]
                elif status == "UNPAID":
                    replies = [dialog.text(f"尚未付款，已检查{len(checks)}/5次。"),
                               waiting(state, {**order, "manual_checks": checks})]
                else:
                    replies = [dialog.text("支付结果待确认，请稍后重试。\n确认后将立刻开始任务。"),
                               waiting(state, {**order, "manual_checks": checks})]
            if (order["payment_status"] == "CLOSED" and not purchase["solve_job_id"]
                    and purchase["status"] != "CLOSED"):
                cur.execute("UPDATE kf_purchases SET status='CLOSED' WHERE id=%s", (purchase_id,))
                if state.get("purchase_id") == purchase_id:
                    state.update(phase="idle", actions={})
                    replies = [dialog.text("订单已超时，请重新选择服务。"), dialog.services(state)]
            document.update(order)
            cur.execute("UPDATE kf_purchases SET document=%s,updated_at=%s WHERE id=%s", (json.dumps(document), time.time(), purchase_id))
            if replies:
                store.reply(cur, row, state, replies)
            store.save_customer(cur, row, state)
        if document.get("revoke_pending") and order["payment_status"] != "PAID":
            self.client.request("POST", f"/orders/{order['order_id']}/code-revocations", {"reason": "MANUAL_CHECK_LIMIT", "code_version": order["code_version"]})

    def settle(self, purchase):
        with self.store.transaction() as cur:
            cur.execute("SELECT status,result FROM kf_jobs WHERE id=%s", (purchase["solve_job_id"],))
            job = cur.fetchone()
        if not job:
            return
        status = job["status"]
        data = json.loads(job["result"]) if isinstance(job["result"], str) else job["result"]
        base = "/orders/" + purchase["order_id"]
        if status in {"pending", "running"}:
            self.client.request("PUT", base + "/fulfillment", {"status": "QUEUED" if status == "pending" else "RUNNING", "version": 1 if status == "pending" else 2, "summary": "排队中" if status == "pending" else "执行中"})
            return
        # Interrupted or incomplete records cannot justify automatic financial settlement.
        if status == "interrupted" or not isinstance(data, dict) or not data.get("final"):
            self.client.request("PUT", base + "/fulfillment", {"status": "INTERRUPTED", "version": 3, "summary": "任务中断，待核对已完成关卡后退款。"})
            return
        document = json.loads(purchase["document"]) if isinstance(purchase["document"], str) else purchase["document"]
        successful = data["passed_units"]
        service_units = document.get("service_units", document["billable_units"])
        if not 0 <= successful <= service_units:
            raise ValueError("Invalid fulfillment accounting")
        amount = refundable(document["amount_fen"], document["billable_units"], successful)
        summary = f"已通过{successful}/{service_units}关"
        if amount > 0:
            summary += f"，待退¥{amount/100:.2f}"
        self.client.request("PUT", base + "/fulfillment", {"status": "SUCCEEDED" if successful == service_units else "PARTIAL" if successful else "FAILED", "version": 4, "summary": summary + "。"})
        if amount:
            refund = self.client.request("POST", base + "/refunds", {"external_refund_no": purchase["id"] + ":result", "amount_fen": amount, "reason": "未完成关卡退款"})
            if refund["status"] not in {"SUCCEEDED", "MANUAL_REQUIRED"}:
                with self.store.transaction() as cur:
                    cur.execute("UPDATE kf_purchases SET status='SETTLING',updated_at=%s WHERE id=%s", (time.time(), purchase["id"]))
                return
        with self.store.transaction() as cur:
            cur.execute("UPDATE kf_purchases SET status='COMPLETE',updated_at=%s WHERE id=%s", (time.time(), purchase["id"]))
