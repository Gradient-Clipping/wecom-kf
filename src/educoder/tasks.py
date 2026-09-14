"""Task runtime APIs for entering, editing, and evaluating shixun games."""

from __future__ import annotations

import base64
import html
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .auth import API_BASE, WEB_BASE
from .exceptions import EduCoderError

if TYPE_CHECKING:
    from .client import EduCoderClient


@dataclass(slots=True)
class EvaluationResult:
    """Result returned by a task evaluation flow."""

    task: dict[str, Any]
    update_file: dict[str, Any]
    build: dict[str, Any]
    status: dict[str, Any]

    @property
    def passed(self) -> bool:
        return task_passed(self.status)

    @property
    def diagnostics(self) -> dict[str, Any]:
        """Structured results and visible failure details; no network requests."""
        return summarize_evaluation(self.status)

    @property
    def errors(self) -> list[dict[str, Any]]:
        """Failed test cases in source order, including restricted placeholders."""
        return self.diagnostics["errors"]

    @property
    def next_game(self) -> str | None:
        next_game = self.status.get("next_game")
        return str(next_game) if next_game else None

    def summary(self) -> dict[str, Any]:
        task = self.task
        challenge = task.get("challenge") or {}
        game = task.get("game") or {}
        diagnostics = self.diagnostics
        return {
            "game_identifier": game.get("identifier"),
            "game_id": game.get("id"),
            "challenge_id": challenge.get("id") or game.get("challenge_id"),
            "challenge_name": challenge.get("subject"),
            "path": normalize_task_path(challenge.get("path")),
            "passed": self.passed,
            "status": self.status.get("status"),
            "last_compile_output": self.status.get("last_compile_output"),
            "test_sets_count": self.status.get("test_sets_count"),
            "sets_error_count": self.status.get("sets_error_count"),
            "next_game": self.next_game,
            "finished": diagnostics["finished"],
            "compile_success": diagnostics["compile_success"],
            "evaluation_message": diagnostics["message"],
            "errors": diagnostics["errors"],
        }


