"""Durable chat gateway and isolated action/execution workers.

Run one process per role. Deployment uses Recreate; database advisory locks also
prevent overlapping owners. In-flight submissions are never replayed on restart.
"""

import hashlib
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

from . import dialog
from .config import Settings
from .crypto import CallbackCrypto, parse_xml, xml_field
from .educoder_service import EduCoderService, InvalidCredentials
from .store import Store
from .wecom import WeCom, WeComError

log = logging.getLogger("wecom_kf.worker")


class Worker:
    def __init__(self, settings, store=None, api=None, service=None):
        self.settings = settings
        self.store = store or Store(settings)
        self.api = api or WeCom(settings)
        self.service = service or EduCoderService(settings)
        self.stop = threading.Event()
        self.last_poll = 0
        self.last_cleanup = 0

    def sync(self):
        store = self.store
        with store.transaction() as cur:
            cur.execute("SELECT * FROM wecom_callback_inbox WHERE processed_at IS NULL ORDER BY received_at DESC LIMIT 1")
            notification = cur.fetchone()
            cur.execute("SELECT value FROM kf_meta WHERE name='activated_at'")
            activated_at = float(cur.fetchone()["value"])
            cur.execute("SELECT cursor_value FROM kf_cursors WHERE open_kfid=%s", (self.settings.open_kfid,))
            row = cur.fetchone()
            cursor = row["cursor_value"] if row else ""
        if not notification and time.time() - self.last_poll < 60:
            return
        token = ""
        if notification:
            crypto = CallbackCrypto(self.settings.corp_id, self.settings.token, self.settings.aes_key)
            if notification["key_id"] != crypto.key_id:
                raise RuntimeError("Retained callback needs its original key")
            encrypted = bytes(notification["encrypted_payload"]).decode("ascii")
            signature = hashlib.sha1("".join(sorted([self.settings.token, "0", "stored", encrypted])).encode()).hexdigest()
            message = crypto.decrypt(encrypted, signature, "0", "stored")
            if hashlib.sha256(message).hexdigest() != notification["event_digest"]:
                raise RuntimeError("Stored callback integrity failure")
            root = parse_xml(message)
            if xml_field(root, "OpenKfId") != self.settings.open_kfid:
                with store.transaction() as cur:
                    cur.execute("UPDATE wecom_callback_inbox SET processed_at=CURRENT_TIMESTAMP(6) WHERE event_digest=%s", (notification["event_digest"],))
                return
            created = int(xml_field(root, "CreateTime"))
            if time.time() - created < 540:
                token = xml_field(root, "Token")
        self.last_poll = time.time()
        # Bound each pass so welcome messages and outbox work cannot starve.
        for _ in range(5):
            try:
                page = self.api.sync(self.settings.open_kfid, cursor, token)
            except WeComError as exc:
                if token and not exc.uncertain:
                    page = self.api.sync(self.settings.open_kfid, cursor)
                else:
                    raise
            new_cursor = page.get("next_cursor")
            if not isinstance(new_cursor, str) or not new_cursor or len(new_cursor) > 128:
                raise RuntimeError("Invalid synchronization cursor")
            messages = page.get("msg_list", [])
            if not isinstance(messages, list):
                raise RuntimeError("Invalid synchronized messages")
            with store.transaction() as cur:
                for message in messages:
                    if not isinstance(message, dict) or not message.get("msgid"):
                        raise RuntimeError("Invalid synchronized message")
                    mid = hashlib.sha256((self.settings.open_kfid + ":" + message["msgid"]).encode()).hexdigest()
                    old = float(message.get("send_time", 0)) < activated_at
                    cur.execute("INSERT IGNORE INTO kf_messages (id,open_kfid,payload,status,created_at) VALUES (%s,%s,%s,%s,%s)",
                                (mid, self.settings.open_kfid, None if old else store.pack(message),
                                 "historical" if old else "pending", time.time()))
                cur.execute("INSERT INTO kf_cursors VALUES (%s,%s) ON DUPLICATE KEY UPDATE cursor_value=VALUES(cursor_value)",
                            (self.settings.open_kfid, new_cursor))
            if not page.get("has_more"):
                if notification:
                    with store.transaction() as cur:
                        cur.execute("UPDATE wecom_callback_inbox SET processed_at=CURRENT_TIMESTAMP(6) WHERE processed_at IS NULL AND received_at<=%s",
                                    (notification["received_at"],))
                return
            if cursor == new_cursor:
                raise RuntimeError("Synchronization cursor did not advance")
            cursor = new_cursor
        self.last_poll = 0

    def message(self):
        store = self.store
        with store.transaction() as cur:
            cur.execute("SELECT * FROM kf_messages WHERE status='pending' ORDER BY seq LIMIT 1 FOR UPDATE")
            record = cur.fetchone()
            if not record:
                return False
            message = store.unpack(record["payload"])
            event = message.get("event", {}) if message.get("msgtype") == "event" else {}
            if message.get("origin") == 4 and event.get("event_type") == "msg_send_fail":
                if event.get("open_kfid") == self.settings.open_kfid:
                    cur.execute("UPDATE kf_outbox SET status='failed',error_code=%s WHERE id=%s",
                                ("event_" + str(event.get("fail_type", 0)), event.get("fail_msgid")))
                self._processed(cur, record)
                return True
            entered = message.get("origin") == 4 and event.get("event_type") == "enter_session"
            if message.get("origin") != 3 and not entered:
                self._processed(cur, record)
                return True
            external = event.get("external_userid") if entered else message.get("external_userid")
            kfid = event.get("open_kfid") if entered else message.get("open_kfid")
            if not external or len(external) > 128 or kfid != self.settings.open_kfid:
                self._processed(cur, record)
                return True
            row, state = store.customer(cur, external, kfid)
            binding = store.binding(cur, row["id"])
            # Capture before advancing the dialog, while password-entry context is known.
            store.remember_message(cur, row, state, record["id"], message, binding=binding)
            now = time.time()
            if not entered:
                row.update(last_input=max(row["last_input"], float(message.get("send_time", now))),
                           last_input_id=record["id"], reply_count=0)
            welcome = event.get("welcome_code", "") if entered else ""
            if entered and not welcome:
                # No welcome permission: wait for customer text; do not consume
                # ordinary-message allowance merely because an old chat opened.
                self._processed(cur, record)
                return True
            content = message.get("text", {}) if message.get("msgtype") == "text" else {}
            replies, kind = dialog.advance(state, binding, content.get("content"), content.get("menu_id", ""),
                                           entered=entered, now=now, execution_enabled=self.settings.execution_enabled)
            if kind == "bind_and_list":
                if binding:
                    raise RuntimeError("Binding already exists")
                pending, profile = state["pending"], state["profile"]
                cur.execute("INSERT INTO kf_bindings (customer_id,service,account,password,login_no,profile,created_at) VALUES (%s,'educoder',%s,%s,%s,%s,%s)",
                            (row["id"], pending["account"], pending["password"], profile["login"], json.dumps(profile), now))
                state.pop("pending", None)
                kind = "list"
            if kind:
                if kind == "verify":
                    payload = dict(state["pending"])
                elif kind == "solve":
                    payload = {"items": [state["items"][i] for i in state["selected"]]}
                else:
                    payload = {}
                store.enqueue(cur, row, state, kind, payload)
            store.reply(cur, row, state, replies, welcome_code=welcome, sent_at=message.get("send_time"))
            store.save_customer(cur, row, state)
            self._processed(cur, record)
        return True

    @staticmethod
    def _processed(cur, record):
        # Dedupe and sanitized history remain; raw customer payload/password is erased.
        cur.execute("UPDATE kf_messages SET status='processed',payload=NULL WHERE id=%s", (record["id"],))

    def outbox(self):
        store = self.store
        now = time.time()
        with store.transaction() as cur:
            cur.execute("SELECT * FROM kf_outbox o WHERE status='pending' AND available_at<=%s AND NOT EXISTS (SELECT 1 FROM kf_outbox p WHERE p.customer_id=o.customer_id AND p.seq<o.seq AND p.status IN ('pending','sending')) ORDER BY seq LIMIT 1 FOR UPDATE", (now,))
            item = cur.fetchone()
            if not item:
                return False
            cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (item["customer_id"],))
            row = cur.fetchone()
            payload = store.unpack(item["payload"])
            if item["expires_at"] <= now or ("code" not in payload and row["reply_count"] >= 5):
                cur.execute("UPDATE kf_outbox SET status='deferred',error_code='reply_window' WHERE id=%s", (item["id"],))
                return True
            if "code" not in payload:
                cur.execute("UPDATE kf_customers SET reply_count=reply_count+1 WHERE id=%s", (row["id"],))
            cur.execute("UPDATE kf_outbox SET status='sending',attempts=attempts+1 WHERE id=%s", (item["id"],))
        status, error = "accepted", None
        try:
            self.api.send(payload)
        except WeComError as exc:
            status = "unknown" if exc.uncertain else "failed"
            error = str(exc.code)
            if not exc.uncertain and exc.code in {-1, 45009} and item["attempts"] < 2:
                status = "pending"
        except Exception:
            status, error = "unknown", "unexpected_transport"
        with store.transaction() as cur:
            cur.execute("UPDATE kf_outbox SET status=%s,error_code=%s WHERE id=%s AND status='sending'", (status, error, item["id"]))
            if status == "pending":
                cur.execute("UPDATE kf_outbox SET available_at=%s WHERE id=%s", (time.time() + 3, item["id"]))
                if "code" not in payload:
                    cur.execute("UPDATE kf_customers SET reply_count=GREATEST(0,reply_count-1) WHERE id=%s AND last_input_id=%s", (row["id"], row["last_input_id"]))
            if status == "accepted":
                cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (row["id"],))
                row = cur.fetchone()
                state = store.unpack(row["state"])
                state["expires_at"] = time.time() + 300
                store.save_customer(cur, row, state)
        if status != "accepted":
            log.warning("reply_not_confirmed status=%s code=%s", status, error)
        return True

    def action(self, execute=False, checkpoint=lambda: None):
        store = self.store
        job = store.claim(("solve",) if execute else ("verify", "list"))
        if not job:
            return False
        with store.transaction() as cur:
            cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (job["customer_id"],))
            row = cur.fetchone()
            state = store.unpack(row["state"])
            binding = store.binding(cur, row["id"])
            obsolete = state.get("job_id") != job["id"] or (job["kind"] != "solve" and state.get("expires_at", 0) <= time.time())
            if obsolete:
                cur.execute("UPDATE kf_jobs SET status='cancelled',payload=NULL WHERE id=%s", (job["id"],))
                return True
        invalid, failed, result = False, False, None

        def progress(value):
            checkpoint()
            if value is not None:
                with store.transaction() as cur:
                    cur.execute("UPDATE kf_jobs SET result=%s,updated_at=%s WHERE id=%s AND status='running'",
                                (json.dumps(value, ensure_ascii=False), time.time(), job["id"]))

        try:
            checkpoint()
            if job["kind"] == "verify":
                result = self.service.verify(**job["payload"])
            elif job["kind"] == "list":
                result = self.service.list_homeworks(binding)
            elif self.settings.execution_enabled:
                result = self.service.solve(binding, job["payload"]["items"], progress)
            else:
                raise RuntimeError("Execution disabled")
        except InvalidCredentials:
            invalid = True
        except Exception:
            failed = True
            log.warning("service_job_failed kind=%s", job["kind"])
        with store.transaction() as cur:
            cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (job["customer_id"],))
            row = cur.fetchone()
            state = store.unpack(row["state"])
            if state.get("job_id") != job["id"] or (job["kind"] != "solve" and state.get("expires_at", 0) <= time.time()):
                cur.execute("UPDATE kf_jobs SET status='cancelled',payload=NULL WHERE id=%s", (job["id"],))
                return True
            if job["kind"] == "verify":
                replies = dialog.verified(state, result, invalid=invalid, unavailable=failed, now=time.time())
            elif job["kind"] == "list":
                replies = dialog.listed(state, result, failed=failed)
            else:
                ok = sum(bool(r.get("ok")) for r in result or [])
                count = len(job["payload"]["items"])
                summary = (f"任务处理结束：所选{count}个实训，全部通过{ok}个，未全部通过或状态未知{count-ok}个。"
                           "已通过的关卡不会重复提交。")
                if failed:
                    summary += "执行过程中出现异常，未自动重放；请核对头歌状态后重新选择。"
                state.update(phase="idle", last_result=summary, items=[], selected=[], actions={})
                replies = [dialog.text(summary), dialog.services(state)]
            state.pop("job_id", None)
            cur.execute("UPDATE kf_jobs SET status=%s,payload=NULL,result=%s,updated_at=%s WHERE id=%s",
                        ("failed" if failed or invalid else "complete",
                         json.dumps(result, ensure_ascii=False) if job["kind"] == "solve" else None, time.time(), job["id"]))
            store.reply(cur, row, state, replies)
            store.save_customer(cur, row, state)
        return True

    def recover(self, role):
        store = self.store
        with store.transaction() as cur:
            if role == "gateway":
                cur.execute("UPDATE kf_outbox SET status='unknown',error_code='worker_interrupted' WHERE status='sending'")
                return
            kinds = ("solve",) if role == "executor" else ("verify", "list")
            cur.execute("SELECT * FROM kf_jobs WHERE status='running' AND kind IN (" + ",".join(["%s"] * len(kinds)) + ")", kinds)
            for job in cur.fetchall():
                cur.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (job["customer_id"],))
                row = cur.fetchone()
                state = store.unpack(row["state"])
                if state.get("job_id") == job["id"]:
                    state.update(phase="idle", pending={}, actions={})
                    state.pop("job_id", None)
                    summary = "服务重启中断了任务，未自动重复提交。请核对头歌状态后重新选择服务。"
                    state["last_result"] = summary
                    store.reply(cur, row, state, [dialog.text(summary), dialog.services(state)])
                    store.save_customer(cur, row, state)
                cur.execute("UPDATE kf_jobs SET status='interrupted',payload=NULL,updated_at=%s WHERE id=%s", (time.time(), job["id"]))

    def cleanup(self):
        if time.time() - self.last_cleanup < 15:
            return
        self.last_cleanup = time.time()
        with self.store.transaction() as cur:
            cur.execute("SELECT * FROM kf_customers WHERE updated_at<%s ORDER BY updated_at LIMIT 100 FOR UPDATE SKIP LOCKED", (time.time() - 300,))
            for row in cur.fetchall():
                state = self.store.unpack(row["state"])
                if state.get("phase") != "running" and state.get("expires_at", 0) <= time.time():
                    for key in ("pending", "profile", "items", "selected", "actions", "job_id"):
                        state.pop(key, None)
                    state.update(phase="idle", expired=True)
                    # Leave the expired timestamp so the next input only opens a menu.
                    self.store.save_customer(cur, row, state)
                    cur.execute("UPDATE kf_jobs SET status='cancelled',payload=NULL WHERE customer_id=%s AND kind IN ('verify','list') AND status IN ('pending','running')", (row["id"],))
                    cur.execute("UPDATE kf_outbox SET status='expired' WHERE customer_id=%s AND status='pending'", (row["id"],))
            cur.execute("DELETE FROM wecom_callback_inbox WHERE processed_at IS NOT NULL AND received_at < CURRENT_TIMESTAMP - INTERVAL 7 DAY")
            cur.execute("DELETE FROM kf_messages WHERE status IN ('processed','historical') AND created_at<%s", (time.time() - 7 * 86400,))
            cur.execute("DELETE FROM kf_message_history WHERE created_at<%s LIMIT 1000", (time.time() - 7 * 86400,))

    def run(self, role):
        if not self.settings.processing_enabled or not self.settings.open_kfid or (role == "gateway" and not self.settings.api_secret):
            raise ValueError("Message processing configuration incomplete")
        self.store.initialize()
        with self.store.exclusive(role) as lock_connection:
            lease_guard = threading.Lock()

            def checkpoint():
                # pymysql connections are not thread-safe; solver callbacks may be concurrent.
                with lease_guard:
                    try:
                        lock_connection.ping(reconnect=False)
                    except Exception:
                        # Fail closed even inside solver threads; ordinary exceptions
                        # are intentionally caught by the solver's repair machinery.
                        os._exit(70)
                self.store.heartbeat(role)
                Path("/tmp/" + role + "-heartbeat").touch()

            def pulse():
                while not self.stop.wait(10):
                    try:
                        checkpoint()
                    except Exception:
                        os._exit(70)

            self.recover(role)
            threading.Thread(target=pulse, daemon=True, name="heartbeat").start()
            while not self.stop.is_set():
                checkpoint()
                try:
                    if role == "gateway":
                        # Drain input and output before fetching another backlog page.
                        for _ in range(100):
                            if not self.message():
                                break
                            self.outbox()
                        self.outbox()
                        self.cleanup()
                        self.sync()
                    else:
                        self.action(role == "executor", checkpoint)
                except Exception as exc:
                    log.error("worker_iteration_failed role=%s type=%s", role, type(exc).__name__)
                    self.stop.wait(3)
                self.stop.wait(0.3 if role == "gateway" else 1)


def main():
    role = sys.argv[1] if len(sys.argv) == 2 else ""
    if role not in {"gateway", "actions", "executor"}:
        raise SystemExit("Usage: python -m wecom_kf.worker gateway|actions|executor")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    # httpx's informational request logs contain access_token query parameters.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    worker = Worker(Settings.from_env())
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run(role)


if __name__ == "__main__":
    main()
