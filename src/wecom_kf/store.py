"""Transactional inbox, conversations, bindings, work queue and notification outbox."""

import hashlib
import json
import time
import uuid
from contextlib import contextmanager

from cryptography.fernet import Fernet
from pymysql.cursors import DictCursor

from .inbox import MySQLInbox
from .history import visible_content

DDL = (
    """CREATE TABLE IF NOT EXISTS kf_purchases (
        id CHAR(32) PRIMARY KEY, customer_id CHAR(64) NOT NULL,
        order_id CHAR(36) UNIQUE, snapshot MEDIUMBLOB NOT NULL, document JSON,
        status VARCHAR(24) NOT NULL, solve_job_id CHAR(32) UNIQUE,
        updated_at DOUBLE NOT NULL, KEY polling (status,updated_at)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_payment_penalties (
        purchase_id CHAR(32) PRIMARY KEY, customer_id CHAR(64) NOT NULL,
        business_day CHAR(10) NOT NULL, returned_at DOUBLE,
        KEY allowance (customer_id,business_day)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_payment_events (
        id CHAR(36) PRIMARY KEY, payload JSON NOT NULL, received_at DOUBLE NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_payment_nonces (
        id CHAR(64) PRIMARY KEY, expires_at DOUBLE NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_meta (
        name VARCHAR(64) PRIMARY KEY, value TEXT NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_cursors (
        open_kfid VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        cursor_value VARCHAR(128) NOT NULL DEFAULT '') ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_customers (
        id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        external_userid VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        open_kfid VARCHAR(128) NOT NULL, state MEDIUMBLOB NOT NULL,
        last_input DOUBLE NOT NULL DEFAULT 0, last_input_id CHAR(64) NOT NULL DEFAULT '',
        reply_count INT NOT NULL DEFAULT 0, updated_at DOUBLE NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_bindings (
        customer_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        service VARCHAR(32) NOT NULL, account VARCHAR(256) NOT NULL,
        password TEXT NOT NULL, login_no VARCHAR(128) NOT NULL,
        profile JSON NOT NULL, created_at DOUBLE NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_messages (
        seq BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        open_kfid VARCHAR(128) NOT NULL, payload MEDIUMBLOB,
        status VARCHAR(24) NOT NULL DEFAULT 'pending', created_at DOUBLE NOT NULL,
        KEY pending (status,seq)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_jobs (
        id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        customer_id CHAR(64) NOT NULL, kind VARCHAR(24) NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'pending', payload MEDIUMBLOB,
        result JSON, created_at DOUBLE NOT NULL, updated_at DOUBLE NOT NULL,
        KEY pending (kind,status,created_at), KEY customer (customer_id,status)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_outbox (
        seq BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        customer_id CHAR(64) NOT NULL, payload MEDIUMBLOB NOT NULL,
        status VARCHAR(24) NOT NULL DEFAULT 'pending', attempts INT NOT NULL DEFAULT 0,
        error_code VARCHAR(64), created_at DOUBLE NOT NULL, available_at DOUBLE NOT NULL,
        expires_at DOUBLE NOT NULL, KEY pending (status,available_at), KEY customer (customer_id,seq)) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_workers (
        role VARCHAR(32) PRIMARY KEY, heartbeat DOUBLE NOT NULL) ENGINE=InnoDB""",
    """CREATE TABLE IF NOT EXISTS kf_message_history (
        id VARCHAR(80) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        customer_id CHAR(64) NOT NULL, open_kfid VARCHAR(128) NOT NULL,
        direction VARCHAR(8) NOT NULL, message_id CHAR(64) NULL, outbox_id CHAR(32) NULL,
        message_type VARCHAR(24) NOT NULL, content_text TEXT NOT NULL,
        content_redacted BOOLEAN NOT NULL, content_truncated BOOLEAN NOT NULL,
        sent_at DOUBLE NULL, created_at DOUBLE NOT NULL,
        KEY retention (created_at), KEY conversation (customer_id,created_at)
        ) ENGINE=InnoDB""",
)


