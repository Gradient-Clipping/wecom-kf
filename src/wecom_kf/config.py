"""Shared callback settings; credentials are never included in representations."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _url_from_env(name: str, default: str, *, origin_only: bool = False) -> str:
    value = os.getenv(name, default).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and "\\" not in value
            and (not origin_only or not parsed.path)
        )
        parsed.port  # Reject malformed ports without including the URL in errors.
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be an absolute HTTP(S) {'origin' if origin_only else 'URL'} without credentials, query or fragment")
    return value


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
    shuori_base_url: str = ""
    shuori_runtime_root: str = "/data/suori-runtime"
    shuori_grading_mode: str = "full_score"
    shuori_submit_enabled: bool = False
    oidc_secret: str = field(default="", repr=False)
    session_secret: str = field(default="", repr=False)
    oidc_issuer: str = "https://auth.lazycampus.com/realms/lazycampus"
    oidc_client_id: str = "lazycampus-wecom-kf"
    public_base_url: str = "https://kf.lazycampus.com"
    payment_enabled: bool = False
    payment_url: str = ""
    payment_secret: str = field(default="", repr=False)
    payment_platform: str = "educoder"
    payment_timezone: str = "Asia/Shanghai"

    @property
    def payment_ready(self) -> bool:
        return self.payment_enabled and self.payment_url.startswith("https://") and bool(self.payment_secret)

    @classmethod
    def from_env(cls) -> "Settings":
        oidc_client_id = os.getenv("OIDC_CLIENT_ID", cls.oidc_client_id).strip()
        if not oidc_client_id or any(char.isspace() or ord(char) < 32 for char in oidc_client_id):
            raise ValueError("OIDC_CLIENT_ID must be a non-empty identifier without whitespace")
        shuori_base_url = os.getenv("SHUORI_BASE_URL", "").strip().rstrip("/")
        if shuori_base_url:
            shuori_base_url = _url_from_env("SHUORI_BASE_URL", shuori_base_url)
        grading_mode = os.getenv("SHUORI_GRADING_MODE", "full_score").strip()
        if grading_mode not in {"normal", "half_score", "full_score"}:
            raise ValueError("SHUORI_GRADING_MODE must be normal, half_score or full_score")
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
            shuori_base_url=shuori_base_url,
            shuori_runtime_root=os.getenv("SHUORI_RUNTIME_ROOT", "/data/suori-runtime"),
            shuori_grading_mode=grading_mode,
            shuori_submit_enabled=os.getenv("SHUORI_SUBMIT_ENABLED", "false").lower() == "true",
            oidc_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
            session_secret=os.getenv("ADMIN_SESSION_SECRET", ""),
            oidc_issuer=_url_from_env("OIDC_ISSUER", cls.oidc_issuer),
            oidc_client_id=oidc_client_id,
            public_base_url=_url_from_env("PUBLIC_BASE_URL", cls.public_base_url, origin_only=True),
            payment_enabled=os.getenv("SERVICE_PAYMENT_ENABLED", "false").lower() == "true",
            payment_url=os.getenv("SERVICE_PAYMENT_URL", ""),
            payment_secret=os.getenv("SERVICE_PAYMENT_SECRET", ""),
            payment_platform=os.getenv("SERVICE_PAYMENT_PLATFORM", "educoder"),
            payment_timezone=os.getenv("SERVICE_PAYMENT_TIMEZONE", "Asia/Shanghai"),
        )
