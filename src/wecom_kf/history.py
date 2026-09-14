"""Visible conversation content for a bounded, credential-free read projection."""
import re

from .dialog import clip

REDACTED = "[凭据已隐藏]"
KINDS = {"text", "msgmenu", "image", "voice", "video", "file", "location", "link", "miniprogram", "event"}
LABELED_SECRET = re.compile(r"((?:password|passwd|密码|token|secret|authorization|api[_ -]?key)\s*[:：=]\s*)[^\r\n]+", re.I)


def visible_content(message, *, password_entry=False, known_secrets=()):
    kind = message.get("msgtype")
    kind = kind if isinstance(kind, str) and kind in KINDS else "unknown"
    body = message.get(kind)
    body = body if isinstance(body, dict) else {}
    if kind == "text":
        content = body.get("content", "")
    elif kind == "msgmenu":
        parts = [body.get("head_content", "")]
        for item in body.get("list", []):
            if not isinstance(item, dict):
                continue
            component = item.get(item.get("type"))
            if isinstance(component, dict):
                parts.append(component.get("content", ""))
        parts.append(body.get("tail_content", ""))
        content = "\n".join(p for p in parts if isinstance(p, str) and p)
    elif kind == "link":
        content = "\n".join(body[k] for k in ("title", "desc") if isinstance(body.get(k), str)) or "[link]"
    else:
        # Media binaries, welcome codes, menu actions and API identifiers are not prose.
        content = f"[{kind}]"
    content = content if isinstance(content, str) else ""
    redacted = password_entry
    if password_entry:
        content = REDACTED
    else:
        for secret in sorted({s for s in known_secrets if isinstance(s, str) and s}, key=len, reverse=True):
            if secret in content:
                content = content.replace(secret, REDACTED)
                redacted = True
        content, count = LABELED_SECRET.subn(lambda m: m[1] + REDACTED, content)
        redacted = redacted or bool(count)
    bounded = clip(content, 60000)
    return kind, bounded, redacted, bounded != content
