"""Reusable Python client for EduCoder (头歌).

The package is intended to be imported by scripts that need to log in to
EduCoder, list classrooms, inspect classroom shixun homework, read task
content, replace task files, and submit/evaluate code through API calls.

Quick start:

    from educoder import EduCoderClient

    client = EduCoderClient.from_dotenv()
    client.ensure_logged_in()

    courses = client.courses.items()
    homeworks = client.shixun_homeworks.summaries(
        "3nqjzf9h",
        states=["未全部完成", "已截止"],
        match="all",
    )

Common entry points:

    EduCoderClient.from_dotenv()
        Create a client from .env credentials.

    client.courses.items()
        Get classrooms for the logged-in user.

    client.courses.module_items(course_identifier)
        Get available classroom modules.

    client.shixun_homeworks.summaries(course_identifier, ...)
        List classroom experiments with local filters.

    client.shixun_homeworks.challenge_summaries_for_course(...)
        Find unpassed or unevaluated challenge tasks across a classroom.

    client.shixun_homeworks.shixun_info(shixun_identifier, myshixun_identifier=...)
        Get shixun skip policy (allow_skip) and per-challenge unlock state.

    client.tasks.content(game_identifier, ...)
        Get structured task text and ordered images.

    client.tasks.evaluate_code(game_identifier, code, ...)
        Replace code, build, and wait for evaluation; inspect result.errors.

    client.tasks.diagnostics(game_identifier, ...)
        Read stored evaluation failures without submitting; respect test locks.

    summarize_evaluation(status)
        Parse an existing API response into structured test results and errors.

    ShixunSolver(client, bank).solve_shixun(course_identifier, homework_id, ...)
        Exact-bank/DeepSeek tool-call solving, ordered images, repair context,
        skip-aware scheduling, and verified answer persistence. See example.py.

    submission_tool()
        Get the submit_code(full_code=...) function schema for an AI client.
        Only full-file replacements are accepted, not snippets or patches.

    QuestionBank(db_path).match(stem_text, images=ordered_image_bytes)
        Match full normalized question text and identical ordered image bytes.

    QuestionBank(db_path).add(title=..., stem_text=..., answer_text=..., images=...)
        Add or update questions offline; preserve original answers verbatim.

    client.answer_bank.match_task(game_identifier, homework_common_id=...)
        Fetch a task and its images, then match the local bank without submitting.

Useful filter states:

    未通过 / unpassed
    未评测 / unevaluated
    未全部完成 / not_all_completed
    已截止 / ended
    提交中 / submitting
    补交中 / late
    已归档 / archived

Command line:

    python -m educoder --help
    educoder --help
"""

from __future__ import annotations

from typing import Any

from .answer_bank import (
    DEFAULT_DB_PATH,
    AmbiguousAnswerError,
    AnswerBankAPI,
    BuildStats,
    QuestionBank,
    build_current_user_question_bank,
    normalize_question_text,
    fetch_question_images,
)
from .auth import API_BASE, CACHE_DIR, DEFAULT_TIMEOUT, build_edu_headers, extract_keys
from .client import EduCoderClient
from .deepseek import (
    DeepSeekConfig, DeepSeekConversation, DeepSeekError, InvalidAnswerError,
    SubmissionToolCall, submission_tool,
)
from .solver import ShixunSolver, SubmissionGate
from .courses import (
    CourseQuery,
    CoursesAPI,
    course_summary,
    extract_course_identifier,
    get_course_modules,
    get_user_courses,
    module_summary,
)
from .env import credentials_from_env, load_env_file
from .exceptions import EduCoderError
from .shixun_homeworks import (
    SHIXUN_HOMEWORK_TYPE,
    ShixunHomeworkFilter,
    ShixunHomeworkPage,
    ShixunHomeworkQuery,
    ShixunHomeworkResource,
    ShixunHomeworksAPI,
    StudentWorkQuery,
    challenge_state_tags,
    enrich_shixun_info_with_homework_challenge_data,
    filter_homeworks,
    filter_challenges,
    get_all_shixun_homeworks,
    get_shixun_challenge_data,
    get_shixun_homework_detail,
    get_shixun_homework_header,
    get_shixun_homeworks,
    get_shixun_info,
    get_shixun_student_work,
    get_myshixun_challenges,
    homework_matches_filter,
    homework_state_tags,
    is_archived,
    is_ended,
    is_finished,
    is_late,
    is_not_all_completed,
    is_submitting,
    is_unevaluated,
    is_unpassed,
    normalize_state_names,
    parse_chinese_duration_seconds,
    summarize_challenge,
    summarize_homework_detail_page,
    summarize_homework,
    summarize_shixun_challenges,
    summarize_skip_policy,
)
from .tasks import (
    EvaluationResult,
    TasksAPI,
    build_game,
    decode_task_file_content,
    download_task_images,
    embed_task_images_base64,
    enter_shixun,
    evaluate_task_code,
    get_game_status,
    get_task,
    get_task_file_content,
    normalize_task_path,
    parse_markdown_blocks,
    report_cost_time,
    structure_task_content,
    summarize_evaluation,
    task_passed,
    task_result_status,
    task_status_finished,
    update_task_file,
    wait_game_status,
)