class Store(MySQLInbox):
    def __init__(self, settings):
        super().__init__(settings)
        self.cipher = Fernet(settings.data_key.encode())

    def pack(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode())

    def unpack(self, value):
        return json.loads(self.cipher.decrypt(bytes(value)))

    @contextmanager
    def transaction(self):
        with self._connect() as connection:
            connection.begin()
            with connection.cursor(DictCursor) as cursor:
                try:
                    yield cursor
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def initialize(self):
        super().initialize()
        with self._connect() as connection, connection.cursor() as cursor:
            for statement in DDL:
                cursor.execute(statement)
            # Immutable deployment watermark: never replay pre-activation chat commands.
            cursor.execute("INSERT IGNORE INTO kf_meta (name,value) VALUES ('activated_at',%s)", (str(time.time()),))

    def customer_id(self, external):
        return hashlib.sha256((self.settings.corp_id + ":" + external).encode()).hexdigest()

    def customer(self, cursor, external, open_kfid):
        cid = self.customer_id(external)
        cursor.execute("INSERT IGNORE INTO kf_customers (id,external_userid,open_kfid,state,updated_at) VALUES (%s,%s,%s,%s,%s)",
                       (cid, external, open_kfid, self.pack({"phase": "idle"}), time.time()))
        cursor.execute("SELECT * FROM kf_customers WHERE id=%s FOR UPDATE", (cid,))
        row = cursor.fetchone()
        row["open_kfid"] = open_kfid
        return row, self.unpack(row["state"])

    def save_customer(self, cursor, row, state):
        cursor.execute("UPDATE kf_customers SET open_kfid=%s,state=%s,last_input=%s,last_input_id=%s,reply_count=%s,updated_at=%s WHERE id=%s",
                       (row["open_kfid"], self.pack(state), row["last_input"], row["last_input_id"], row["reply_count"], time.time(), row["id"]))

    def binding(self, cursor, cid):
        cursor.execute("SELECT * FROM kf_bindings WHERE customer_id=%s", (cid,))
        return cursor.fetchone()

    def enqueue(self, cursor, row, state, kind, payload):
        job = uuid.uuid4().hex
        cursor.execute("INSERT INTO kf_jobs (id,customer_id,kind,payload,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s)",
                       (job, row["id"], kind, self.pack(payload), time.time(), time.time()))
        if kind == "solve":
            cursor.execute("UPDATE kf_jobs SET result=%s WHERE id=%s", (json.dumps({
                "passed_homeworks": 0, "total_homeworks": len(payload["items"]), "passed_units": 0,
                "current": "等待处理", "failures": [], "final": False}), job))
        state["job_id"] = job
        return job

    def reply(self, cursor, row, state, replies, *, welcome_code="", sent_at=None):
        now = time.time()
        state["expires_at"] = now + 300
        for reply in replies:
            mid = uuid.uuid4().hex
            payload = {**reply, "msgid": mid}
            if welcome_code:
                payload["code"] = welcome_code
                expires = (sent_at or now) + 19
            else:
                payload.update(touser=row["external_userid"], open_kfid=row["open_kfid"])
                expires = row["last_input"] + 48 * 3600
            cursor.execute("INSERT INTO kf_outbox (id,customer_id,payload,created_at,available_at,expires_at) VALUES (%s,%s,%s,%s,%s,%s)",
                           (mid, row["id"], self.pack(payload), now, now, expires))
            self.remember_message(cursor, row, state, mid, reply, direction="outbound")

    def remember_message(self, cursor, row, state, source_id, message, *, direction="inbound", binding=None):
        if binding is None:
            binding = self.binding(cursor, row["id"])
        secrets = [(binding or {}).get("password"), state.get("pending", {}).get("password")]
        kind, content, redacted, truncated = visible_content(
            message, password_entry=direction == "inbound" and state.get("phase") == "password" and message.get("msgtype") != "event",
            known_secrets=secrets,
        )
        sent_at = message.get("send_time") if direction == "inbound" else None
        if not isinstance(sent_at, (int, float)) or sent_at <= 0:
            sent_at = None
        cursor.execute("""INSERT IGNORE INTO kf_message_history
            (id,customer_id,open_kfid,direction,message_id,outbox_id,message_type,content_text,content_redacted,content_truncated,sent_at,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (direction + ":" + source_id, row["id"], row["open_kfid"], direction,
             source_id if direction == "inbound" else None, source_id if direction == "outbound" else None,
             kind, content, redacted, truncated, sent_at, time.time()))

    def claim(self, kinds):
        with self.transaction() as cursor:
            marks = ",".join(["%s"] * len(kinds))
            cursor.execute(f"SELECT * FROM kf_jobs WHERE status='pending' AND kind IN ({marks}) ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED", kinds)
            job = cursor.fetchone()
            if job:
                cursor.execute("UPDATE kf_jobs SET status='running',updated_at=%s WHERE id=%s", (time.time(), job["id"]))
                job["payload"] = self.unpack(job["payload"])
            return job

    def heartbeat(self, role):
        with self.transaction() as cursor:
            cursor.execute("INSERT INTO kf_workers VALUES (%s,%s) ON DUPLICATE KEY UPDATE heartbeat=VALUES(heartbeat)", (role, time.time()))

    @contextmanager
    def exclusive(self, role):
        # A non-expiring MySQL advisory lock prevents overlapping worker pods.
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT GET_LOCK(%s,0)", (f"wecom_kf_{role}",))
                if cursor.fetchone()[0] != 1:
                    raise RuntimeError("Worker role already owned")
            yield connection
