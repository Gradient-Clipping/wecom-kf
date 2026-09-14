"""Classroom experiment (课堂实验 / shixun_homework) APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Literal

from .utils import display

if TYPE_CHECKING:
    from .client import EduCoderClient


SHIXUN_HOMEWORK_TYPE = 4


@dataclass(slots=True)
class ShixunHomeworkQuery:
    limit: int = 20
    status: int | str = 0
    order: int | str = 0
    homework_type: int = SHIXUN_HOMEWORK_TYPE


@dataclass(slots=True)
class StudentWorkQuery:
    order: str = "work_score"
    direction: Literal["asc", "desc"] = "desc"


@dataclass(slots=True)
class ShixunHomeworkFilter:
    """Local filter options for classroom shixun homework items."""

    name_contains: str | None = None
    states: str | Iterable[str] | None = None
    match: Literal["all", "any"] = "all"
    enterable: bool | None = None


@dataclass(slots=True)
class ShixunHomeworkPage:
    """All data loaded by the shixun homework detail page."""

    detail: dict[str, Any]
    challenge_data: dict[str, Any]
    student_work: dict[str, Any]
    header: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        return summarize_homework_detail_page(self)


class ShixunHomeworksAPI:
    """High-level shixun homework APIs bound to an authenticated client."""

    def __init__(self, client: "EduCoderClient") -> None:
        self.client = client

    def list(
        self,
        course_identifier: str,
        login_no: str | None = None,
        *,
        query: ShixunHomeworkQuery | None = None,
        limit: int | None = None,
        status: int | str | None = None,
        order: int | str | None = None,
        homework_type: int | None = None,
    ) -> dict[str, Any]:
        return get_shixun_homeworks(
            self.client,
            course_identifier,
            login_no or self._login_no(),
            query=query,
            limit=limit,
            status=status,
            order=order,
            homework_type=homework_type,
        )

    def list_all(
        self,
        course_identifier: str,
        login_no: str | None = None,
        *,
        query: ShixunHomeworkQuery | None = None,
    ) -> dict[str, Any]:
        return get_all_shixun_homeworks(
            self.client,
            course_identifier,
            login_no or self._login_no(),
            query=query,
        )

    def items(
        self,
        course_identifier: str,
        login_no: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return self.list(course_identifier, login_no, **kwargs).get("homeworks") or []

    def filtered(
        self,
        course_identifier: str,
        login_no: str | None = None,
        *,
        all_items: bool = True,
        query: ShixunHomeworkQuery | None = None,
        filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
        name_contains: str | None = None,
        states: str | Iterable[str] | None = None,
        match: Literal["all", "any"] = "all",
        enterable: bool | None = None,
        only_unfinished: bool = False,
        only_enterable: bool = False,
        only_unpassed: bool = False,
        only_unevaluated: bool = False,
        only_not_all_completed: bool = False,
        only_ended: bool = False,
        only_submitting: bool = False,
        only_late: bool = False,
        only_archived: bool = False,
    ) -> list[dict[str, Any]]:
        data = (
            self.list_all(course_identifier, login_no, query=query)
            if all_items
            else self.list(course_identifier, login_no, query=query)
        )
        return filter_homeworks(
            data.get("homeworks") or [],
            filters=filters,
            name_contains=name_contains,
            states=states,
            match=match,
            enterable=enterable,
            only_unfinished=only_unfinished,
            only_enterable=only_enterable,
            only_unpassed=only_unpassed,
            only_unevaluated=only_unevaluated,
            only_not_all_completed=only_not_all_completed,
            only_ended=only_ended,
            only_submitting=only_submitting,
            only_late=only_late,
            only_archived=only_archived,
        )

    def summaries(
        self,
        course_identifier: str,
        login_no: str | None = None,
        *,
        all_items: bool = True,
        name_contains: str | None = None,
        filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
        states: str | Iterable[str] | None = None,
        match: Literal["all", "any"] = "all",
        enterable: bool | None = None,
        only_unfinished: bool = False,
        only_enterable: bool = False,
        only_unpassed: bool = False,
        only_unevaluated: bool = False,
        only_not_all_completed: bool = False,
        only_ended: bool = False,
        only_submitting: bool = False,
        only_late: bool = False,
        only_archived: bool = False,
        query: ShixunHomeworkQuery | None = None,
    ) -> list[dict[str, Any]]:
        return [
            summarize_homework(item)
            for item in self.filtered(
                course_identifier,
                login_no,
                all_items=all_items,
                query=query,
                filters=filters,
                name_contains=name_contains,
                states=states,
                match=match,
                enterable=enterable,
                only_unfinished=only_unfinished,
                only_enterable=only_enterable,
                only_unpassed=only_unpassed,
                only_unevaluated=only_unevaluated,
                only_not_all_completed=only_not_all_completed,
                only_ended=only_ended,
                only_submitting=only_submitting,
                only_late=only_late,
                only_archived=only_archived,
            )
        ]

    def homework(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
    ) -> "ShixunHomeworkResource":
        return ShixunHomeworkResource(
            self.client,
            course_identifier=course_identifier,
            homework_id=homework_id,
            login_no=login_no or self._login_no(),
        )

    def detail(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return self.homework(course_identifier, homework_id, login_no).detail()

    def challenge_data(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return self.homework(course_identifier, homework_id, login_no).challenge_data()

    def challenge_summaries(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
        *,
        states: str | Iterable[str] | None = None,
        match: Literal["all", "any"] = "any",
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.homework(course_identifier, homework_id, login_no).challenge_summaries(
            states=states,
            match=match,
            name_contains=name_contains,
        )

    def challenge_summaries_for_course(
        self,
        course_identifier: str,
        login_no: str | None = None,
        *,
        all_items: bool = True,
        query: ShixunHomeworkQuery | None = None,
        homework_filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
        homework_states: str | Iterable[str] | None = None,
        homework_match: Literal["all", "any"] = "all",
        challenge_states: str | Iterable[str] | None = None,
        challenge_match: Literal["all", "any"] = "any",
        homework_name_contains: str | None = None,
        challenge_name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        login_no = login_no or self._login_no()
        homeworks = self.filtered(
            course_identifier,
            login_no,
            all_items=all_items,
            query=query,
            filters=homework_filters,
            name_contains=homework_name_contains,
            states=homework_states,
            match=homework_match,
        )
        summaries: list[dict[str, Any]] = []
        for homework in homeworks:
            homework_id = homework.get("homework_id")
            if homework_id is None:
                continue
            resource = self.homework(course_identifier, homework_id, login_no)
            for challenge in resource.challenge_summaries(
                states=challenge_states,
                match=challenge_match,
                name_contains=challenge_name_contains,
            ):
                challenge.update(
                    {
                        "homework_id": homework_id,
                        "homework_name": homework.get("name")
                        or homework.get("shixun_name"),
                        "homework_status": homework.get("status"),
                        "homework_filter_states": homework_state_tags(homework),
                        "shixun_identifier": homework.get("shixun_identifier"),
                    }
                )
                summaries.append(challenge)
        return summaries

    def shixun_info(
        self,
        shixun_identifier: str,
        login_no: str | None = None,
        *,
        myshixun_identifier: str | None = None,
    ) -> dict[str, Any]:
        return get_shixun_info(
            self.client,
            shixun_identifier,
            login_no or self._login_no(),
            myshixun_identifier=myshixun_identifier,
        )

    def student_work(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
        *,
        query: StudentWorkQuery | None = None,
        order: str | None = None,
        direction: Literal["asc", "desc"] | None = None,
    ) -> dict[str, Any]:
        return self.homework(course_identifier, homework_id, login_no).student_work(
            query=query,
            order=order,
            direction=direction,
        )

    def header(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
    ) -> dict[str, Any]:
        return self.homework(course_identifier, homework_id, login_no).header()

    def page(
        self,
        course_identifier: str,
        homework_id: int | str,
        login_no: str | None = None,
    ) -> ShixunHomeworkPage:
        return self.homework(course_identifier, homework_id, login_no).page()

    def _login_no(self) -> str:
        user_info = self.client.ensure_logged_in()
        login_no = user_info.get("login")
        if not login_no:
            raise ValueError("Could not determine EduCoder login number")
        return str(login_no)


class ShixunHomeworkResource:
    """A readable handle for one classroom shixun homework."""

    def __init__(
        self,
        client: "EduCoderClient",
        *,
        course_identifier: str,
        homework_id: int | str,
        login_no: str,
    ) -> None:
        self.client = client
        self.course_identifier = str(course_identifier)
        self.homework_id = str(homework_id)
        self.login_no = login_no

    @property
    def detail_url(self) -> str:
        return (
            f"https://www.educoder.net/classrooms/{self.course_identifier}"
            f"/shixun_homework/{self.homework_id}/detail?tabs=1"
        )

    def detail(self) -> dict[str, Any]:
        return get_shixun_homework_detail(
            self.client,
            self.homework_id,
            self.login_no,
            course_identifier=self.course_identifier,
        )

    def challenge_data(self) -> dict[str, Any]:
        return get_shixun_challenge_data(
            self.client,
            self.homework_id,
            self.login_no,
            course_identifier=self.course_identifier,
        )

    def student_work(
        self,
        *,
        query: StudentWorkQuery | None = None,
        order: str | None = None,
        direction: Literal["asc", "desc"] | None = None,
    ) -> dict[str, Any]:
        return get_shixun_student_work(
            self.client,
            self.course_identifier,
            self.homework_id,
            self.login_no,
            query=query,
            order=order,
            direction=direction,
        )

    def header(self) -> dict[str, Any]:
        return get_shixun_homework_header(
            self.client,
            self.homework_id,
            self.login_no,
            course_identifier=self.course_identifier,
        )

    def page(self) -> ShixunHomeworkPage:
        return ShixunHomeworkPage(
            detail=self.detail(),
            challenge_data=self.challenge_data(),
            student_work=self.student_work(),
            header=self.header(),
        )

    def summary(self) -> dict[str, Any]:
        return self.page().summary()

    def challenges(
        self,
        *,
        states: str | Iterable[str] | None = None,
        match: Literal["all", "any"] = "any",
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        data = self.challenge_data()
        return filter_challenges(
            data.get("challenge_settings") or [],
            states=states,
            match=match,
            name_contains=name_contains,
        )

    def challenge_summaries(
        self,
        *,
        states: str | Iterable[str] | None = None,
        match: Literal["all", "any"] = "any",
        name_contains: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            summarize_challenge(challenge)
            for challenge in self.challenges(
                states=states,
                match=match,
                name_contains=name_contains,
            )
        ]

    def shixun_info(self) -> dict[str, Any]:
        page = self.page()
        summary = page.summary()
        shixun_identifier = summary.get("shixun_identifier")
        if not shixun_identifier:
            raise ValueError("Could not determine shixun_identifier")
        info = get_shixun_info(
            self.client,
            str(shixun_identifier),
            self.login_no,
            myshixun_identifier=summary.get("myshixun_identifier"),
        )
        return enrich_shixun_info_with_homework_challenge_data(
            info,
            page.challenge_data,
        )


def get_shixun_homeworks(
    client: "EduCoderClient",
    course_identifier: str,
    login_no: str,
    *,
    query: ShixunHomeworkQuery | None = None,
    limit: int | None = None,
    status: int | str | None = None,
    order: int | str | None = None,
    homework_type: int | None = None,
) -> dict[str, Any]:
    """Fetch /api/courses/<course_identifier>/homework_commons.json."""
    query = query or ShixunHomeworkQuery()
    effective_limit = query.limit if limit is None else limit
    effective_status = query.status if status is None else status
    effective_order = query.order if order is None else order
    effective_type = query.homework_type if homework_type is None else homework_type

    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": (
            f"https://www.educoder.net/classrooms/{course_identifier}/shixun_homework"
        ),
    }
    params = {
        "limit": effective_limit,
        "status": effective_status,
        "id": course_identifier,
        "type": effective_type,
        "order": effective_order,
        "zzud": login_no,
    }
    return client.request_json(
        "GET",
        f"/api/courses/{course_identifier}/homework_commons.json",
        params=params,
        headers=headers,
    )


def get_all_shixun_homeworks(
    client: "EduCoderClient",
    course_identifier: str,
    login_no: str,
    *,
    query: ShixunHomeworkQuery | None = None,
) -> dict[str, Any]:
    """Re-request with a larger limit when the first response is truncated."""
    query = query or ShixunHomeworkQuery()
    data = get_shixun_homeworks(
        client,
        course_identifier,
        login_no,
        query=query,
    )
    homeworks = data.get("homeworks") or []
    total = data.get("query_total_count") or data.get("all_count") or len(homeworks)
    try:
        total_int = int(total)
    except (TypeError, ValueError):
        return data

    if total_int > len(homeworks) and total_int > query.limit:
        return get_shixun_homeworks(
            client,
            course_identifier,
            login_no,
            query=query,
            limit=total_int,
        )
    return data


def get_shixun_homework_detail(
    client: "EduCoderClient",
    homework_id: int | str,
    login_no: str,
    *,
    course_identifier: str | None = None,
) -> dict[str, Any]:
    """Fetch /api/homework_commons/<homework_id>.json."""
    headers = _detail_headers(course_identifier, homework_id)
    return client.request_json(
        "GET",
        f"/api/homework_commons/{homework_id}.json",
        params={"zzud": login_no},
        headers=headers,
    )


def get_shixun_challenge_data(
    client: "EduCoderClient",
    homework_id: int | str,
    login_no: str,
    *,
    course_identifier: str | None = None,
) -> dict[str, Any]:
    """Fetch /api/homework_commons/<homework_id>/shixun_challenge_data.json."""
    headers = _detail_headers(course_identifier, homework_id)
    return _unwrap_data(
        client.request_json(
            "GET",
            f"/api/homework_commons/{homework_id}/shixun_challenge_data.json",
            params={"zzud": login_no},
            headers=headers,
        )
    )


def get_shixun_student_work(
    client: "EduCoderClient",
    course_identifier: str,
    homework_id: int | str,
    login_no: str,
    *,
    query: StudentWorkQuery | None = None,
    order: str | None = None,
    direction: Literal["asc", "desc"] | None = None,
) -> dict[str, Any]:
    """Fetch the current user's work data for one shixun homework."""
    query = query or StudentWorkQuery()
    effective_order = query.order if order is None else order
    effective_direction = query.direction if direction is None else direction
    headers = _detail_headers(course_identifier, homework_id)
    return _unwrap_data(
        client.request_json(
            "GET",
            f"/api/shixun_homeworks/{homework_id}/student_works.json",
            params={
                "coursesId": course_identifier,
                "categoryId": homework_id,
                "order": effective_order,
                "b_order": effective_direction,
                "id": course_identifier,
                "zzud": login_no,
            },
            headers=headers,
        )
    )


