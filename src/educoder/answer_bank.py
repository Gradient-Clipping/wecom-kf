"""Offline question bank with exact normalized stems and ordered image bytes."""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

from .courses import extract_course_identifier
from .tasks import find_task_image_tokens, parse_markdown_blocks

if TYPE_CHECKING:
    from .client import EduCoderClient


DEFAULT_DB_PATH = "educoder_question_bank.sqlite"
SCHEMA_VERSION = 2


def normalize_question_text(text: str) -> str:
    """Normalize width, removing whitespace and zero-width format characters.

    Case, punctuation, digits and mathematical symbols remain significant.
    Limit compatibility normalization to width mappings: x² must not equal x2.
    This function must never be applied to stored answers.
    """
    converted = "".join(
        unicodedata.normalize("NFKC", char)
        if unicodedata.decomposition(char).startswith(("<wide>", "<narrow>"))
        else char
        for char in text
    )
    return "".join(
        char for char in converted
        if not char.isspace()
        and unicodedata.category(char) != "Cf"
        and char != "\u034f"
    )


def stem_identity(stem_text: str) -> tuple[str, list[dict[str, Any]]]:
    """Replace image markup with position markers; compare its bytes separately."""
    if not isinstance(stem_text, str) or not normalize_question_text(stem_text):
        raise ValueError("A nonempty full stem_text is required")
    parts: list[Any] = []
    images: list[dict[str, Any]] = []
    cursor = 0
    for token in find_task_image_tokens(stem_text, strict=True):
        parts.append(normalize_question_text(stem_text[cursor:token["start"]]))
        parts.append({"image": len(images) + 1})
        images.append(dict(token["image"], index=len(images) + 1))
        cursor = token["end"]
    parts.append(normalize_question_text(stem_text[cursor:]))
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":")), images


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _image_bytes(image: Any) -> bytes:
    """Accept bytes, a local Path, or a tasks.content image dictionary."""
    if isinstance(image, (bytes, bytearray, memoryview)):
        data = bytes(image)
    elif isinstance(image, Path):
        data = image.read_bytes()
    elif isinstance(image, dict):
        if image.get("content") is not None:
            data = bytes(image["content"])
        elif image.get("base64") is not None:
            data = base64.b64decode(image["base64"], validate=True)
        elif image.get("data_url") is not None:
            header, payload = image["data_url"].split(",", 1)
            if (not header.startswith(("data:image/", "data:application/octet-stream;"))
                    or not header.endswith(";base64")):
                raise ValueError("Expected a base64 image data URL")
            data = base64.b64decode(payload, validate=True)
        elif image.get("local_path") is not None:
            data = Path(image["local_path"]).read_bytes()
        else:
            raise ValueError("Image bytes are required; a URL or hash alone is insufficient")
    else:
        raise TypeError("Each image must contain bytes, a Path, or an image dictionary")
    if not data:
        raise ValueError("Empty image data")
    return data


def _prepare(stem_text: str, images: Iterable[Any]) -> tuple[str, str, list[dict[str, Any]]]:
    stem_key, references = stem_identity(stem_text)
    supplied = list(images)
    if len(supplied) != len(references):
        raise ValueError(f"Stem has {len(references)} images; received {len(supplied)}")
    prepared = []
    for index, (reference, image) in enumerate(zip(references, supplied), 1):
        if isinstance(image, dict):
            declared_index = image.get("index", image.get("image_index", index))
            if int(declared_index) != index:
                raise ValueError("Images must be supplied in stem order")
        data = _image_bytes(image)
        mime = image.get("content_type") if isinstance(image, dict) else None
        if not mime and isinstance(image, dict) and image.get("data_url"):
            mime = image["data_url"].split(";", 1)[0][5:]
        prepared.append({
            "index": index,
            "url": reference["url"],
            "alt": reference.get("alt", ""),
            "content_type": mime or "application/octet-stream",
            "sha256": _digest(data),
            "content": data,
        })
    image_key = json.dumps([item["sha256"] for item in prepared], separators=(",", ":"))
    return stem_key, image_key, prepared


