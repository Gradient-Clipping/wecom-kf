"""Environment helpers for examples and command-line entry points."""

from __future__ import annotations

import os
from pathlib import Path


def load_env_file(path: str | os.PathLike[str] = ".env", *, override: bool = False) -> None:
    """Load simple KEY=VALUE lines without requiring python-dotenv."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and (override or key not in os.environ):
            os.environ[key] = value


def credentials_from_env(
    *,
    account_key: str = "EDUCODER_ACCOUNT",
    password_key: str = "EDUCODER_PASSWORD",
) -> tuple[str, str]:
    """Return account/password from environment variables."""
    account = os.environ.get(account_key)
    password = os.environ.get(password_key)
    if not account or not password:
        raise ValueError(f"Missing {account_key} or {password_key}")
    return account, password
