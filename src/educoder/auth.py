"""Authentication, signature key extraction, and request header generation."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from .exceptions import EduCoderError


API_BASE = "https://data.educoder.net"
WEB_BASE = "https://www.educoder.net"
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
DEFAULT_TIMEOUT = 30


def safe_json(response: requests.Response) -> dict[str, Any]:
    """Parse a JSON object response and raise readable errors otherwise."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        raise EduCoderError(
            f"Unexpected Content-Type '{content_type}' "
            f"(status {response.status_code})"
        )

    try:
        data = response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise EduCoderError(
            f"Response is not valid JSON (status {response.status_code})"
        ) from exc

    if not isinstance(data, dict):
        raise EduCoderError(
            f"Expected JSON object, got {type(data).__name__} "
            f"(status {response.status_code})"
        )

    if response.status_code >= 400:
        msg = data.get("message") or data.get("error") or json.dumps(
            data,
            ensure_ascii=False,
        )
        raise EduCoderError(f"HTTP {response.status_code}: {msg}")

    return data


def load_key_cache(cache_dir: str | Path = CACHE_DIR) -> dict[str, Any]:
    """Load the signature key cache from disk."""
    path = Path(cache_dir) / "keys.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_key_cache(data: dict[str, Any], cache_dir: str | Path = CACHE_DIR) -> None:
    """Persist the signature key cache to disk."""
    path = Path(cache_dir) / "keys.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_keys(
    force_refresh: bool = False,
    *,
    cache_dir: str | Path = CACHE_DIR,
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Fetch the current frontend bundle and extract mi + hw signature keys.

    Keys are cached by bundle URL, so repeated calls normally only fetch the
    lightweight homepage.
    """
    cache = load_key_cache(cache_dir)
    _log(verbose, "[*] Preparing signature keys...")
    bundle_url = find_bundle_url()

    if not force_refresh and bundle_url in cache:
        _log(verbose, "    [OK] Using cached keys")
        return cache[bundle_url]

    _log(verbose, "    Downloading current frontend bundle...")
    response = requests.get(
        bundle_url,
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    keys = extract_keys_from_bundle(response.text)
    keys["_bundle_url"] = bundle_url
    keys["_updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    cache[bundle_url] = keys
    save_key_cache(cache, cache_dir)
    _log(verbose, "    [OK] Extracted keys")
    return keys


def find_bundle_url() -> str:
    """Fetch the homepage and find the main JS bundle URL."""
    response = requests.get(
        f"{WEB_BASE}/",
        timeout=15,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    html = response.text

    patterns = [
        r'(?:https?:)?//[^"\'\s]+\.educoder\.net/[^"\'\s]*umi\.[a-f0-9]+\.js(?:\?[^"\'\s]*)?',
        r'(?:https?:)?//[^"\'\s]+(?:cdn|static)[^"\'\s]*\.educoder\.net/[^"\'\s]*\.[a-f0-9]{8,}\.js(?:\?[^"\'\s]*)?',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            url = match.group(0)
            return "https:" + url if url.startswith("//") else url

    raise EduCoderError("Could not find EduCoder frontend bundle URL")


def extract_keys_from_bundle(bundle_js: str) -> dict[str, str]:
    """Extract and double-decode mi/hw keys from the frontend bundle."""
    for bn_match in re.finditer(r"Bn:function\(\)\{return (\w+)\}", bundle_js):
        pos = bn_match.start()
        ctx = bundle_js[max(0, pos - 200) : pos + 600]

        hw_match = re.search(r"hw:function\(\)\{return (\w+)\}", ctx)
        mi_match = re.search(r"mi:function\(\)\{return (\w+)\}", ctx)
        if not (hw_match and mi_match):
            continue

        return_vars = {
            "mi": mi_match.group(1),
            "hw": hw_match.group(1),
        }
        var_map: dict[str, str] = {}
        for decl_match in re.finditer(
            r'(?:const|var|let)\s+(\w+)\s*=\s*"([A-Za-z0-9+/=]{30,})"',
            ctx,
        ):
            var_map[decl_match.group(1)] = decl_match.group(2)
        for decl_match in re.finditer(r',(\w+)\s*=\s*"([A-Za-z0-9+/=]{30,})"', ctx):
            var_map[decl_match.group(1)] = decl_match.group(2)

        try:
            mi_encoded = var_map[return_vars["mi"]]
            hw_encoded = var_map[return_vars["hw"]]
        except KeyError:
            continue

        return {
            "mi": double_base64_decode(mi_encoded),
            "hw": double_base64_decode(hw_encoded),
        }

    raise EduCoderError("Could not extract EduCoder signature keys from bundle")


def double_base64_decode(value: str) -> str:
    return base64.b64decode(base64.b64decode(value).decode()).decode()


def build_edu_headers(
    method: str,
    session: requests.Session,
    *,
    keys: dict[str, Any] | None = None,
    cache_dir: str | Path = CACHE_DIR,
    verbose: bool = False,
) -> dict[str, str]:
    """
    Build X-EDU-* headers for an EduCoder API request.

    Signature:
        method=<METHOD>&ak=<MI>&sk=<HW>&time=<ts>
        signature = MD5(btoa(signature_string))
    """
    keys = keys or extract_keys(cache_dir=cache_dir, verbose=verbose)
    timestamp = str(int(time.time() * 1000))
    signature_source = (
        f"method={method.upper()}&ak={keys['mi']}&sk={keys['hw']}&time={timestamp}"
    )
    signature_b64 = base64.b64encode(signature_source.encode()).decode()
    signature = hashlib.md5(signature_b64.encode()).hexdigest()

    headers = {
        "X-EDU-Type": "pc",
        "X-EDU-Timestamp": timestamp,
        "X-EDU-Signature": signature,
        "X-Original-Protocol": "https:",
        "X-Original-Host": "www.educoder.net",
        "X-Original-Origin": WEB_BASE,
        "X-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/148.0.0.0 Safari/537.36"
        ),
        "Origin": WEB_BASE,
        "Referer": f"{WEB_BASE}/",
    }
    session_cookie = session.cookies.get("_educoder_session")
    if session_cookie:
        headers["Pc-Authorization"] = session_cookie
    return headers


def _log(verbose: bool, message: str) -> None:
    if verbose:
        print(message)