class AmbiguousAnswerError(ValueError):
    """An identical stem and images have conflicting stored answers."""


class QuestionBank:
    """Pure local question storage. Matching never logs in or downloads images.

    bank.add(title=..., stem_text=..., answer_text=..., images=[image_bytes])
    bank.match(stem_text, images=[image_bytes]) -> question or None
    bank.find_answer(stem_text, images=[image_bytes]) -> answer or None
    Titles are stored for display and browsing, not as proof of a match.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path).resolve()

    @classmethod
    def create(cls, db_path: str | Path = DEFAULT_DB_PATH) -> "QuestionBank":
        """Create a new bank. Existing files are never reset implicitly."""
        bank = cls(db_path)
        bank.db_path.parent.mkdir(parents=True, exist_ok=True)
        with bank.db_path.open("xb"):
            pass
        conn = sqlite3.connect(bank.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        finally:
            conn.close()
        return bank

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        mode = "rw" if write else "ro"
        conn = sqlite3.connect(self.db_path.as_uri() + f"?mode={mode}", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise ValueError("Unsupported question bank schema; migrate the database first")
            with conn:
                yield conn
        finally:
            conn.close()

    def add(
        self, *, title: str, stem_text: str, answer_text: str,
        shixun_title: str = "", images: Iterable[Any] = (),
    ) -> int:
        """Insert a question or update its answer. Preserve original text exactly."""
        if not isinstance(title, str) or not normalize_question_text(title):
            raise ValueError("A nonempty title is required")
        if not isinstance(answer_text, str) or not answer_text.strip():
            raise ValueError("A nonempty answer_text is required")
        stem_key, image_key, prepared = _prepare(stem_text, images)
        title_key = normalize_question_text(title)
        shixun_key = normalize_question_text(shixun_title)
        stem_hash = _digest(stem_key.encode("utf-8"))
        with self.connect(write=True) as conn:
            conn.execute(
                """INSERT INTO question_bank (
                    shixun_title, shixun_title_key, title, title_key,
                    stem_text, stem_key, stem_sha256, image_key, stem_blocks_json,
                    answer_text, answer_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shixun_title_key, title_key, stem_sha256, image_key)
                DO UPDATE SET shixun_title=excluded.shixun_title, title=excluded.title,
                    stem_text=excluded.stem_text, stem_key=excluded.stem_key,
                    stem_blocks_json=excluded.stem_blocks_json,
                    answer_text=excluded.answer_text, answer_sha256=excluded.answer_sha256""",
                (shixun_title, shixun_key, title, title_key, stem_text, stem_key,
                 stem_hash, image_key, json.dumps(parse_markdown_blocks(stem_text), ensure_ascii=False),
                 answer_text, _digest(answer_text.encode("utf-8"))),
            )
            question_id = conn.execute(
                """SELECT id FROM question_bank WHERE shixun_title_key=? AND title_key=?
                   AND stem_sha256=? AND image_key=?""",
                (shixun_key, title_key, stem_hash, image_key),
            ).fetchone()[0]
            conn.execute("DELETE FROM question_images WHERE question_id=?", (question_id,))
            conn.executemany(
                """INSERT INTO question_images
                   (question_id, image_index, url, alt, content_type, sha256, image_blob)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [(question_id, im["index"], im["url"], im["alt"], im["content_type"],
                  im["sha256"], im["content"]) for im in prepared],
            )
        return int(question_id)

    def add_many(self, entries: Iterable[dict[str, Any]]) -> list[int]:
        """Add dictionaries with title, stem_text, answer_text, and optional images."""
        return [self.add(**entry) for entry in entries]

    def search(self, stem_text: str, *, images: Iterable[Any] = ()) -> list[dict[str, Any]]:
        """Return only exact full-stem/image matches, with no scores or fallback."""
        stem_key, image_key, prepared = _prepare(stem_text, images)
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM question_bank WHERE stem_sha256=?
                   AND image_key=? AND stem_key=? ORDER BY id""",
                (_digest(stem_key.encode("utf-8")), image_key, stem_key),
            ).fetchall()
            results = []
            for row in rows:
                stored = conn.execute(
                    "SELECT image_blob FROM question_images WHERE question_id=? ORDER BY image_index",
                    (row["id"],),
                ).fetchall()
                if [im[0] for im in stored] == [im["content"] for im in prepared]:
                    results.append(_question_result(row))
        return results

    def match(self, stem_text: str, *, images: Iterable[Any] = ()) -> dict[str, Any] | None:
        """Return an exact match, rejecting conflicting answers for identical input."""
        results = self.search(stem_text, images=images)
        if not results:
            return None
        if len({row["answer_text"] for row in results}) != 1:
            raise AmbiguousAnswerError("Identical question content has conflicting answers")
        return results[0]

    def find_answer(self, stem_text: str, *, images: Iterable[Any] = ()) -> str | None:
        result = self.match(stem_text, images=images)
        return result["answer_text"] if result else None

    def get(self, question_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM question_bank WHERE id=?", (question_id,)).fetchone()
        return _question_result(row) if row else None

    def list(self, *, title: str | None = None, shixun_title: str | None = None) -> list[dict[str, Any]]:
        """Browse stored titles; this does not determine answer reusability."""
        clauses, values = [], []
        for column, value in (("title_key", title), ("shixun_title_key", shixun_title)):
            if value is not None:
                clauses.append(f"{column}=?")
                values.append(normalize_question_text(value))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute("SELECT id, shixun_title, title FROM question_bank" + where + " ORDER BY id", values)
            return [dict(row) for row in rows]

    def get_images(self, question_id: int, *, image_format: str = "bytes") -> list[dict[str, Any]]:
        """Read ordered image bytes, base64, data_url or metadata from SQLite."""
        if image_format not in {"bytes", "base64", "data_url", "metadata"}:
            raise ValueError("image_format must be bytes, base64, data_url or metadata")
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM question_images WHERE question_id=? ORDER BY image_index",
                (question_id,),
            ).fetchall()
        images = []
        for row in rows:
            item = {"index": row["image_index"], "url": row["url"], "alt": row["alt"],
                    "content_type": row["content_type"], "sha256": row["sha256"]}
            blob = row["image_blob"]
            if image_format == "bytes":
                item["content"] = blob
            elif image_format in {"base64", "data_url"}:
                encoded = base64.b64encode(blob).decode("ascii")
                item[image_format] = (f"data:{row['content_type']};base64,{encoded}"
                                      if image_format == "data_url" else encoded)
            images.append(item)
        return images


def _question_result(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "shixun_title": row["shixun_title"], "title": row["title"],
            "stem_text": row["stem_text"], "stem_blocks": json.loads(row["stem_blocks_json"]),
            "answer_text": row["answer_text"]}


def fetch_question_images(client: "EduCoderClient", stem_text: str) -> list[dict[str, Any]]:
    """Fetch actual image bytes at the explicit online boundary."""
    _, references = stem_identity(stem_text)
    cache: dict[str, tuple[bytes, str]] = {}
    result = []
    for reference in references:
        url = reference["url"]
        if url not in cache:
            if url.startswith("data:image/"):
                cache[url] = (_image_bytes({"data_url": url}), url[5:].split(";", 1)[0])
            else:
                # Task assets on another host must not receive EduCoder credentials.
                from urllib.parse import urlparse
                import requests
                if urlparse(url).netloc == urlparse(client.api_base).netloc:
                    response = client.request("GET", url)
                else:
                    response = requests.get(url, timeout=client.timeout)
                try:
                    response.raise_for_status()
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0]
                    if not mime.startswith("image/"):
                        raise ValueError("Image URL did not return image content")
                    cache[url] = (response.content, mime)
                finally:
                    response.close()
        data, mime = cache[url]
        result.append(dict(reference, content=data, content_type=mime))
    return result


class AnswerBankAPI:
    """Online acquisition followed by the same offline exact matcher."""

    def __init__(self, client: "EduCoderClient") -> None:
        self.client = client

    def open(self, db_path: str | Path = DEFAULT_DB_PATH) -> QuestionBank:
        return QuestionBank(db_path)

    def match_task(self, game_identifier: str, *, homework_common_id: int | str | None = None,
                   db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any] | None:
        content = self.client.tasks.content(game_identifier, homework_common_id=homework_common_id)
        images = fetch_question_images(self.client, content["raw"])
        return self.open(db_path).match(content["raw"], images=images)

    def build(self, *, db_path: str | Path = DEFAULT_DB_PATH, verbose: bool = False) -> "BuildStats":
        return build_current_user_question_bank(self.client, db_path=db_path, verbose=verbose)


@dataclass(slots=True)
class BuildStats:
    questions: int = 0
    images: int = 0
    skipped: int = 0
    errors: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def build_current_user_question_bank(client: "EduCoderClient", *,
                                    db_path: str | Path = DEFAULT_DB_PATH,
                                    verbose: bool = False) -> BuildStats:
    """Explicitly import completed saved tasks with their full stems and images."""
    bank = QuestionBank(db_path) if Path(db_path).exists() else QuestionBank.create(db_path)
    stats = BuildStats()
    client.ensure_logged_in()
    page = 1
    seen = set()
    while True:
        courses = client.courses.items(page=page, per_page=50)
        fresh = [c for c in courses if c.get("id") not in seen]
        if not fresh:
            break
        seen.update(c.get("id") for c in fresh)
        for course in fresh:
            cid = extract_course_identifier(course)
            if not cid:
                continue
            for homework in client.shixun_homeworks.list_all(cid).get("homeworks") or []:
                hid = homework.get("homework_id")
                try:
                    info = client.shixun_homeworks.homework(cid, hid).shixun_info()
                    for challenge in info.get("challenge_list") or []:
                        if not challenge.get("finished") or not challenge.get("game_identifier"):
                            stats.skipped += 1
                            continue
                        try:
                            game = challenge["game_identifier"]
                            content = client.tasks.content(game, homework_common_id=hid)
                            code = client.tasks.read_file(game, content["path"], homework_common_id=hid)
                            images = fetch_question_images(client, content["raw"])
                            bank.add(shixun_title=homework.get("shixun_name") or homework.get("name") or "",
                                     title=content["challenge_name"], stem_text=content["raw"],
                                     answer_text=code, images=images)
                            stats.questions += 1
                            stats.images += len(images)
                        except Exception as exc:
                            stats.errors += 1
                            if verbose:
                                print(f"[error] {challenge.get('name')}: {type(exc).__name__}")
                except Exception as exc:
                    stats.errors += 1
                    if verbose:
                        print(f"[error] {homework.get('name')}: {type(exc).__name__}")
        if len(courses) < 50:
            break
        page += 1
    return stats


_SCHEMA = """
CREATE TABLE question_bank (
    id INTEGER PRIMARY KEY,
    shixun_title TEXT NOT NULL,
    shixun_title_key TEXT NOT NULL,
    title TEXT NOT NULL,
    title_key TEXT NOT NULL,
    stem_text TEXT NOT NULL,
    stem_key TEXT NOT NULL,
    stem_sha256 TEXT NOT NULL,
    image_key TEXT NOT NULL,
    stem_blocks_json TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    answer_sha256 TEXT NOT NULL,
    UNIQUE(shixun_title_key, title_key, stem_sha256, image_key)
);
CREATE TABLE question_images (
    question_id INTEGER NOT NULL REFERENCES question_bank(id) ON DELETE CASCADE,
    image_index INTEGER NOT NULL CHECK(image_index > 0),
    url TEXT NOT NULL,
    alt TEXT NOT NULL,
    content_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    image_blob BLOB NOT NULL CHECK(length(image_blob) > 0),
    PRIMARY KEY(question_id, image_index)
);
CREATE INDEX idx_question_content ON question_bank(stem_sha256, image_key);
CREATE INDEX idx_question_title ON question_bank(title_key);
"""
