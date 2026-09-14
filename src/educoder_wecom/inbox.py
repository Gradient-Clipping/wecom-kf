"""Durable, idempotent storage of authenticated encrypted event packets."""

import hashlib

import pymysql

from .config import Settings


class MySQLInbox:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not all((settings.mysql_host, settings.mysql_database, settings.mysql_user, settings.mysql_password)):
            raise ValueError("Dedicated MySQL configuration is required")

    def _connect(self):
        return pymysql.connect(
            host=self.settings.mysql_host, port=self.settings.mysql_port,
            database=self.settings.mysql_database, user=self.settings.mysql_user,
            password=self.settings.mysql_password, charset="utf8mb4",
            connect_timeout=2, read_timeout=2, write_timeout=2, autocommit=True,
        )

    def initialize(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wecom_callback_inbox (
                    event_digest CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
                    key_id CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                    encrypted_payload MEDIUMBLOB NOT NULL,
                    received_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    last_seen_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    delivery_count INT UNSIGNED NOT NULL DEFAULT 1,
                    processed_at TIMESTAMP(6) NULL,
                    KEY pending_events (processed_at, received_at)
                ) ENGINE=InnoDB
            """)

    def ping(self):
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()

    def record(self, message: bytes, encrypted: str, key_id: str):
        digest = hashlib.sha256(message).hexdigest()
        with self._connect() as connection, connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO wecom_callback_inbox (event_digest, key_id, encrypted_payload)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE delivery_count=delivery_count+1,
                    last_seen_at=CURRENT_TIMESTAMP(6)
            """, (digest, key_id, encrypted.encode("ascii")))
