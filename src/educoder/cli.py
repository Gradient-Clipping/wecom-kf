"""Command-line help for the educoder package."""

from __future__ import annotations

import argparse
import sys
import textwrap
from typing import Sequence


HELP_EPILOG = """\
Python API examples:

  from educoder import EduCoderClient

  client = EduCoderClient.from_dotenv()
  client.ensure_logged_in()

  # Classrooms
  courses = client.courses.items()
  modules = client.courses.module_items("3nqjzf9h")

  # Classroom shixun homework
  homeworks = client.shixun_homeworks.summaries("3nqjzf9h")

  unfinished_ended = client.shixun_homeworks.summaries(
      "3nqjzf9h",
      states=["未全部完成", "已截止"],
      match="all",
  )

  # Challenge tasks inside classroom shixun homework
  pending_tasks = client.shixun_homeworks.challenge_summaries_for_course(
      "3nqjzf9h",
      homework_states=["未全部完成", "已截止"],
      homework_match="all",
      challenge_states=["未通过", "未评测"],
      challenge_match="any",
  )

  # One task runtime page
  content = client.tasks.content(
      "kifu54as6h29",
      homework_common_id=3802969,
      download_images_to="images",
  )

  result = client.tasks.evaluate_code(
      "kifu54as6h29",
      code,
      homework_common_id=3802969,
  )
  print(result.errors)
  print(result.diagnostics["message"])

  # Read the last stored result without submitting again
  diagnostics = client.tasks.diagnostics(
      "kifu54as6h29", homework_common_id=3802969,
  )

  # Match full question text and ordered image bytes
  from educoder import QuestionBank
  bank = QuestionBank("educoder_question_bank.sqlite")
  answer = bank.find_answer(stem_text, images=ordered_image_bytes)

  # Add or update text answers entirely offline
  bank.add(shixun_title="实训名", title="题目名",
           stem_text=stem_text, answer_text=code, images=ordered_image_bytes)

  # Fetch one live task and perform the same exact local match
  matched = client.answer_bank.match_task(game_identifier, homework_common_id=homework_id)

Filter states:

  Chinese: 未通过, 未评测, 未全部完成, 已截止, 提交中, 补交中, 已归档
  English: unpassed, unevaluated, not_all_completed, ended, submitting, late, archived

Important objects:

  EduCoderClient
    Authenticated reusable API client. Use from_dotenv() or from_env().

  client.courses
    Classroom list and classroom module APIs.

  client.shixun_homeworks
    Classroom experiment list, detail, challenge data, and filters.

  client.tasks
    Runtime task APIs: enter shixun, read content/images, update files, build, poll status.

More interactive help:

  python - <<'PY'
  import educoder
  help(educoder)
  PY

  python - <<'PY'
  from educoder import EduCoderClient
  help(EduCoderClient)
  PY
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="educoder",
        description=(
            "Reusable Python client for EduCoder APIs. "
            "Use answer-bank for exact offline matching and text imports; "
            "use the Python API for classrooms and evaluation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(HELP_EPILOG),
    )
    parser.add_argument(
        "--version",
        action="version",
        version="educoder-client 0.1.0",
    )
    subparsers = parser.add_subparsers(dest="command")

    bank = subparsers.add_parser(
        "answer-bank",
        help="Build or query the offline SQLite answer/question bank.",
    )
    bank_subparsers = bank.add_subparsers(dest="answer_bank_command")

    bank_build = bank_subparsers.add_parser(
        "build",
        help="Import completed saved tasks and their images from the current account.",
    )
    bank_build.add_argument("--db", default="educoder_question_bank.sqlite")
    bank_build.add_argument("--verbose", action="store_true")
    bank_build.set_defaults(func=run_answer_bank_build)

    bank_search = bank_subparsers.add_parser(
        "search",
        help="Find exact full-stem and ordered-image matches offline.",
    )
    bank_search.add_argument("--stem-file", required=True, help="UTF-8 full question text file.")
    bank_search.add_argument("--images", nargs="*", default=[], help="Image files in stem order.")
    bank_search.add_argument("--db", default="educoder_question_bank.sqlite")
    bank_search.set_defaults(func=run_answer_bank_search)

    bank_add = bank_subparsers.add_parser("add", help="Add/update text questions and answers offline.")
    bank_add.add_argument("--entries-json", required=True, help="JSON/JSONL entries: title, stem_text, answer_text, optional shixun_title/images.")
    bank_add.add_argument("--db", default="educoder_question_bank.sqlite")
    bank_add.set_defaults(func=run_answer_bank_add)

    bank_list = bank_subparsers.add_parser("list", help="Browse stored titles, without matching answers.")
    bank_list.add_argument("--title")
    bank_list.add_argument("--shixun-title")
    bank_list.add_argument("--db", default="educoder_question_bank.sqlite")
    bank_list.set_defaults(func=run_answer_bank_list)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return int(func(args) or 0)


def run_answer_bank_build(args: argparse.Namespace) -> int:
    from .client import EduCoderClient

    client = EduCoderClient.from_dotenv(override=True, verbose=args.verbose)
    try:
        stats = client.answer_bank.build(db_path=args.db, verbose=args.verbose)
    finally:
        client.session.close()
    print("Question bank built:", stats.as_dict())
    print(f"SQLite: {args.db}")
    return 1 if stats.errors else 0


def run_answer_bank_search(args: argparse.Namespace) -> int:
    from pathlib import Path
    from .answer_bank import QuestionBank

    bank = QuestionBank(args.db)
    results = bank.search(
        Path(args.stem_file).read_bytes().decode("utf-8"),
        images=[Path(path) for path in args.images],
    )
    if not results:
        print("No matching answer found.")
        return 1
    for index, item in enumerate(results, start=1):
        print(
            f"{index}. exact match: "
            f"title={item.get('shixun_title')} / {item.get('title')}"
        )
        print(item.get("answer_text") or "")
    return 0


def run_answer_bank_add(args: argparse.Namespace) -> int:
    from pathlib import Path
    from .answer_bank import QuestionBank

    entries = load_answer_entries(args.entries_json)
    base = Path(args.entries_json).resolve().parent
    for entry in entries:
        entry["images"] = [base / image if isinstance(image, str) else image
                           for image in entry.get("images", [])]
    bank = QuestionBank(args.db) if Path(args.db).exists() else QuestionBank.create(args.db)
    print("Saved question IDs:", bank.add_many(entries))
    return 0


def run_answer_bank_list(args: argparse.Namespace) -> int:
    from .answer_bank import QuestionBank
    for item in QuestionBank(args.db).list(title=args.title, shixun_title=args.shixun_title):
        print(f"{item['id']}. {item['shixun_title']} / {item['title']}")
    return 0


def load_answer_entries(path: str) -> list[dict[str, object]]:
    import json
    from pathlib import Path

    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("Expected a JSON object, array of objects, or JSONL objects")
    return data


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
