"""Shuori adapter for the generic WeCom customer-service workflow.

The adapter deliberately keeps the Sower client and workflow imports lazy.  The
customer-service process can therefore start with the Shuori feature disabled
even when the optional Shuori runtime dependencies are not installed yet.

``test.py`` is the source of truth for execution semantics: grading defaults to
``full_score`` and a score is submitted only when the caller explicitly opts
in with ``submit=True`` (or the adapter strategy was constructed with
``submit=True``).
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any, Callable

from .failure_details import add_failure, exception_detail, safe_error_text


class ShuoriUnavailable(RuntimeError):
    """The optional Shuori runtime cannot be loaded or reached."""


def _run_failure_reason(details: dict[str, Any], state: dict[str, Any]) -> str:
    """Use the platform's returned score/status fields as the failure reason."""
    for source in (details, state):
        if not isinstance(source, dict):
            continue
        for key in ("error", "reason", "message", "detail"):
            value = source.get(key)
            if value:
                return safe_error_text(value)
    score, maximum = state.get("score"), state.get("maximum_score")
    if score is not None and maximum is not None:
        return f"平台成绩为 {score}/{maximum}，未达到满分要求"
    return "平台未返回有效成绩或失败诊断信息"


def _first_value(source: Any, *names: str, default: Any = None) -> Any:
    """Read the first non-empty setting without requiring a settings class."""

    for name in names:
        value = getattr(source, name, None) if source is not None else None
        if value not in (None, ""):
            return value
    return default