class TasksAPI:
    """High-level task runtime APIs bound to an authenticated client."""

    def __init__(self, client: "EduCoderClient") -> None:
        self.client = client

    def enter_shixun(
        self,
        shixun_identifier: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        reset: bool = False,
    ) -> str:
        return enter_shixun(
            self.client,
            shixun_identifier,
            login_no or self._login_no(),
            homework_common_id=homework_common_id,
            reset=reset,
        )

    def get(
        self,
        game_identifier: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return get_task(
            self.client,
            game_identifier,
            login_no or self._login_no(),
            homework_common_id=homework_common_id,
        )

    def file_content(
        self,
        game_identifier: str,
        path: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        exercise_id: int | str | None = "",
    ) -> dict[str, Any]:
        return get_task_file_content(
            self.client,
            game_identifier,
            path,
            login_no or self._login_no(),
            homework_common_id=homework_common_id,
            exercise_id=exercise_id,
        )

    def diagnostics(
        self,
        game_identifier: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        """Read the latest stored evaluation without editing or submitting code.

        Locked/hidden cases retain their result but omit input/output details.
        This reads the last evaluation, not necessarily the current editor code.
        """
        task = self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        return summarize_evaluation(task_result_status(task))

    def read_file(
        self,
        game_identifier: str,
        path: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        exercise_id: int | str | None = "",
    ) -> str:
        return decode_task_file_content(
            self.file_content(
                game_identifier,
                path,
                homework_common_id=homework_common_id,
                login_no=login_no,
                exercise_id=exercise_id,
            )
        )

    def content(
        self,
        game_identifier: str,
        *,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        download_images_to: str | Path | None = None,
        embed_images_base64: bool = False,
        image_base64_format: str = "base64",
    ) -> dict[str, Any]:
        """Return structured problem content with images in source order."""
        login_no = login_no or self._login_no()
        task = self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        content = structure_task_content(task)
        if download_images_to is not None:
            download_task_images(self.client, content, download_images_to)
        if embed_images_base64:
            embed_task_images_base64(
                self.client,
                content,
                image_format=image_base64_format,
            )
        return content

    def update_file(
        self,
        game_identifier: str,
        path: str,
        content: str,
        *,
        task: dict[str, Any] | None = None,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        evaluate: int = 1,
        tab_type: int | None = None,
        exercise_id: int | str | None = None,
    ) -> dict[str, Any]:
        login_no = login_no or self._login_no()
        task = task or self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        return update_task_file(
            self.client,
            task,
            path,
            content,
            login_no,
            homework_common_id=homework_common_id,
            evaluate=evaluate,
            tab_type=tab_type,
            exercise_id=exercise_id,
        )

    def replace_file(
        self,
        game_identifier: str,
        path: str,
        content: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Replace the whole remote file content."""
        return self.update_file(game_identifier, path, content, **kwargs)

    def build(
        self,
        game_identifier: str,
        *,
        task: dict[str, Any] | None = None,
        update_file_result: dict[str, Any] | None = None,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        tab_type: int | None = None,
        first: int = 1,
        content_modified: int | None = None,
        resubmit: str | None = None,
    ) -> dict[str, Any]:
        login_no = login_no or self._login_no()
        task = task or self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        return build_game(
            self.client,
            task,
            login_no,
            update_file_result=update_file_result,
            homework_common_id=homework_common_id,
            tab_type=tab_type,
            first=first,
            content_modified=content_modified,
            resubmit=resubmit,
        )

    def status(
        self,
        game_identifier: str,
        *,
        task: dict[str, Any] | None = None,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        sec_key: str | None = None,
        resubmit: str = "",
        time_out: bool = False,
        port: int | str = 0,
    ) -> dict[str, Any]:
        login_no = login_no or self._login_no()
        task = task or self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        return get_game_status(
            self.client,
            task,
            login_no,
            homework_common_id=homework_common_id,
            sec_key=sec_key,
            resubmit=resubmit,
            time_out=time_out,
            port=port,
        )

    def wait_status(
        self,
        game_identifier: str,
        *,
        task: dict[str, Any] | None = None,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        sec_key: str | None = None,
        resubmit: str = "",
        port: int | str = 0,
        interval: float = 1.0,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        login_no = login_no or self._login_no()
        task = task or self.get(
            game_identifier,
            homework_common_id=homework_common_id,
            login_no=login_no,
        )
        return wait_game_status(
            self.client,
            task,
            login_no,
            homework_common_id=homework_common_id,
            sec_key=sec_key,
            resubmit=resubmit,
            port=port,
            interval=interval,
            timeout=timeout,
        )

    def evaluate_code(
        self,
        game_identifier: str,
        code: str,
        *,
        path: str | None = None,
        homework_common_id: int | str | None = None,
        login_no: str | None = None,
        wait: bool = True,
        interval: float = 1.0,
        timeout: float = 120.0,
    ) -> EvaluationResult:
        login_no = login_no or self._login_no()
        return evaluate_task_code(
            self.client,
            game_identifier,
            code,
            login_no,
            path=path,
            homework_common_id=homework_common_id,
            wait=wait,
            interval=interval,
            timeout=timeout,
        )

    def report_cost_time(
        self,
        game_identifier: str,
        seconds: int | float,
        *,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return report_cost_time(
            self.client,
            game_identifier,
            seconds,
            login_no or self._login_no(),
        )

    def _login_no(self) -> str:
        user_info = self.client.ensure_logged_in()
        login_no = user_info.get("login")
        if not login_no:
            raise ValueError("Could not determine EduCoder login number")
        return str(login_no)


def enter_shixun(
    client: "EduCoderClient",
    shixun_identifier: str,
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
    reset: bool = False,
) -> str:
    """Enter a shixun and return the server-selected game identifier."""
    params: dict[str, Any] = {"zzud": login_no}
    if homework_common_id is not None:
        params["homework_common_id"] = homework_common_id
    if reset:
        params["reset"] = "true"
    data = client.request_json(
        "GET",
        f"/api/shixuns/{shixun_identifier}/shixun_exec.json",
        params=params,
        headers={"Referer": "https://www.educoder.net/"},
    )
    game_identifier = data.get("game_identifier")
    if not game_identifier:
        raise EduCoderError(f"shixun_exec did not return game_identifier: {data}")
    return str(game_identifier)


def get_task(
    client: "EduCoderClient",
    game_identifier: str,
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
) -> dict[str, Any]:
    """Fetch /api/tasks/<game_identifier>.json."""
    params: dict[str, Any] = {"zzud": login_no}
    if homework_common_id is not None:
        params["homework_common_id"] = homework_common_id
    return client.request_json(
        "GET",
        f"/api/tasks/{game_identifier}.json",
        params=params,
        headers={"Referer": _task_referer(game_identifier)},
    )


def get_task_file_content(
    client: "EduCoderClient",
    game_identifier: str,
    path: str,
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
    exercise_id: int | str | None = "",
) -> dict[str, Any]:
    """Fetch a task repository file."""
    params: dict[str, Any] = {
        "path": normalize_task_path(path),
        "exercise_id": "" if exercise_id is None else exercise_id,
        "zzud": login_no,
    }
    if homework_common_id is not None:
        params["homework_common_id"] = homework_common_id
    return client.request_json(
        "GET",
        f"/api/tasks/{game_identifier}/rep_content.json",
        params=params,
        headers={"Referer": _task_referer(game_identifier)},
    )


def decode_task_file_content(file_content: dict[str, Any]) -> str:
    """Decode the base64 content returned by rep_content.json."""
    content = file_content.get("content") or {}
    encoded = content.get("content")
    if not encoded:
        return ""
    return base64.b64decode(str(encoded)).decode("utf-8")


def structure_task_content(task: dict[str, Any]) -> dict[str, Any]:
    """Parse challenge.task_pass into ordered, structured content blocks."""
    game = task.get("game") or {}
    challenge = task.get("challenge") or {}
    raw = str(challenge.get("task_pass") or "")
    blocks = parse_markdown_blocks(raw)
    images = [block for block in blocks if block.get("type") == "image"]
    return {
        "game_identifier": game.get("identifier"),
        "game_id": game.get("id"),
        "challenge_id": challenge.get("id") or game.get("challenge_id"),
        "challenge_name": challenge.get("subject"),
        "challenge_position": challenge.get("position"),
        "path": normalize_task_path(challenge.get("path")),
        "raw": raw,
        "blocks": blocks,
        "images": images,
    }


def parse_markdown_blocks(markdown: str) -> list[dict[str, Any]]:
    """Best-effort Markdown/HTML parser preserving image order."""
    # A single HTML image may span several source lines.
    for token in reversed(find_task_image_tokens(markdown)):
        start, end = token["start"], token["end"]
        markup = re.sub(r"[\r\n]+", " ", markdown[start:end])
        markdown = markdown[:start] + markup + markdown[end:]
    blocks: list[dict[str, Any]] = []
    paragraph: list[str] = []
    code_lines: list[str] = []
    in_code = False
    code_language = ""

    def flush_paragraph() -> None:
        if not paragraph:
            return
        text = clean_inline_text(" ".join(paragraph))
        paragraph.clear()
        if text:
            blocks.append({"type": "paragraph", "text": text})

    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            if in_code:
                blocks.append(
                    {
                        "type": "code",
                        "language": code_language,
                        "text": "\n".join(code_lines),
                    }
                )
                code_lines = []
                code_language = ""
                in_code = False
            else:
                flush_paragraph()
                in_code = True
                code_language = stripped[3:].strip()
            continue

        if in_code:
            code_lines.append(raw_line)
            continue

        if not stripped:
            flush_paragraph()
            continue

        if stripped == "[TOC]":
            flush_paragraph()
            blocks.append({"type": "toc"})
            continue

        if re.fullmatch(r"-{3,}", stripped):
            flush_paragraph()
            blocks.append({"type": "divider"})
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            blocks.append(
                {
                    "type": "heading",
                    "level": len(heading.group(1)),
                    "text": clean_inline_text(heading.group(2)),
                }
            )
            continue

        image_tokens = find_task_image_tokens(line)
        if image_tokens:
            cursor = 0
            for token in image_tokens:
                before = clean_inline_text(line[cursor : token["start"]])
                if before:
                    paragraph.append(before)
                    flush_paragraph()
                else:
                    flush_paragraph()
                image = token["image"]
                image["index"] = len([b for b in blocks if b.get("type") == "image"]) + 1
                blocks.append(image)
                cursor = token["end"]
            after = clean_inline_text(line[cursor:])
            if after:
                paragraph.append(after)
            continue

        text = clean_inline_text(line)
        if text:
            paragraph.append(text)

    if in_code:
        blocks.append(
            {
                "type": "code",
                "language": code_language,
                "text": "\n".join(code_lines),
            }
        )
    flush_paragraph()
    return blocks


def find_image_tokens(line: str) -> list[dict[str, Any]]:
    tokens: list[dict[str, Any]] = []
    markdown_image = re.compile(
        r"!\[([^\]]*)\]\(\s*(<[^>]+>|[^()\s]+(?:\([^()]*\)[^()\s]*)*)"
        r"(?:\s+(?:\"([^\"]*)\"|'([^']*)'))?\s*\)"
    )
    html_image = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)

    for match in markdown_image.finditer(line):
        alt, src = match.group(1), match.group(2).strip("<>")
        title = match.group(3) or match.group(4)
        image = build_image_block(src=src, alt=alt, title=title)
        tokens.append({"start": match.start(), "end": match.end(), "image": image})

    for match in html_image.finditer(line):
        attrs = parse_html_attrs(match.group(1))
        src = attrs.get("src")
        if not src:
            continue
        image = build_image_block(
            src=src,
            alt=attrs.get("alt"),
            title=attrs.get("title"),
            width=attrs.get("width"),
            height=attrs.get("height"),
            attrs=attrs,
        )
        tokens.append({"start": match.start(), "end": match.end(), "image": image})

    ordered = []
    for token in sorted(tokens, key=lambda token: token["start"]):
        if not ordered or token["start"] >= ordered[-1]["end"]:
            ordered.append(token)
    return ordered


def find_task_image_tokens(markdown: str, *, strict: bool = False) -> list[dict[str, Any]]:
    """Locate image occurrences in source order, excluding examples/comments."""
    masked = re.sub(r"<!--[\s\S]*?-->", lambda m: " " * len(m[0]), markdown)
    lines = masked.splitlines(keepends=True)
    fence_char = ""
    fence_length = 0
    for index, line in enumerate(lines):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_char:
            lines[index] = " " * len(line)
            if (fence and fence[1][0] == fence_char
                    and len(fence[1]) >= fence_length
                    and not line[fence.end():].strip()):
                fence_char = ""
        elif fence:
            fence_char, fence_length = fence[1][0], len(fence[1])
            lines[index] = " " * len(line)
    masked = "".join(lines)
    masked = re.sub(r"(`+)([^`]*?)\1", lambda m: " " * len(m[0]), masked)
    tokens = find_image_tokens(masked)
    if strict:
        for marker in re.finditer(r"!\[[^\]]*\]|<img\b", masked, re.IGNORECASE):
            if not any(t["start"] <= marker.start() < t["end"] for t in tokens):
                raise ValueError("Unresolved image markup; use inline Markdown or HTML images")
    return tokens


def build_image_block(
    *,
    src: str,
    alt: str | None = None,
    title: str | None = None,
    width: str | None = None,
    height: str | None = None,
    attrs: dict[str, str] | None = None,
) -> dict[str, Any]:
    src = html.unescape(src)
    return {
        "type": "image",
        "src": src,
        "url": resolve_task_asset_url(src),
        "alt": alt or "",
        "title": title or "",
        "width": width or "",
        "height": height or "",
        "attrs": attrs or {},
    }


def parse_html_attrs(raw_attrs: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    attr_pattern = re.compile(
        r"([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*"
        r"(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))"
    )
    for match in attr_pattern.finditer(raw_attrs):
        value = match.group(2) or match.group(3) or match.group(4) or ""
        attrs[match.group(1).lower()] = html.unescape(value)
    return attrs


def clean_inline_text(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(?:center|p|span|div)[^>]*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def resolve_task_asset_url(src: str) -> str:
    if src.startswith(("http://", "https://", "data:image/")):
        return src
    if src.startswith("/api/"):
        return f"{API_BASE}{src}"
    if src.startswith("/"):
        return f"{WEB_BASE}{src}"
    return f"{WEB_BASE}/{src.lstrip('/')}"


def download_task_images(
    client: "EduCoderClient",
    structured_content: dict[str, Any],
    output_dir: str | Path,
) -> list[dict[str, Any]]:
    """Download ordered problem images and add local_path to image blocks."""
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, Any]] = []
    for image in structured_content.get("images") or []:
        index = int(image.get("index") or len(downloaded) + 1)
        response = client.request("GET", str(image["url"]))
        response.raise_for_status()
        extension = image_extension(response.headers.get("content-type"), image["url"])
        filename = f"{index:03d}{extension}"
        path = target_dir / filename
        path.write_bytes(response.content)
        image["local_path"] = str(path.resolve())
        downloaded.append(image)
    return downloaded


def embed_task_images_base64(
    client: "EduCoderClient",
    structured_content: dict[str, Any],
    *,
    image_format: str = "base64",
) -> list[dict[str, Any]]:
    """Embed ordered problem images as base64 in image blocks."""
    if image_format not in {"base64", "data_url"}:
        raise ValueError("image_format must be 'base64' or 'data_url'")
    embedded: list[dict[str, Any]] = []
    for image in structured_content.get("images") or []:
        response = client.request("GET", str(image["url"]))
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "application/octet-stream"
        encoded = base64.b64encode(response.content).decode("ascii")
        image["content_type"] = content_type.split(";", 1)[0]
        if image_format == "base64":
            image["base64"] = encoded
            image.pop("data_url", None)
        else:
            image["data_url"] = f"data:{image['content_type']};base64,{encoded}"
            image.pop("base64", None)
        embedded.append(image)
    return embedded


def image_extension(content_type: str | None, url: str) -> str:
    if content_type:
        media_type = content_type.split(";", 1)[0].lower()
        if media_type == "image/jpeg":
            return ".jpg"
        if media_type == "image/png":
            return ".png"
        if media_type == "image/gif":
            return ".gif"
        if media_type == "image/webp":
            return ".webp"
    suffix = Path(urlparse(url).path).suffix
    return suffix if suffix else ".img"


def update_task_file(
    client: "EduCoderClient",
    task: dict[str, Any],
    path: str,
    content: str,
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
    evaluate: int = 1,
    tab_type: int | None = None,
    exercise_id: int | str | None = None,
) -> dict[str, Any]:
    """Replace a file in the current myshixun repository."""
    game = task.get("game") or {}
    myshixun = task.get("myshixun") or {}
    challenge = task.get("challenge") or {}
    resolved_homework_id = homework_common_id or task.get("homework_common_id")
    resolved_tab_type = tab_type if tab_type is not None else infer_tab_type(task)
    payload = {
        "path": normalize_task_path(path),
        "evaluate": evaluate,
        "content": content,
        "game_id": game.get("id"),
        "tab_type": resolved_tab_type,
        "exercise_id": exercise_id,
        "homework_common_id": str(resolved_homework_id)
        if resolved_homework_id is not None
        else None,
        "extras": build_task_extras(task, homework_common_id=resolved_homework_id),
    }
    result = client.request_json(
        "POST",
        f"/api/myshixuns/{myshixun['identifier']}/update_file.json",
        params={"zzud": login_no},
        json=payload,
        headers={"Referer": _task_referer(str(game.get("identifier") or ""))},
    )
    if isinstance(result.get("status"), int) and result["status"] < 0:
        raise EduCoderError(f"File update rejected: {result.get('message') or result['status']}")
    return result


def build_game(
    client: "EduCoderClient",
    task: dict[str, Any],
    login_no: str,
    *,
    update_file_result: dict[str, Any] | None = None,
    homework_common_id: int | str | None = None,
    tab_type: int | None = None,
    first: int = 1,
    content_modified: int | None = None,
    resubmit: str | None = None,
) -> dict[str, Any]:
    """Start server-side evaluation for a task game."""
    game = task.get("game") or {}
    code_editor = task.get("code_editor") or {}
    resolved_homework_id = homework_common_id or task.get("homework_common_id")
    extras = build_task_extras(task, homework_common_id=resolved_homework_id)
    commit_id = extract_commit_id(update_file_result)
    if commit_id:
        extras["commitID"] = commit_id

    update = update_file_result or {}
    if isinstance(update.get("status"), int) and update["status"] < 0:
        raise EduCoderError(f"File update rejected: {update.get('message') or update['status']}")
    payload = {
        "sec_key": update.get("sec_key") or task.get("sec_key"),
        "resubmit": (update.get("resubmit") or "") if resubmit is None else resubmit,
        "first": first,
        "content_modified": update.get("content_modified", 0) if content_modified is None else content_modified,
        "shixun_environment_id": code_editor.get("shixun_environment_id")
        or infer_environment_id(task),
        "tab_type": tab_type if tab_type is not None else infer_tab_type(task),
        "extras": extras,
    }
    return client.request_json(
        "POST",
        f"/api/tasks/{game['identifier']}/game_build.json",
        params={"zzud": login_no},
        json=payload,
        headers={"Referer": _task_referer(str(game["identifier"]))},
    )


def get_game_status(
    client: "EduCoderClient",
    task: dict[str, Any],
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
    sec_key: str | None = None,
    resubmit: str = "",
    time_out: bool = False,
    port: int | str = 0,
) -> dict[str, Any]:
    """Poll evaluation status for a task game."""
    game = task.get("game") or {}
    challenge = task.get("challenge") or {}
    resolved_homework_id = homework_common_id or task.get("homework_common_id")
    params = {
        "resubmit": resubmit,
        "time_out": "true" if time_out else "false",
        "port": port,
        "sec_key": sec_key or task.get("sec_key"),
        "challenge_id": challenge.get("id") or game.get("challenge_id"),
        "subject_id": task.get("subject_id") or "",
        "homework_common_id": resolved_homework_id or "",
        "zzud": login_no,
    }
    return client.request_json(
        "GET",
        f"/api/tasks/{game['identifier']}/game_status.json",
        params=params,
        headers={"Referer": _task_referer(str(game["identifier"]))},
    )


def wait_game_status(
    client: "EduCoderClient",
    task: dict[str, Any],
    login_no: str,
    *,
    homework_common_id: int | str | None = None,
    sec_key: str | None = None,
    resubmit: str = "",
    port: int | str = 0,
    interval: float = 1.0,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Poll game_status.json until evaluation reaches a terminal state."""
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] = {}
    game = task.get("game") or {}
    game_identifier = str(game.get("identifier") or "")
    while time.monotonic() < deadline:
        last_status = get_game_status(
            client,
            task,
            login_no,
            homework_common_id=homework_common_id,
            sec_key=sec_key,
            resubmit=resubmit,
            port=port,
        )
        if task_status_finished(last_status):
            return last_status
        if game_identifier:
            latest_task = get_task(
                client,
                game_identifier,
                login_no,
                homework_common_id=homework_common_id,
            )
            latest_status = task_result_status(latest_task)
            # Task details may still contain the result from before this build.
            if task_status_finished(latest_status) and _task_result_changed(task, latest_task):
                return latest_status
        time.sleep(interval)
    raise TimeoutError(f"Evaluation did not finish in {timeout} seconds: {last_status}")


def task_result_status(task: dict[str, Any]) -> dict[str, Any]:
    """Extract evaluation-result shaped fields from tasks/<game>.json."""
    game = task.get("game") or {}
    status: dict[str, Any] = {
        "status": task.get("status") if task.get("status") is not None else game.get("status"),
        "last_compile_output": task.get("last_compile_output"),
        "test_sets_count": task.get("test_sets_count"),
        "sets_error_count": task.get("sets_error_count"),
        "test_sets": task.get("test_sets"),
        "compile_success": task.get("compile_success"),
        "record_consume_time": task.get("record_consume_time"),
        "next_game": task.get("next_game"),
        "prev_game": task.get("prev_game"),
    }
    return {key: value for key, value in status.items() if value is not None}


def _task_result_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Require changed result evidence, not just a build counter or timestamp."""
    def evidence(task: dict[str, Any]) -> tuple[Any, ...]:
        cases = task.get("test_sets") or []
        return (
            task.get("last_compile_output"), task.get("sets_error_count"),
            [(item.get("result"), item.get("compile_success"), item.get("actual_output"))
             for item in cases if isinstance(item, dict)],
        )
    return evidence(before) != evidence(after)


def evaluate_task_code(
    client: "EduCoderClient",
    game_identifier: str,
    code: str,
    login_no: str,
    *,
    path: str | None = None,
    homework_common_id: int | str | None = None,
    wait: bool = True,
    interval: float = 1.0,
    timeout: float = 120.0,
) -> EvaluationResult:
    """Replace task code, start evaluation, and optionally wait for final status."""
    task = get_task(
        client,
        game_identifier,
        login_no,
        homework_common_id=homework_common_id,
    )
    resolved_path = path or infer_task_path(task)
    update_result = update_task_file(
        client,
        task,
        resolved_path,
        code,
        login_no,
        homework_common_id=homework_common_id,
    )
    build_result = build_game(
        client,
        task,
        login_no,
        update_file_result=update_result,
        homework_common_id=homework_common_id,
    )
    status = (
        wait_game_status(
            client,
            task,
            login_no,
            homework_common_id=homework_common_id,
            sec_key=update_result.get("sec_key") or task.get("sec_key"),
            resubmit=update_result.get("resubmit") or "",
            port=build_result.get("port", 0),
            interval=interval,
            timeout=timeout,
        )
        if wait
        else build_result
    )
    return EvaluationResult(
        task=task,
        update_file=update_result,
        build=build_result,
        status=status,
    )


def report_cost_time(
    client: "EduCoderClient",
    game_identifier: str,
    seconds: int | float,
    login_no: str,
) -> dict[str, Any]:
    """Report time spent on the task page."""
    return client.request_json(
        "POST",
        f"/api/tasks/{game_identifier}/cost_time.json",
        params={"time": int(seconds), "zzud": login_no},
        json={},
        headers={"Referer": _task_referer(game_identifier)},
    )


def build_task_extras(
    task: dict[str, Any],
    *,
    homework_common_id: int | str | None = None,
) -> dict[str, Any]:
    game = task.get("game") or {}
    challenge = task.get("challenge") or {}
    return {
        "exercise_id": "",
        "question_id": "",
        "challenge_id": challenge.get("id") or game.get("challenge_id"),
        "subject_id": task.get("subject_id") or "",
        "homework_common_id": str(homework_common_id or task.get("homework_common_id") or ""),
        "competition_entry_id": "",
        "currentUserId": game.get("user_id") or (task.get("user") or {}).get("user_id"),
    }


def infer_task_path(task: dict[str, Any]) -> str:
    challenge = task.get("challenge") or {}
    path = normalize_task_path(challenge.get("path"))
    if path:
        return path
    raise ValueError("Could not infer task file path; pass path explicitly")


def normalize_task_path(path: Any) -> str:
    if path is None:
        return ""
    normalized = str(path).strip()
    for separator in ("；", ";"):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0]
    return normalized.strip()


def infer_tab_type(task: dict[str, Any]) -> int:
    environments = task.get("shixun_environments") or []
    if environments:
        tab_type = environments[0].get("tab_type")
        if tab_type is not None:
            return int(tab_type)
    return 1


def infer_environment_id(task: dict[str, Any]) -> int | None:
    environments = task.get("shixun_environments") or []
    if environments:
        return environments[0].get("shixun_environment_id")
    return None


def extract_commit_id(update_file_result: dict[str, Any] | None) -> str | None:
    if not update_file_result:
        return None
    for key in ("commitID", "commit_id", "commitId"):
        value = update_file_result.get(key)
        if value:
            return str(value)
    for name in ("content", "data"):
        data = update_file_result.get(name)
        if isinstance(data, dict):
            for key in ("commitID", "commit_id", "commitId"):
                value = data.get(key)
                if value:
                    return str(value)
    return None


def task_status_finished(status: dict[str, Any]) -> bool:
    if isinstance(status.get("status"), (int, float)) and status["status"] < 0:
        return False
    if _evaluation_bool(status.get("compile_success")) is False:
        return True
    test_sets = status.get("test_sets")
    if isinstance(test_sets, list) and test_sets:
        return all(
            isinstance(item, dict) and (
                _evaluation_bool(item.get("result")) is not None
                or _evaluation_bool(item.get("compile_success")) is False
            )
            for item in test_sets
        )
    if status.get("last_compile_output"):
        return True
    if status.get("status") in {2, 3}:
        return True
    if status.get("running_code_status") == 3:
        return True
    return False


def task_passed(status: dict[str, Any]) -> bool:
    if isinstance(status.get("status"), (int, float)) and status["status"] < 0:
        return False
    if _evaluation_bool(status.get("compile_success")) is False:
        return False
    try:
        if status.get("sets_error_count") is not None and int(status["sets_error_count"]) > 0:
            return False
    except (ValueError, TypeError):
        return False
    test_sets = status.get("test_sets")
    if isinstance(test_sets, list) and test_sets:
        try:
            total = int(status.get("test_sets_count") or len(test_sets))
        except (ValueError, TypeError):
            return False
        if total > len(test_sets) and not (status.get("status") == 2 and status.get("sets_error_count") == 0):
            return False
        return all(
            isinstance(item, dict)
            and _evaluation_bool(item.get("result")) is True
            and _evaluation_bool(item.get("compile_success")) is not False
            for item in test_sets
        )
    if status.get("sets_error_count") == 0 and status.get("status") == 2:
        return True
    return False


def _evaluation_bool(value: Any) -> bool | None:
    """Do not treat missing, pending, or the string 'false' as a pass."""
    if isinstance(value, str):
        value = value.strip().lower()
        if value in {"true", "1"}:
            return True
        if value in {"false", "0"}:
            return False
    elif isinstance(value, (bool, int)):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


def summarize_evaluation(status: dict[str, Any]) -> dict[str, Any]:
    """Extract failures from an API result without altering raw input/output.

    Only fields actually returned by the API are used. Locked or invisible
    cases expose their result but never their input, output, or file URLs here.
    ``last_compile_output`` can also be a test summary, not a compiler error.
    """
    cases = []
    raw_cases = status.get("test_sets")
    for index, item in enumerate(raw_cases if isinstance(raw_cases, list) else [], 1):
        if not isinstance(item, dict):
            continue
        passed = _evaluation_bool(item.get("result"))
        compiled = _evaluation_bool(item.get("compile_success"))
        locked = _evaluation_bool(item.get("show_lock"))
        hidden = _evaluation_bool(item.get("is_invisible"))
        restricted = locked is True or hidden is True
        details = {
            "input": item.get("input"),
            "expected_output": item.get("output"),
            "actual_output": item.get("actual_output"),
            "input_file_url": item.get("input_file_url"),
            "expected_output_file_url": item.get("output_file_url"),
        }
        if restricted:
            details = dict.fromkeys(details)
        error_type = "compile_error" if compiled is False else "test_failed" if passed is False else None
        cases.append({
            "index": index,
            "id": item.get("id"),
            "passed": passed,
            "compile_success": compiled,
            "error_type": error_type,
            "locked": locked,
            "hidden": hidden,
            "is_public": _evaluation_bool(item.get("is_public")),
            "is_file": _evaluation_bool(item.get("is_file")),
            "details_available": any(value is not None for value in details.values()),
            **details,
            "ts_time": item.get("ts_time"),
            "ts_mem": item.get("ts_mem"),
            "match_rule": item.get("matchRule"),
        })
    errors = [item for item in cases if item["error_type"] is not None]
    compiled = _evaluation_bool(status.get("compile_success"))
    if any(item["compile_success"] is False for item in cases):
        compiled = False
    elif compiled is None and cases and all(item["compile_success"] is True for item in cases):
        compiled = True
    raw_message = status.get("last_compile_output")
    # Normalize HTML line breaks only in the display message, never in test data.
    message = (
        html.unescape(re.sub(r"\r?<br\s*/?>", "\n", raw_message, flags=re.I))
        if isinstance(raw_message, str) else None
    )
    return {
        "finished": task_status_finished(status),
        "passed": task_passed(status),
        "compile_success": compiled,
        "last_compile_output": raw_message,
        "message": message,
        "test_sets_count": status.get("test_sets_count"),
        "sets_error_count": status.get("sets_error_count"),
        "record_consume_time": status.get("record_consume_time"),
        "test_sets": cases,
        "errors": errors,
        "visible_error_count": sum(item["details_available"] for item in errors),
        "restricted_error_count": sum(item["locked"] is True or item["hidden"] is True for item in errors),
    }


def _task_referer(game_identifier: str) -> str:
    return f"https://www.educoder.net/tasks/{game_identifier}"
