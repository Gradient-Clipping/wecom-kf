"""Small formatting helpers used by optional human-readable output."""

from __future__ import annotations

from typing import Any


def display(value: Any) -> str:
    if value is None or value == "":
        return "N/A"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else "N/A"
    return str(value)


def mask_tail(value: Any, tail: int = 4) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "N/A"
    if len(text) <= tail:
        return "*" * len(text)
    return f"***{text[-tail:]}"


def mask_phone(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "N/A"
    if len(text) >= 7:
        return f"{text[:3]}****{text[-4:]}"
    return mask_tail(text)