def get_shixun_homework_header(
    client: "EduCoderClient",
    homework_id: int | str,
    login_no: str,
    *,
    course_identifier: str | None = None,
) -> dict[str, Any]:
    """Fetch /api/shixun_homeworks/<homework_id>/header_info.json."""
    headers = _detail_headers(course_identifier, homework_id)
    return _unwrap_data(
        client.request_json(
            "GET",
            f"/api/shixun_homeworks/{homework_id}/header_info.json",
            params={"categoryId": homework_id, "zzud": login_no},
            headers=headers,
        )
    )


def get_shixun_info(
    client: "EduCoderClient",
    shixun_identifier: str,
    login_no: str,
    *,
    myshixun_identifier: str | None = None,
) -> dict[str, Any]:
    """Fetch shixun-level challenge info and skip policy."""
    shixun = client.request_json(
        "GET",
        f"/api/shixuns/{shixun_identifier}/challenges.json",
        params={"zzud": login_no},
        headers={"Referer": f"https://www.educoder.net/shixuns/{shixun_identifier}/challenges"},
    )
    myshixun = (
        get_myshixun_challenges(client, myshixun_identifier, login_no)
        if myshixun_identifier
        else []
    )
    return {
        "shixun_identifier": shixun_identifier,
        "allow_skip": shixun.get("allow_skip"),
        "skip_policy": summarize_skip_policy(shixun, myshixun),
        "challenge_list": summarize_shixun_challenges(shixun, myshixun),
        "shixun": shixun,
        "myshixun_identifier": myshixun_identifier,
        "myshixun_challenges": myshixun,
    }


