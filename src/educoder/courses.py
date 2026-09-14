"""Course and classroom module APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .utils import display

if TYPE_CHECKING:
    from .client import EduCoderClient


@dataclass(slots=True)
class CourseQuery:
    category: str = ""
    status: str = ""
    page: int = 1
    per_page: int = 15
    sort_by: str = "updated_at"
    sort_direction: str = "desc"


class CoursesAPI:
    """High-level course APIs bound to an authenticated client."""

    def __init__(self, client: "EduCoderClient") -> None:
        self.client = client

    def list(
        self,
        login_no: str | None = None,
        *,
        query: CourseQuery | None = None,
        category: str | None = None,
        status: str | None = None,
        page: int | None = None,
        per_page: int | None = None,
        sort_by: str | None = None,
        sort_direction: str | None = None,
    ) -> dict[str, Any]:
        login_no = login_no or self._login_no()
        return get_user_courses(
            self.client,
            login_no,
            query=query,
            category=category,
            status=status,
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_direction=sort_direction,
        )

    def items(self, login_no: str | None = None, **kwargs: Any) -> list[dict[str, Any]]:
        return self.list(login_no, **kwargs).get("courses") or []

    def modules(
        self,
        course_identifier: str,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return get_course_modules(
            self.client,
            course_identifier,
            login_no or self._login_no(),
        )

    def module_items(
        self,
        course_identifier: str,
        login_no: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.modules(course_identifier, login_no).get("course_modules") or []

    def first_identifier(self, login_no: str | None = None) -> str | None:
        for course in self.items(login_no, per_page=1):
            identifier = extract_course_identifier(course)
            if identifier:
                return identifier
        return None

    def _login_no(self) -> str:
        user_info = self.client.ensure_logged_in()
        login_no = user_info.get("login")
        if not login_no:
            raise ValueError("Could not determine EduCoder login number")
        return str(login_no)


def get_user_courses(
    client: "EduCoderClient",
    login_no: str,
    *,
    query: CourseQuery | None = None,
    category: str | None = None,
    status: str | None = None,
    page: int | None = None,
    per_page: int | None = None,
    sort_by: str | None = None,
    sort_direction: str | None = None,
) -> dict[str, Any]:
    """Fetch /api/users/<login_no>/courses.json."""
    query = query or CourseQuery()
    effective_category = query.category if category is None else category
    effective_status = query.status if status is None else status
    effective_page = query.page if page is None else page
    effective_per_page = query.per_page if per_page is None else per_page
    effective_sort_by = query.sort_by if sort_by is None else sort_by
    effective_sort_direction = (
        query.sort_direction if sort_direction is None else sort_direction
    )

    params = {
        "category": effective_category,
        "status": effective_status,
        "page": effective_page,
        "per_page": effective_per_page,
        "sort_by": effective_sort_by,
        "sort_direction": effective_sort_direction,
        "username": login_no,
        "zzud": login_no,
    }
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": f"https://www.educoder.net/users/{login_no}/classrooms?status={effective_status}",
    }
    return client.request_json(
        "GET",
        f"/api/users/{login_no}/courses.json",
        params=params,
        headers=headers,
    )


def extract_course_identifier(course: dict[str, Any]) -> str | None:
    """Extract qyc4o7z5 from a URL such as /classrooms/qyc4o7z5/announcement."""
    for key in ("first_category_url", "category_url"):
        url = course.get(key)
        if not url:
            continue
        match = re.search(r"/classrooms/([^/]+)/", str(url))
        if match:
            return match.group(1)
    return None


def get_course_modules(
    client: "EduCoderClient",
    course_identifier: str,
    login_no: str,
) -> dict[str, Any]:
    """Fetch /api/courses/<course_identifier>/left_banner.json."""
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": f"https://www.educoder.net/classrooms/{course_identifier}/announcement",
    }
    return client.request_json(
        "GET",
        f"/api/courses/{course_identifier}/left_banner.json",
        params={"id": course_identifier, "zzud": login_no},
        headers=headers,
    )


def course_summary(course: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary for one course item."""
    teacher = course.get("teacher") or {}
    return {
        "id": course.get("id"),
        "identifier": extract_course_identifier(course),
        "name": course.get("name"),
        "school": course.get("school"),
        "teacher": teacher.get("real_name"),
        "members_count": course.get("members_count"),
        "homework_commons_count": course.get("homework_commons_count"),
        "visits": course.get("visits"),
        "is_end": course.get("is_end"),
        "first_category_url": course.get("first_category_url"),
    }


def module_summary(module: dict[str, Any]) -> dict[str, Any]:
    """Return a compact summary for one course module."""
    return {
        "id": module.get("id"),
        "name": module.get("name"),
        "init_name": module.get("init_name"),
        "type": module.get("type"),
        "position": module.get("position"),
        "main_id": module.get("main_id"),
        "category_url": module.get("category_url"),
        "second_category": module.get("second_category") or [],
    }


def print_course_summary(
    data: dict[str, Any],
    *,
    page: int = 1,
    per_page: int = 15,
    module_banners: dict[str, dict[str, Any]] | None = None,
    show_hidden_modules: bool = False,
) -> None:
    """Optional human-readable course summary printer."""
    courses = data.get("courses") or []
    count = data.get("count", len(courses))
    print(f"Courses: count={count}, page={page}, per_page={per_page}")
    if not courses:
        print("No courses found.")
        return

    for index, course in enumerate(courses, start=1):
        summary = course_summary(course)
        ended = "ended" if summary["is_end"] else "active"
        print(
            f"{index}. id={display(summary['id'])}, "
            f"identifier={display(summary['identifier'])}, "
            f"name={display(summary['name'])}, "
            f"school={display(summary['school'])}, "
            f"teacher={display(summary['teacher'])}, "
            f"members={display(summary['members_count'])}, "
            f"homeworks={display(summary['homework_commons_count'])}, "
            f"visits={display(summary['visits'])}, "
            f"status={ended}"
        )
        if module_banners and summary["identifier"] in module_banners:
            print_course_modules(
                module_banners[summary["identifier"]],
                show_hidden_modules=show_hidden_modules,
            )


def print_course_modules(
    banner: dict[str, Any],
    *,
    indent: str = "   ",
    show_hidden_modules: bool = False,
) -> None:
    """Optional human-readable course module printer."""
    modules = banner.get("course_modules") or []
    hidden_modules = banner.get("hidden_modules") or []
    if not modules:
        print(f"{indent}Modules: none")
    else:
        print(f"{indent}Modules:")
        for module in modules:
            print(
                f"{indent}- {display(module.get('name'))} "
                f"(type={display(module.get('type'))}, "
                f"url={display(module.get('category_url'))})"
            )
            for child in module.get("second_category") or []:
                child_name = child.get("category_name") or child.get("name")
                print(
                    f"{indent}  - {display(child_name)} "
                    f"(type={display(child.get('category_type'))}, "
                    f"url={display(child.get('second_category_url'))})"
                )

    if show_hidden_modules and hidden_modules:
        print(f"{indent}Hidden modules:")
        for module in hidden_modules:
            print(
                f"{indent}- {display(module.get('name'))} "
                f"(type={display(module.get('type'))})"
            )
