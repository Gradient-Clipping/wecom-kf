"""Shared callback settings; credentials are never included in representations."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    corp_id: str = field(repr=False)
    token: str = field(repr=False)
    aes_key: str = field(repr=False)
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_database: str = ""
    mysql_user: str = field(default="", repr=False)
    mysql_password: str = field(default="", repr=False)
    revision: str = "development"
    max_clock_skew: int = 600

    @classmethod
    def from_env(cls) -> "Settings":
        # This release has no executor or administrative frontend.
        for name in ("EDUCODER_EXECUTION_ENABLED", "WECOM_MESSAGE_PROCESSING_ENABLED"):
            if os.getenv(name, "false").lower() not in {"false", "0", ""}:
                raise ValueError(f"{name} is unavailable in this callback-only release")
        return cls(
            corp_id=os.getenv("WECOM_CORP_ID", ""),
            token=os.getenv("WECOM_CALLBACK_TOKEN") or os.getenv("WECOM_KF_TOKEN", ""),
            aes_key=os.getenv("WECOM_ENCODING_AES_KEY") or os.getenv("WECOM_KF_AES_KEY", ""),
            mysql_host=os.getenv("MYSQL_HOST", ""),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_database=os.getenv("MYSQL_DATABASE", ""),
            mysql_user=os.getenv("MYSQL_USER", ""),
            mysql_password=os.getenv("MYSQL_PASSWORD", ""),
            revision=os.getenv("APP_REVISION", "development"),
        )