def enrich_shixun_info_with_homework_challenge_data(
    shixun_info: dict[str, Any],
    challenge_data: dict[str, Any],
) -> dict[str, Any]:
    """Merge classroom homework per-challenge evaluation fields into shixun_info.

    The shixun-level APIs know unlock/skip policy, while
    shixun_challenge_data.json carries current user's classroom evaluation
    fields such as time_consuming and evaluate_count.
    """
    settings = challenge_data.get("challenge_settings") or []
    by_id = {str(item.get("challenge_id") or item.get("id")): item for item in settings}
    by_name = {
        str(item.get("challenge_name") or item.get("name") or ""): item
        for item in settings
    }
    for challenge in shixun_info.get("challenge_list") or []:
        detail = by_id.get(str(challenge.get("challenge_id"))) or by_name.get(
            str(challenge.get("name") or "")
        )
        if not detail:
            challenge.update(
                {
                    "time_consuming": None,
                    "time_consuming_seconds": None,
                    "evaluate_count": None,
                    "passed_status": None,
                    "game_score": None,
                    "challenge_score": None,
                }
            )
            continue
        time_consuming = detail.get("time_consuming")
        challenge.update(
            {
                "time_consuming": time_consuming,
                "time_consuming_seconds": parse_chinese_duration_seconds(
                    time_consuming
                ),
                "evaluate_count": detail.get("evaluate_count"),
                "passed_status": detail.get("passed_status"),
                "game_score": detail.get("game_score"),
                "challenge_score": detail.get("challenge_score"),
                "difficulty": detail.get("difficulty"),
                "knowledge_points": detail.get("knowledge_points"),
                "passed_rate": detail.get("passed_rate"),
            }
        )
    shixun_info["challenge_evaluation_summary"] = {
        "passed_count": challenge_data.get("passed_count"),
        "no_evaluate_count": challenge_data.get("no_evaluate_count"),
        "progress_count": challenge_data.get("progress_count"),
        "evaluate_count": challenge_data.get("evaluate_count"),
        "time_consuming": challenge_data.get("time_consuming"),
        "time_consuming_seconds": parse_chinese_duration_seconds(
            challenge_data.get("time_consuming")
        ),
        "work_score": challenge_data.get("work_score"),
    }
    return shixun_info