class ShuoriService:
    """Implement the existing customer-service adapter protocol for Shuori.

    ``client_factory`` and ``workflow_factory`` are intentionally injectable so
    unit tests can use fake clients without importing the optional Sower
    package or making network requests.
    """

    def __init__(
        self,
        settings: Any = None,
        *,
        client_factory: Callable[..., Any] | None = None,
        workflow_factory: Callable[..., Any] | None = None,
        root: str | Path | None = None,
        grading_mode: str = "full_score",
        submit: bool = False,
    ) -> None:
        if grading_mode not in {"normal", "half_score", "full_score"}:
            raise ValueError("grading_mode must be normal, half_score or full_score")
        self.settings = settings
        self.base_url = str(
            _first_value(
                settings,
                "shuori_base_url",
                "suori_base_url",
                default=os.getenv("SHUORI_BASE_URL") or os.getenv("SUORI_BASE_URL", ""),
            )
        ).strip().rstrip("/")
        self.root = Path(
            root
            or _first_value(
                settings,
                "shuori_runtime_root",
                "suori_runtime_root",
                default=os.getenv("SHUORI_RUNTIME_ROOT")
                or os.getenv("SUORI_RUNTIME_ROOT")
                or "runtime/suori",
            )
        )
        self.grading_mode = grading_mode
        self.submit = bool(submit)
        self._client_factory = client_factory
        self._workflow_factory = workflow_factory

    def _load_components(self) -> tuple[type[Any], type[Any]]:
        """Load Sower classes only when a Shuori operation is actually used."""

        try:
            client_module = importlib.import_module("sower_client_service.platform.client")
            workflow_module = importlib.import_module("sower_client_service.platform.workflow")
            return client_module.PlatformClient, workflow_module.HeadlessTraining
        except (ImportError, ModuleNotFoundError, AttributeError) as exc:
            raise ShuoriUnavailable("朔日运行依赖未安装或版本不完整") from exc

    def _new_client(self, *, on_progress: Callable[[Any], None] | None = None) -> Any:
        if not self.base_url:
            raise ShuoriUnavailable("朔日服务地址未配置")
        if self._client_factory is not None:
            return self._client_factory(self.base_url, on_progress=on_progress)
        client_type, _ = self._load_components()
        return client_type(self.base_url, on_progress=on_progress)

    def _new_workflow(self, client: Any, *, on_progress: Callable[[Any], None] | None = None) -> Any:
        if self._workflow_factory is not None:
            return self._workflow_factory(
                client,
                root=self.root,
                grading_mode=self.grading_mode,
                on_progress=on_progress,
            )
        _, workflow_type = self._load_components()
        return workflow_type(
            client,
            root=self.root,
            grading_mode=self.grading_mode,
            on_progress=on_progress,
        )

    @staticmethod
    def _close(client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    @staticmethod
    def _identity(client: Any, account: str) -> str:
        return str(getattr(client, "username", "") or account)

    def _login_and_enter(self, client: Any, account: str, password: str) -> str:
        client.login(account, password)
        client.enter_training()
        return self._identity(client, account)

    @staticmethod
    def _assert_binding_identity(identity: str, binding: dict[str, Any]) -> None:
        expected = str(binding.get("login_no") or "")
        if expected and identity != expected:
            raise RuntimeError("Bound identity mismatch")

    def verify(self, account: str, password: str) -> dict[str, str]:
        """Authenticate and enter the training module without persisting secrets."""

        client = self._new_client()
        try:
            identity = self._login_and_enter(client, account, password)
            return {"login": identity, "username": identity, "phone": "未提供"}
        finally:
            self._close(client)

    @staticmethod
    def _task_id(task: dict[str, Any]) -> int:
        return int(task.get("ID") or task.get("HwID") or task.get("HWID"))

    @staticmethod
    def _term_id(task: dict[str, Any]) -> int:
        return int(task.get("TermID") or task.get("termId") or 0)

    @staticmethod
    def _remaining(task: dict[str, Any]) -> int:
        """Use a platform count when present; otherwise one whole task unit.

        The current Shuori API exposes tasks rather than challenge rows, and
        ``test.py`` charges/selects by task ID.  The fallback therefore keeps a
        task selectable and billable as one task without inventing challenge
        details that the platform did not return.
        """

        for key in ("RemainingCount", "UnfinishedCount", "ChallengeCount", "TaskCount"):
            if task.get(key) is not None:
                return max(0, int(task[key]))
        return 1

    def _map_task(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = self._task_id(task)
        term_id = self._term_id(task)
        title = str(task.get("HWName") or task.get("TaskName") or task_id)
        return {
            "homework_id": str(task_id),
            "task_id": task_id,
            "term_id": term_id,
            "course_name": str(task.get("CourseName") or "未知课程"),
            "title": title,
            "remaining_challenges": self._remaining(task),
            "submitted_count": int(task.get("SubmittedCount") or 0),
            "billing_units": 1,
        }

    def list_homeworks(self, binding: dict[str, Any]) -> list[dict[str, Any]]:
        client = self._new_client()
        try:
            identity = self._login_and_enter(client, binding["account"], binding["password"])
            self._assert_binding_identity(identity, binding)
            return [self._map_task(task) for task in client.list_tasks()]
        finally:
            self._close(client)

    def snapshot(self, binding: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Re-read selected task IDs and return a credential-free immutable snapshot."""

        client = self._new_client()
        try:
            identity = self._login_and_enter(client, binding["account"], binding["password"])
            self._assert_binding_identity(identity, binding)
            tasks = {self._task_id(task): task for task in client.list_tasks()}
            snapshot: list[dict[str, Any]] = []
            for item in items:
                task_id = int(item.get("task_id") or item.get("homework_id"))
                task = tasks.get(task_id)
                if task is None:
                    raise ValueError("所选朔日任务已不在当前任务列表中。")
                mapped = self._map_task(task)
                # Keep only task metadata required by payments and execution.
                snapshot.append(mapped)
            return snapshot
        finally:
            self._close(client)

    @staticmethod
    def billing_items(snapshot: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Expose each selected Shuori task as one generic charge unit."""

        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in snapshot:
            task_id = str(item.get("task_id") or item.get("homework_id") or "")
            term_id = str(item.get("term_id") or "0")
            if not task_id:
                raise ValueError("朔日收费项缺少任务 ID。")
            item_id = f"{term_id}:{task_id}"
            if item_id in seen:
                raise ValueError("朔日任务重复，无法确认收费数量。")
            seen.add(item_id)
            result.append(
                {
                    "id": item_id,
                    "name": str(item.get("title") or task_id),
                    "quantity": int(item.get("billing_units") or 1),
                    "billing_attributes": {"kind": "task", "service": "shuori"},
                }
            )
        return result

    @staticmethod
    def _event_details(event: Any) -> tuple[str, int | None, int | None]:
        message = str(getattr(event, "message", "") or "")
        current = getattr(event, "current", None)
        total = getattr(event, "total", None)
        return message, current, total

    def solve(
        self,
        binding: dict[str, Any],
        items: list[dict[str, Any]],
        progress: Callable[[dict[str, Any] | None], None],
        *,
        submit: bool | None = None,
    ) -> dict[str, Any]:
        """Grade selected tasks and optionally submit them.

        The default is always local scoring.  A caller must explicitly pass
        ``submit=True`` or construct this adapter with ``submit=True`` to reach
        ``HeadlessTraining.submit_task``.
        """

        should_submit = self.submit if submit is None else bool(submit)
        client = self._new_client()
        result: dict[str, Any] = {
            "passed_homeworks": 0,
            "total_homeworks": len(items),
            "passed_units": 0,
            "total_units": len(items),
            "current": "",
            "failures": [],
            "homeworks": [],
            "final": False,
            "unknown": False,
            "has_error": False,
            "submitted": should_submit,
        }

        def on_event(event: Any) -> None:
            message, current, total = self._event_details(event)
            if message:
                result["current"] = message
            if current is not None:
                result["current_step"] = current
            if total is not None:
                result["total_steps"] = total
            progress(result)

        try:
            identity = self._login_and_enter(client, binding["account"], binding["password"])
            self._assert_binding_identity(identity, binding)
            workflow = self._new_workflow(client, on_progress=on_event)
            for item in items:
                task_id = int(item.get("task_id") or item.get("homework_id"))
                title = str(item.get("title") or task_id)
                result["current"] = f"任务：{title}"
                progress(result)
                try:
                    run = workflow.run_task(
                        task_id,
                        term_id=int(item.get("term_id") or 0) or None,
                        submit=should_submit,
                    )
                    # ``test.py`` performs an independent server-side
                    # observation after an explicit submission.  Keep that
                    # distinction from the local score and do not infer it
                    # for the default (non-submitting) path.
                    if should_submit and callable(getattr(workflow, "verify_task", None)):
                        run = workflow.verify_task(run)
                    state = getattr(run, "state", {})
                    details = run.as_dict() if hasattr(run, "as_dict") else dict(state)
                    score = state.get("score", details.get("score"))
                    maximum = state.get("maximum_score", details.get("maximum_score"))
                    passed = score is not None and maximum is not None and score >= maximum
                    units = int(item.get("billing_units") or 1)
                    result["passed_homeworks"] += int(passed)
                    result["passed_units"] += units if passed else 0
                    result["homeworks"].append(
                        {"title": title, "ok": passed, "task_id": task_id, "run": details}
                    )
                    if not passed:
                        result["has_error"] = True
                        add_failure(result, f"任务：{title}\n原因：{_run_failure_reason(details, state)}")
                except Exception as exc:
                    result["unknown"] = True
                    result["has_error"] = True
                    reason = exception_detail(exc, secrets=(binding.get("account"), binding.get("password")))
                    result["homeworks"].append(
                        {"title": title, "ok": False, "task_id": task_id, "reason": reason}
                    )
                    add_failure(result, f"任务：{title}\n原因：{reason}")
                progress(result)
            result["has_error"] = bool(result["has_error"] or result["failures"])
            result.update(final=not result["unknown"], current="已结束" if not result["unknown"] else "评测结果待核对")
            return result
        finally:
            self._close(client)


# Keep both spellings available while the repository settles on its public
# service code.  They refer to exactly the same implementation.
SuoriService = ShuoriService


__all__ = ["ShuoriService", "SuoriService", "ShuoriUnavailable"]