def login_from_env(*, dotenv_path: str | None = ".env", **kwargs: Any) -> EduCoderClient:
    """Create a client from environment variables, log in, and return it."""
    if dotenv_path:
        load_env_file(dotenv_path)
    client = EduCoderClient.from_env(**kwargs)
    client.login()
    return client


def login_from_dotenv(path: str = ".env", **kwargs: Any) -> EduCoderClient:
    """Create a client from a .env file, log in, and return it."""
    return login_from_env(dotenv_path=path, **kwargs)


__all__ = [
    "DeepSeekConfig",
    "DeepSeekConversation",
    "DeepSeekError",
    "InvalidAnswerError",
    "SubmissionToolCall",
    "submission_tool",
    "ShixunSolver",
    "SubmissionGate",
    "API_BASE",
    "CACHE_DIR",
    "DEFAULT_DB_PATH",
    "DEFAULT_TIMEOUT",
    "AnswerBankAPI",
    "AmbiguousAnswerError",
    "BuildStats",
    "CourseQuery",
    "CoursesAPI",
    "EduCoderClient",
    "EduCoderError",
    "EvaluationResult",
    "QuestionBank",
    "SHIXUN_HOMEWORK_TYPE",
    "ShixunHomeworkFilter",
    "ShixunHomeworkPage",
    "ShixunHomeworkQuery",
    "ShixunHomeworkResource",
    "ShixunHomeworksAPI",
    "StudentWorkQuery",
    "TasksAPI",
    "build_game",
    "build_current_user_question_bank",
    "build_edu_headers",
    "challenge_state_tags",
    "course_summary",
    "credentials_from_env",
    "decode_task_file_content",
    "download_task_images",
    "embed_task_images_base64",
    "enter_shixun",
    "enrich_shixun_info_with_homework_challenge_data",
    "evaluate_task_code",
    "extract_course_identifier",
    "extract_keys",
    "filter_challenges",
    "filter_homeworks",
    "get_all_shixun_homeworks",
    "get_course_modules",
    "get_game_status",
    "get_shixun_challenge_data",
    "get_shixun_homework_detail",
    "get_shixun_homework_header",
    "get_shixun_homeworks",
    "get_shixun_info",
    "get_shixun_student_work",
    "get_user_courses",
    "get_myshixun_challenges",
    "get_task",
    "get_task_file_content",
    "homework_matches_filter",
    "homework_state_tags",
    "is_archived",
    "is_ended",
    "is_finished",
    "is_late",
    "is_not_all_completed",
    "is_submitting",
    "is_unevaluated",
    "is_unpassed",
    "load_env_file",
    "login_from_dotenv",
    "login_from_env",
    "module_summary",
    "normalize_state_names",
    "normalize_question_text",
    "normalize_task_path",
    "parse_markdown_blocks",
    "fetch_question_images",
    "parse_chinese_duration_seconds",
    "report_cost_time",
    "structure_task_content",
    "summarize_challenge",
    "summarize_homework_detail_page",
    "summarize_homework",
    "summarize_shixun_challenges",
    "summarize_skip_policy",
    "task_passed",
    "task_result_status",
    "summarize_evaluation",
    "task_status_finished",
    "update_task_file",
    "wait_game_status",
]
