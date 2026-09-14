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
    api_secret: str = field(default="", repr=False)
    data_key: str = field(default="", repr=False)
    open_kfid: str = ""
    processing_enabled: bool = False
    execution_enabled: bool = False
    bank_path: str = "/data/question_bank.sqlite"
    cache_dir: str = "/tmp/educoder"
    oidc_secret: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)
    oidc_issuer: str = "https://auth.lazycampus.com/realms/lazycampus"
    oidc_client_id: str = "lazycampus-wecom-kf"
    public_base_url: str = "https://kf.lazycampus.com"

    @classmethod
    def from_env(cls) -> "Settings":
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
            api_secret=os.getenv("WECOM_API_SECRET") or os.getenv("WECOM_KF_SECRET", ""),
            data_key=os.getenv("DATA_ENCRYPTION_KEY", ""),
            open_kfid=os.getenv("WECOM_OPEN_KFID", ""),
            processing_enabled=os.getenv("WECOM_MESSAGE_PROCESSING_ENABLED", "false").lower() == "true",
            execution_enabled=os.getenv("EDUCODER_EXECUTION_ENABLED", "false").lower() == "true",
            bank_path=os.getenv("QUESTION_BANK_PATH", "/data/question_bank.sqlite"),
            cache_dir=os.getenv("EDUCODER_CACHE_DIR", "/tmp/educoder"),
            oidc_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
            session_secret=os.getenv("ADMIN_SESSION_SECRET", ""),
        )