def get_myshixun_challenges(
    client: "EduCoderClient",
    myshixun_identifier: str,
    login_no: str,
) -> list[dict[str, Any]]:
    """Fetch current user's game identifiers and progress for one myshixun."""
    response = client.request(
        "GET",
        f"/api/myshixuns/{myshixun_identifier}/challenges.json",
        params={"zzud": login_no},
        headers={"Referer": f"https://www.educoder.net/myshixuns/{myshixun_identifier}"},
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def parse_chinese_duration_seconds(value: Any) -> int | None:
    """Parse strings such as '10分 27秒' or '1小时 2分' into seconds."""
    if value in {None, "", "--"}:
        return None
    text = str(value).strip()
    if not text:
        return None
    total = 0
    matched = False
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(小时|时|分|秒)", text):
        matched = True
        amount = float(number)
        if unit in {"小时", "时"}:
            total += int(amount * 3600)
        elif unit == "分":
            total += int(amount * 60)
        elif unit == "秒":
            total += int(amount)
    if matched:
        return total
    try:
        return int(float(text))
    except ValueError:
        return None


def summarize_skip_policy(
    shixun: dict[str, Any],
    myshixun_challenges: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    challenges = list(myshixun_challenges or [])
    locked_count = sum(1 for item in challenges if not item.get("identifier"))
    allow_skip = bool(shixun.get("allow_skip"))
    return {
        "allow_skip": shixun.get("allow_skip"),
        "sequential_required": not allow_skip,
        "locked_challenge_count": locked_count,
        "can_parallel_submit_all": allow_skip and locked_count == 0,
        "reason": (
            "allow_skip=false, locked challenges must be unlocked by passing earlier tasks"
            if not allow_skip
            else "allow_skip=true"
        ),
    }


def summarize_shixun_challenges(
    shixun: dict[str, Any],
    myshixun_challenges: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    my_by_position = {
        item.get("position"): item for item in (myshixun_challenges or [])
    }
    summaries: list[dict[str, Any]] = []
    for item in shixun.get("challenge_list") or []:
        my_item = my_by_position.get(item.get("position"), {})
        game_identifier = my_item.get("identifier")
        summaries.append(
            {
                "challenge_id": item.get("challenge_id"),
                "position": item.get("position"),
                "name": item.get("name"),
                "game_identifier": game_identifier,
                "unlocked": bool(game_identifier),
                "finished": item.get("finish_status") or my_item.get("status") == 2,
                "status": my_item.get("status"),
                "show_type": my_item.get("show_type") or item.get("show_type"),
                "finish_show_flag": item.get("finish_show_flag"),
                "has_relation": item.get("has_relation"),
            }
        )
    return summaries


def filter_homeworks(
    homeworks: Iterable[dict[str, Any]],
    *,
    filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
    name_contains: str | None = None,
    states: str | Iterable[str] | None = None,
    match: Literal["all", "any"] = "all",
    enterable: bool | None = None,
    only_unfinished: bool = False,
    only_enterable: bool = False,
    only_unpassed: bool = False,
    only_unevaluated: bool = False,
    only_not_all_completed: bool = False,
    only_ended: bool = False,
    only_submitting: bool = False,
    only_late: bool = False,
    only_archived: bool = False,
) -> list[dict[str, Any]]:
    """Filter homework items locally."""
    filter_options = resolve_homework_filter(
        filters,
        name_contains=name_contains,
        states=states,
        match=match,
        enterable=enterable,
        only_unfinished=only_unfinished,
        only_enterable=only_enterable,
        only_unpassed=only_unpassed,
        only_unevaluated=only_unevaluated,
        only_not_all_completed=only_not_all_completed,
        only_ended=only_ended,
        only_submitting=only_submitting,
        only_late=only_late,
        only_archived=only_archived,
    )
    filtered: list[dict[str, Any]] = []
    for homework in homeworks:
        if homework_matches_filter(homework, filter_options):
            filtered.append(homework)
    return filtered


def resolve_homework_filter(
    filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
    *,
    name_contains: str | None = None,
    states: str | Iterable[str] | None = None,
    match: Literal["all", "any"] = "all",
    enterable: bool | None = None,
    only_unfinished: bool = False,
    only_enterable: bool = False,
    only_unpassed: bool = False,
    only_unevaluated: bool = False,
    only_not_all_completed: bool = False,
    only_ended: bool = False,
    only_submitting: bool = False,
    only_late: bool = False,
    only_archived: bool = False,
) -> ShixunHomeworkFilter:
    if filters is None:
        resolved = ShixunHomeworkFilter()
    elif isinstance(filters, ShixunHomeworkFilter):
        resolved = ShixunHomeworkFilter(
            name_contains=filters.name_contains,
            states=filters.states,
            match=filters.match,
            enterable=filters.enterable,
        )
    else:
        resolved = ShixunHomeworkFilter(**filters)

    resolved_states = list(normalize_state_names(resolved.states))
    resolved_states.extend(normalize_state_names(states))
    if only_unfinished or only_not_all_completed:
        resolved_states.append("not_all_completed")
    if only_unpassed:
        resolved_states.append("unpassed")
    if only_unevaluated:
        resolved_states.append("unevaluated")
    if only_ended:
        resolved_states.append("ended")
    if only_submitting:
        resolved_states.append("submitting")
    if only_late:
        resolved_states.append("late")
    if only_archived:
        resolved_states.append("archived")

    resolved.name_contains = name_contains or resolved.name_contains
    resolved.states = tuple(dict.fromkeys(resolved_states))
    if filters is None or match != "all":
        resolved.match = match
    if only_enterable:
        resolved.enterable = True
    elif enterable is not None:
        resolved.enterable = enterable
    return resolved


def homework_matches_filter(
    homework: dict[str, Any],
    filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
) -> bool:
    filters = resolve_homework_filter(filters)
    if filters.name_contains:
        name = str(homework.get("name") or homework.get("shixun_name") or "")
        if filters.name_contains.lower() not in name.lower():
            return False

    if filters.enterable is not None:
        if bool(homework.get("is_enter_shixun")) != filters.enterable:
            return False

    required_states = tuple(normalize_state_names(filters.states))
    if required_states:
        tags = set(homework_state_tags(homework))
        if filters.match == "any":
            if not any(state in tags for state in required_states):
                return False
        else:
            if not all(state in tags for state in required_states):
                return False
    return True


def summarize_homework(homework: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, stable summary for one homework item."""
    operation = homework.get("task_operation") or []
    operation_url = operation[1] if len(operation) > 1 else None
    return {
        "homework_id": homework.get("homework_id"),
        "student_work_id": homework.get("student_work_id"),
        "name": homework.get("name") or homework.get("shixun_name"),
        "status": homework.get("status"),
        "status_time": homework.get("status_time"),
        "publish_time": homework.get("publish_time"),
        "end_time": homework.get("end_time"),
        "allow_late": homework.get("allow_late"),
        "author": homework.get("author"),
        "shixun_identifier": homework.get("shixun_identifier"),
        "myshixun_identifier": homework.get("myshixun_identifier"),
        "is_enter_shixun": homework.get("is_enter_shixun"),
        "operation_url": operation_url,
        "challenge_count": homework.get("challenge_count"),
        "finished_challenge_count": homework.get("finished_challenge_count"),
        "checked_challenge_count": homework.get("checked_challenge_count"),
        "shixun_finished_status": homework.get("shixun_finished_status"),
        "filter_states": homework_state_tags(homework),
        "student_passed_time": homework.get("student_passed_time"),
        "is_jupyter": homework.get("is_jupyter"),
        "is_jupyter_lab": homework.get("is_jupyter_lab"),
    }


def is_finished(homework: dict[str, Any]) -> bool:
    """Best-effort completion check for one shixun homework item."""
    finished = homework.get("finished_challenge_count")
    total = homework.get("challenge_count")
    if finished is not None and total is not None:
        try:
            return int(finished) >= int(total)
        except (TypeError, ValueError):
            pass
    return homework.get("shixun_finished_status") == 1


def is_not_all_completed(homework: dict[str, Any]) -> bool:
    return not is_finished(homework)


def is_unpassed(homework: dict[str, Any]) -> bool:
    return not is_finished(homework)


def is_unevaluated(homework: dict[str, Any]) -> bool:
    checked = homework.get("checked_challenge_count")
    total = homework.get("challenge_count")
    if checked is not None and total is not None:
        try:
            return int(checked) < int(total)
        except (TypeError, ValueError):
            pass
    return homework.get("student_work_id") in {None, ""}


def is_ended(homework: dict[str, Any]) -> bool:
    labels = homework_status_labels(homework)
    return "已截止" in labels or "截止" in labels or homework.get("time_status") == 5


def is_submitting(homework: dict[str, Any]) -> bool:
    labels = homework_status_labels(homework)
    return any(label in {"提交中", "进行中"} for label in labels)


def is_late(homework: dict[str, Any]) -> bool:
    labels = homework_status_labels(homework)
    if any("补交" in label for label in labels):
        return True
    late_time = homework.get("late_time")
    return bool(late_time and late_time != "--" and not is_ended(homework))


def is_archived(homework: dict[str, Any]) -> bool:
    labels = homework_status_labels(homework)
    return bool(homework.get("is_archive")) or any("归档" in label for label in labels)


def homework_status_labels(homework: dict[str, Any]) -> list[str]:
    raw_status = homework.get("status") or homework.get("homework_status") or []
    if isinstance(raw_status, list):
        return [str(item) for item in raw_status if item not in {None, ""}]
    if raw_status in {None, ""}:
        return []
    return [str(raw_status)]


def homework_state_tags(homework: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    if is_finished(homework):
        tags.extend(("passed", "all_completed"))
    else:
        tags.extend(("unpassed", "not_all_completed"))
    if is_unevaluated(homework):
        tags.append("unevaluated")
    else:
        tags.append("evaluated")
    if is_ended(homework):
        tags.append("ended")
    if is_submitting(homework):
        tags.append("submitting")
    if is_late(homework):
        tags.append("late")
    if is_archived(homework):
        tags.append("archived")
    tags.append("enterable" if homework.get("is_enter_shixun") else "not_enterable")
    return tags


def filter_challenges(
    challenges: Iterable[dict[str, Any]],
    *,
    states: str | Iterable[str] | None = None,
    match: Literal["all", "any"] = "any",
    name_contains: str | None = None,
) -> list[dict[str, Any]]:
    required_states = tuple(normalize_state_names(states))
    needle = name_contains.lower() if name_contains else None
    filtered: list[dict[str, Any]] = []
    for challenge in challenges:
        name = str(challenge.get("challenge_name") or challenge.get("name") or "")
        if needle and needle not in name.lower():
            continue
        if required_states:
            tags = set(challenge_state_tags(challenge))
            if match == "any" and not any(state in tags for state in required_states):
                continue
            if match == "all" and not all(state in tags for state in required_states):
                continue
        filtered.append(challenge)
    return filtered


def summarize_challenge(challenge: dict[str, Any]) -> dict[str, Any]:
    operation = challenge.get("task_operation") or []
    operation_url = operation[1] if len(operation) > 1 else None
    return {
        "challenge_id": challenge.get("challenge_id") or challenge.get("id"),
        "name": challenge.get("challenge_name") or challenge.get("name"),
        "status": challenge.get("status"),
        "passed_status": challenge.get("passed_status"),
        "evaluate_count": challenge.get("evaluate_count"),
        "game_score": challenge.get("game_score"),
        "challenge_score": challenge.get("challenge_score"),
        "time_consuming": challenge.get("time_consuming"),
        "difficulty": challenge.get("difficulty"),
        "knowledge_points": challenge.get("knowledge_points"),
        "operation_url": operation_url,
        "filter_states": challenge_state_tags(challenge),
    }


def challenge_state_tags(challenge: dict[str, Any]) -> list[str]:
    passed_status = challenge.get("passed_status")
    evaluate_count = challenge.get("evaluate_count")
    try:
        passed_status_int = int(passed_status)
    except (TypeError, ValueError):
        passed_status_int = None
    try:
        evaluate_count_int = int(evaluate_count)
    except (TypeError, ValueError):
        evaluate_count_int = None

    tags: list[str] = []
    if passed_status_int == 2:
        tags.append("passed")
    elif passed_status_int == 1 or (evaluate_count_int and evaluate_count_int > 0):
        tags.append("unpassed")
    else:
        tags.append("unevaluated")
    if challenge.get("status"):
        tags.append(str(challenge["status"]))
    return tags


def normalize_state_names(states: str | Iterable[str] | None) -> tuple[str, ...]:
    if states is None:
        return ()
    if isinstance(states, str):
        raw_states = [states]
    else:
        raw_states = list(states)
    normalized: list[str] = []
    for state in raw_states:
        canonical = _STATE_ALIASES.get(str(state).strip().lower())
        normalized.append(canonical or str(state).strip())
    return tuple(item for item in normalized if item)


_STATE_ALIASES = {
    "passed": "passed",
    "pass": "passed",
    "已通过": "passed",
    "通过": "passed",
    "all_completed": "all_completed",
    "finished": "all_completed",
    "completed": "all_completed",
    "已全部完成": "all_completed",
    "全部完成": "all_completed",
    "unpassed": "unpassed",
    "failed": "unpassed",
    "not_passed": "unpassed",
    "未通过": "unpassed",
    "未完成": "not_all_completed",
    "unfinished": "not_all_completed",
    "incomplete": "not_all_completed",
    "not_all_completed": "not_all_completed",
    "not_completed": "not_all_completed",
    "未全部完成": "not_all_completed",
    "未全部通关": "not_all_completed",
    "unevaluated": "unevaluated",
    "unreviewed": "unevaluated",
    "not_evaluated": "unevaluated",
    "未评测": "unevaluated",
    "未测评": "unevaluated",
    "未评价": "unevaluated",
    "evaluated": "evaluated",
    "已评测": "evaluated",
    "ended": "ended",
    "closed": "ended",
    "deadline_passed": "ended",
    "已截止": "ended",
    "截止": "ended",
    "submitting": "submitting",
    "in_progress": "submitting",
    "进行中": "submitting",
    "提交中": "submitting",
    "late": "late",
    "makeup": "late",
    "补交中": "late",
    "补交": "late",
    "archived": "archived",
    "archive": "archived",
    "已归档": "archived",
    "归档": "archived",
    "enterable": "enterable",
    "可进入": "enterable",
    "not_enterable": "not_enterable",
    "不可进入": "not_enterable",
}


def summarize_homework_detail_page(page: ShixunHomeworkPage) -> dict[str, Any]:
    """Return stable fields from the loaded shixun homework detail page."""
    detail = page.detail
    header = page.header
    challenge_data = page.challenge_data
    student_work = page.student_work
    challenges = header.get("challenges") or challenge_data.get("challenge_settings") or []
    return {
        "course_id": header.get("course_id") or detail.get("course_id"),
        "course_name": header.get("course_name") or detail.get("course_name"),
        "homework_id": header.get("homework_id") or detail.get("homework_id"),
        "homework_name": header.get("homework_name") or detail.get("homework_name"),
        "homework_status": header.get("homework_status") or detail.get("homework_status"),
        "time_status": header.get("time_status") or detail.get("time_status"),
        "shixun_id": header.get("shixun_id") or detail.get("shixun_id"),
        "shixun_identifier": header.get("shixun_identifier")
        or detail.get("shixun_identifier"),
        "myshixun_identifier": header.get("myshixun_identifier")
        or detail.get("myshixun_identifier"),
        "work_id": header.get("work_id") or detail.get("work_id") or student_work.get("id"),
        "work_status": student_work.get("work_status"),
        "work_score": student_work.get("work_score"),
        "final_score": student_work.get("final_score"),
        "complete_info": student_work.get("complete_info"),
        "passed_count": challenge_data.get("passed_count"),
        "progress_count": challenge_data.get("progress_count"),
        "challenge_count": len(challenges),
        "is_enter_shixun": header.get("is_enter_shixun"),
        "can_submit": detail.get("can_submit"),
        "view_report": header.get("view_report") or detail.get("view_report"),
        "task_operation": header.get("task_operation") or detail.get("task_operation"),
    }


def _unwrap_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    return data if isinstance(data, dict) else response


def _detail_headers(
    course_identifier: str | None,
    homework_id: int | str,
) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if course_identifier:
        headers["Referer"] = (
            f"https://www.educoder.net/classrooms/{course_identifier}"
            f"/shixun_homework/{homework_id}/detail?tabs=1"
        )
    return headers


def print_shixun_homework_summary(
    data: dict[str, Any],
    *,
    course_identifier: str,
    name_contains: str | None = None,
    filters: ShixunHomeworkFilter | dict[str, Any] | None = None,
    states: str | Iterable[str] | None = None,
    match: Literal["all", "any"] = "all",
    enterable: bool | None = None,
    only_unfinished: bool = False,
    only_enterable: bool = False,
    only_unpassed: bool = False,
    only_unevaluated: bool = False,
    only_not_all_completed: bool = False,
    only_ended: bool = False,
    only_submitting: bool = False,
    only_late: bool = False,
    only_archived: bool = False,
    show_urls: bool = True,
) -> None:
    """Optional human-readable shixun homework summary printer."""
    homeworks = filter_homeworks(
        data.get("homeworks") or [],
        filters=filters,
        name_contains=name_contains,
        states=states,
        match=match,
        enterable=enterable,
        only_unfinished=only_unfinished,
        only_enterable=only_enterable,
        only_unpassed=only_unpassed,
        only_unevaluated=only_unevaluated,
        only_not_all_completed=only_not_all_completed,
        only_ended=only_ended,
        only_submitting=only_submitting,
        only_late=only_late,
        only_archived=only_archived,
    )
    print(
        f"Shixun homeworks: course={course_identifier}, "
        f"module={display(data.get('main_category_name'))}, "
        f"total={display(data.get('all_count'))}, "
        f"published={display(data.get('published_count'))}, "
        f"shown={len(homeworks)}, "
        f"tasks={display(data.get('task_count'))}, "
        f"challenges={display(data.get('challenge_count'))}, "
        f"finished_tasks={display(data.get('finished_task_count'))}, "
        f"finished_challenges={display(data.get('finished_challenge_count'))}"
    )
    if not homeworks:
        print("No shixun homework found.")
        return

    for index, homework in enumerate(homeworks, start=1):
        summary = summarize_homework(homework)
        progress = (
            f"{display(summary['finished_challenge_count'])}/"
            f"{display(summary['challenge_count'])}"
        )
        print(
            f"{index}. id={display(summary['homework_id'])}, "
            f"name={display(summary['name'])}, "
            f"status={display(summary['status'])}, "
            f"progress={progress}, "
            f"states={display(summary['filter_states'])}, "
            f"enterable={display(summary['is_enter_shixun'])}, "
            f"author={display(summary['author'])}, "
            f"publish={display(summary['publish_time'])}, "
            f"end={display(summary['end_time'])}, "
            f"passed={display(summary['student_passed_time'])}, "
            f"shixun={display(summary['shixun_identifier'])}, "
            f"myshixun={display(summary['myshixun_identifier'])}"
        )
        if show_urls and summary["operation_url"]:
            print(f"   url={summary['operation_url']}")
