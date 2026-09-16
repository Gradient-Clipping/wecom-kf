"""Concurrent shixun solving with exact bank matches and bounded model repair."""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from .answer_bank import QuestionBank, fetch_question_images
from .client import EduCoderClient
from .deepseek import DeepSeekConfig, DeepSeekConversation, InvalidAnswerError, problem_message
from .exceptions import EduCoderError
from .tasks import EvaluationResult, infer_task_path, structure_task_content


class SubmissionGate:
    """Thread-safe outbound admission; evaluations remain concurrent afterward."""

    def __init__(self, interval: float = 0.5) -> None:
        if not math.isfinite(interval) or interval < 0.5:
            raise ValueError("Skip-enabled submissions require an interval of at least 0.5 seconds")
        self.interval = interval
        self._lock = threading.Lock()
        self._last_finished: float | None = None

    def run(self, send: Callable[[], Any], *, allow_skip: bool) -> Any:
        if not allow_skip:
            return send()
        with self._lock:
            if self._last_finished is not None:
                delay = self.interval - (time.monotonic() - self._last_finished)
                if delay > 0:
                    time.sleep(delay)
            # Base the next delay on HTTP completion so a delayed callback or
            # thread cannot shorten the actual outbound request spacing.
            try:
                return send()
            finally:
                self._last_finished = time.monotonic()


class EvaluationUncertainError(RuntimeError):
    """A build may still be running; do not write or submit again blindly."""


def evaluation_feedback(diagnostics: dict[str, Any]) -> str:
    errors = diagnostics.get("errors") or []
    visible = [item for item in errors if item.get("details_available")]
    details = {
        "compile_success": diagnostics.get("compile_success"),
        "message": diagnostics.get("message"),
        "test_sets_count": diagnostics.get("test_sets_count"),
        "sets_error_count": diagnostics.get("sets_error_count"),
        "visible_errors": visible,
        "restricted_error_count": diagnostics.get("restricted_error_count"),
    }
    instruction = ("The submitted code did not pass. Fix it and call submit_code with full_code "
                   "containing the complete replacement file, including all required starter code.")
    if not visible:
        instruction += (
            " Detailed failing inputs/outputs are unavailable (locked, hidden, or absent). "
            "Do not invent hidden test data. Recheck the statement, boundary cases, "
            "types, algorithms, and exact output formatting using this same conversation."
        )
    return instruction + "\n" + json.dumps(details, ensure_ascii=False)


class ShixunSolver:
    """One account, shared admission gate, independent sessions/conversations.

    Call solve_challenge concurrently or use solve_shixun. Only remote build
    admission is rate-limited; model generation and result polling are parallel.
    Same-file writes are protected until evaluation ends. Different files may
    evaluate concurrently using their returned repository commit IDs.
    """

    def __init__(
        self, client: EduCoderClient, bank: QuestionBank, *,
        deepseek: DeepSeekConfig | None = None, max_attempts: int = 5,
        submission_interval: float = 0.5, evaluation_timeout: float = 180.0,
        audit_dir: str | Path | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        conversation_factory: Callable[..., Any] = DeepSeekConversation,
    ) -> None:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if not math.isfinite(evaluation_timeout) or evaluation_timeout <= 0:
            raise ValueError("evaluation_timeout must be finite and positive")
        self.client = client
        self.bank = bank
        self.deepseek = deepseek
        self.max_attempts = max_attempts
        self.evaluation_timeout = evaluation_timeout
        self.gate = SubmissionGate(submission_interval)
        self.audit_dir = Path(audit_dir) if audit_dir else None
        self.on_event = on_event
        self.conversation_factory = conversation_factory
        self._state_lock = threading.Lock()
        self._bank_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._locks: dict[tuple[str, ...], threading.Lock] = {}
        self._inflight: dict[str, dict[str, threading.Event]] = {}

    def _lock_for(self, *key: str) -> threading.Lock:
        with self._state_lock:
            return self._locks.setdefault(key, threading.Lock())

    def _emit(self, event: str, **fields: Any) -> None:
        if self.on_event:
            with self._event_lock:
                self.on_event({"event": event, "monotonic": time.monotonic(), **fields})

    def _evaluate(
        self, client: EduCoderClient, game: str, repo: str, path: str, code: str,
        homework_id: str | int, allow_skip: bool, attempt: dict[str, Any], previous_code: str,
    ) -> EvaluationResult:
        deadline = time.monotonic() + self.evaluation_timeout
        finished = threading.Event()
        for admission in range(1, 9):
            task = client.tasks.get(game, homework_common_id=homework_id)
            if task.get("work_end_forbid_evaluate"):
                raise ValueError("Evaluation is forbidden after the homework deadline")
            if task.get("submit_limit"):
                count = task.get("game", {}).get("evaluate_count")
                limit = task.get("submit_limit_num")
                if count is None or limit is None or int(count) >= int(limit):
                    raise ValueError("Evaluation quota is exhausted or unknown")
            busy = False
            with self._lock_for("repository", repo):
                current = client.tasks.read_file(game, path, homework_common_id=homework_id)
                if current not in {previous_code, code}:
                    raise ValueError("Remote source changed while queued; refusing to overwrite")
                try:
                    update = client.tasks.update_file(game, path, code, task=task, homework_common_id=homework_id)
                except EduCoderError as exc:
                    if "\u8bc4\u6d4b\u4efb\u52a1\u8fd0\u884c\u4e2d" not in str(exc):
                        raise
                    busy = True
                if not busy:
                    def send() -> dict[str, Any]:
                        attempt["submitted_at"] = time.time()
                        attempt["submitted_monotonic"] = time.monotonic()
                        self._emit("submit", game=game, attempt=attempt["number"], admission=admission, allow_skip=allow_skip)
                        return client.tasks.build(game, task=task, update_file_result=update, homework_common_id=homework_id)
                    try:
                        build = self.gate.run(send, allow_skip=allow_skip)
                    except Exception as exc:
                        raise EvaluationUncertainError(f"Build transport failed: {type(exc).__name__}") from exc
                    response = {key: build.get(key) for key in ("status", "message", "error", "port")}
                    attempt.setdefault("build_requests", []).append({**response, "submitted_monotonic": attempt["submitted_monotonic"]})
                    attempt["new_submission_key"] = bool(update.get("sec_key"))
                    if build.get("status") == 1:
                        attempt["accepted"] = True
                        with self._state_lock:
                            self._inflight.setdefault(repo, {})[game] = finished
                        break
                    busy = build.get("status") == -2 and "\u8bc4\u6d4b\u4efb\u52a1\u8fd0\u884c\u4e2d" in str(build.get("message"))
                    if not busy:
                        raise RuntimeError(f"Build rejected: {response}")
            # The server explicitly refused admission, so this is not another
            # failed answer or an uncertain submission. Keep the same candidate.
            with self._state_lock:
                peers = list(self._inflight.get(repo, {}).values())
            remaining = deadline - time.monotonic()
            if admission == 8 or remaining <= 0:
                raise RuntimeError("Server remained busy; candidate was not accepted")
            self._emit("queued_server_busy", game=game, attempt=attempt["number"], admission=admission)
            if peers:
                if not all(peer.wait(timeout=max(0, deadline - time.monotonic())) for peer in peers):
                    raise RuntimeError("Timed out waiting for another evaluation to finish")
            else:
                time.sleep(min(1.0, remaining))
        else:
            raise RuntimeError("Server admission attempts exhausted")
        try:
            status = client.tasks.wait_status(
                game, task=task, homework_common_id=homework_id,
                sec_key=update.get("sec_key") or task.get("sec_key"),
                resubmit=update.get("resubmit") or "", port=build.get("port", 0),
                interval=0.5, timeout=max(0.001, deadline - time.monotonic()),
            )
        except Exception as exc:
            # Leave the event unresolved: dependent queued jobs must not assume
            # the remote process stopped just because our poll timed out.
            raise EvaluationUncertainError(f"Evaluation state unknown: {type(exc).__name__}") from exc
        with self._state_lock:
            self._inflight.get(repo, {}).pop(game, None)
            finished.set()
        return EvaluationResult(task=task, update_file=update, build=build, status=status)

    def solve_challenge(
        self, game_identifier: str, *, homework_id: str | int,
        shixun_title: str, allow_skip: bool, position: int | None = None,
    ) -> dict[str, Any]:
        if type(allow_skip) is not bool:
            raise ValueError("An explicit server skip policy is required")
        client = self.client.clone()
        result: dict[str, Any] = {
            "game": game_identifier, "homework_id": str(homework_id),
            "shixun_title": shixun_title, "allow_skip": allow_skip,
            "position": position, "passed": False, "attempts": [], "bank_saved": False,
        }
        conversation = None
        pending_call = None
        original = None
        last_written = None
        path = None
        uncertain = False
        run_id = uuid.uuid4().hex
        folder = self.audit_dir / f"{game_identifier}_{run_id[:8]}" if self.audit_dir else None
        if folder:
            folder.mkdir(parents=True, exist_ok=False)
        try:
            task = client.tasks.get(game_identifier, homework_common_id=homework_id)
            path = infer_task_path(task)
            paths = [p for p in str(task.get("challenge", {}).get("path", "")).replace(";", "\uff1b").split("\uff1b") if p.strip()]
            if len(paths) != 1:
                raise ValueError("Automatic solving currently requires exactly one editable file")
            repo = str(task.get("myshixun", {}).get("identifier") or "")
            if not repo:
                raise ValueError("Missing myshixun repository identifier")
            with self._lock_for("file", repo, path):
                original = client.tasks.read_file(game_identifier, path, homework_common_id=homework_id)
                if folder:
                    (folder / "original.txt").write_bytes(original.encode("utf-8"))
                content = structure_task_content(task)
                stem = content["raw"]
                title = str(task.get("challenge", {}).get("subject") or "")
                result.update({"challenge": title, "path": path})
                images = fetch_question_images(client, stem)
                matched = self.bank.match(stem, images=images)
                result["matched"] = matched is not None
                result["image_count"] = len(images)
                self._emit("question_ready", game=game_identifier, title=title, position=position,
                           bank_match=matched is not None, images=len(images))

                def context() -> Any:
                    nonlocal conversation
                    if conversation is None:
                        config = self.deepseek or DeepSeekConfig.from_env()
                        conversation = self.conversation_factory(config, problem_message(
                            title=title, stem=stem, path=path, starter_code=original, images=images,
                        ))
                    return conversation

                try:
                    for number in range(1, self.max_attempts + 1):
                        attempt: dict[str, Any] = {"number": number}
                        result["attempts"].append(attempt)
                        if number == 1 and matched is not None:
                            code = matched["answer_text"]
                            attempt["source"] = "bank"
                        else:
                            attempt["source"] = "deepseek"
                            self._emit("model_request", game=game_identifier, attempt=number)
                            try:
                                pending_call = context().next_submission()
                                code = pending_call.full_code
                                attempt["tool_call_id"] = pending_call.call_id
                                attempt["tool_name"] = "submit_code"
                            except InvalidAnswerError as exc:
                                attempt["error"] = str(exc)
                                self._emit("tool_rejected", game=game_identifier, attempt=number, error=str(exc))
                                continue
                        task = client.tasks.get(game_identifier, homework_common_id=homework_id)
                        if task.get("work_end_forbid_evaluate"):
                            raise ValueError("This homework forbids evaluation after its deadline")
                        if task.get("submit_limit"):
                            count = task.get("game", {}).get("evaluate_count")
                            limit = task.get("submit_limit_num")
                            if count is None or limit is None or int(count) >= int(limit):
                                raise ValueError("Evaluation quota is exhausted or unknown")
                        current = client.tasks.read_file(game_identifier, path, homework_common_id=homework_id)
                        if current != (last_written if last_written is not None else original):
                            raise ValueError("Remote source changed externally; refusing to overwrite")
                        last_written = code
                        try:
                            evaluation = self._evaluate(client, game_identifier, repo, path, code, homework_id, allow_skip, attempt, current)
                        except EvaluationUncertainError:
                            uncertain = True
                            raise
                        attempt["passed"] = evaluation.passed
                        attempt["diagnostics"] = evaluation.diagnostics
                        self._emit("evaluated", game=game_identifier, attempt=number, passed=evaluation.passed)
                        if pending_call is not None:
                            context().submit_result(pending_call, {
                                "status": "passed" if evaluation.passed else "failed",
                                "submitted": True, "passed": evaluation.passed,
                                "remaining_attempts": self.max_attempts - number,
                                "feedback": ("All tests passed. No further submission is needed."
                                             if evaluation.passed else evaluation_feedback(evaluation.diagnostics)),
                            })
                            pending_call = None
                        if evaluation.passed:
                            result["passed"] = True
                            # Update the exact matched entry rather than creating conflicting aliases.
                            with self._bank_lock:
                                result["question_id"] = self.bank.add(
                                    title=matched["title"] if matched else title,
                                    shixun_title=matched["shixun_title"] if matched else shixun_title,
                                    stem_text=stem, answer_text=code, images=images,
                                )
                            result["bank_saved"] = True
                            break
                        if attempt["source"] == "bank" and number < self.max_attempts:
                            context().remember_code(code)
                            context().feedback(evaluation_feedback(evaluation.diagnostics))
                    if not result["passed"]:
                        result["error"] = "attempt_limit_reached"
                finally:
                    if last_written is not None and not result["passed"] and not uncertain:
                        try:
                            current = client.tasks.read_file(game_identifier, path, homework_common_id=homework_id)
                            if current == original:
                                result["restored_original"] = True
                            elif current == last_written:
                                client.tasks.update_file(
                                    game_identifier, path, original, homework_common_id=homework_id, evaluate=0,
                                )
                                result["restored_original"] = client.tasks.read_file(
                                    game_identifier, path, homework_common_id=homework_id,
                                ) == original
                                if not result["restored_original"]:
                                    result["restore_error"] = "Source read-back differs from original"
                            else:
                                result["restore_skipped"] = "remote_source_changed"
                        except Exception as exc:
                            result["restore_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["evaluation_uncertain"] = uncertain
            if pending_call is not None:
                conversation.submit_result(pending_call, {
                    "status": "unknown" if uncertain else "error",
                    "submitted": None if uncertain else bool(result["attempts"][-1].get("accepted")),
                    "passed": None, "error": result["error"],
                    "instruction": "Execution stopped. Do not resubmit automatically.",
                })
                pending_call = None
            self._emit("question_error", game=game_identifier, error=result["error"])
        finally:
            result["evaluation_count"] = sum(bool(attempt.get("accepted")) for attempt in result["attempts"])
            if conversation:
                result["model_responses"] = len(conversation.usage)
                result["api_requests"] = len(conversation.api_attempts)
                result["context_message_count"] = len(conversation.messages)
            if folder:
                audit = dict(result)
                if conversation:
                    audit["conversation"] = conversation.messages
                    audit["usage"] = conversation.usage
                    audit["api_attempts"] = conversation.api_attempts
                (folder / "result.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
                result["audit_path"] = str((folder / "result.json").resolve())
            client.session.close()
        return result

    def solve_shixun(
        self, course_identifier: str, homework_id: str | int, *,
        include_completed: bool = False, max_challenges: int | None = None,
        challenge_ids: set[int] | None = None, max_workers: int | None = None,
    ) -> dict[str, Any]:
        control = self.client.clone()
        results: list[dict[str, Any]] = []
        try:
            resource = control.shixun_homeworks.homework(course_identifier, homework_id)
            info = resource.shixun_info()
            allow_skip = info.get("allow_skip")
            title = str(info.get("shixun", {}).get("name") or info.get("shixun", {}).get("shixun_name") or "")
            if not title:
                title = str(resource.summary().get("homework_name") or info["shixun_identifier"])
            challenges = sorted(info.get("challenge_list") or [], key=lambda c: int(c.get("position") or 0))
            eligible = [c for c in challenges if challenge_ids is None or int(c["challenge_id"]) in challenge_ids]
            selected = [c for c in eligible if include_completed or not c.get("finished")]
            skipped_completed_count = len(eligible) - len(selected)
            if max_challenges is not None:
                if max_challenges < 1:
                    raise ValueError("max_challenges must be positive")
                selected = selected[:max_challenges]
            if selected and type(allow_skip) is not bool:
                raise ValueError("Unknown skip policy; refusing automatic submission")
            if selected and not info.get("myshixun_identifier"):
                game = control.tasks.enter_shixun(info["shixun_identifier"], homework_common_id=homework_id)
                task = control.tasks.get(game, homework_common_id=homework_id)
                myshixun = task.get("myshixun", {}).get("identifier")
                info = control.shixun_homeworks.shixun_info(info["shixun_identifier"], myshixun_identifier=myshixun)

            def current_challenge(challenge: dict[str, Any], current_info: dict[str, Any]) -> dict[str, Any]:
                return next((c for c in current_info["challenge_list"] if c["challenge_id"] == challenge["challenge_id"]), challenge)

            def solve(challenge: dict[str, Any]) -> dict[str, Any]:
                if not include_completed and challenge.get("finished"):
                    return {"challenge": challenge.get("name"), "passed": True,
                            "position": challenge["position"], "skipped": True, "skip_reason": "already_completed", "attempts": []}
                game = challenge.get("game_identifier")
                if not game:
                    return {"challenge": challenge.get("name"), "position": challenge["position"], "passed": False, "error": "challenge_locked", "attempts": []}
                return self.solve_challenge(game, homework_id=homework_id, shixun_title=title,
                                            allow_skip=allow_skip, position=int(challenge["position"]))

            self._emit("start_shixun", homework_id=str(homework_id), title=title, allow_skip=allow_skip, selected=len(selected))
            if allow_skip:
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {pool.submit(solve, current_challenge(c, info)): index for index, c in enumerate(selected)}
                    ordered = {}
                    for future in as_completed(futures):
                        ordered[futures[future]] = future.result()
                    results = [ordered[index] for index in sorted(ordered)]
            else:
                for index, challenge in enumerate(selected):
                    if index:
                        info = control.shixun_homeworks.shixun_info(
                            info["shixun_identifier"], myshixun_identifier=info.get("myshixun_identifier"),
                        )
                    result = solve(current_challenge(challenge, info))
                    results.append(result)
                    if not result["passed"]:
                        for remaining in selected[index + 1:]:
                            results.append({"challenge": remaining.get("name"), "passed": False,
                                            "position": remaining["position"], "skipped": True,
                                            "error": "previous_challenge_failed", "attempts": []})
                        break
            already_completed = bool(eligible) and skipped_completed_count == len(eligible)
            return {
                "course_identifier": course_identifier, "homework_id": str(homework_id),
                "shixun_title": title, "allow_skip": allow_skip,
                "selected_count": len(selected), "results": results,
                "skipped_completed_count": skipped_completed_count + sum(
                    r.get("skip_reason") == "already_completed" for r in results
                ),
                "skipped": already_completed,
                "skip_reason": "already_completed" if already_completed else None,
                "ok": already_completed or (bool(selected) and all(r["passed"] and r.get("bank_saved", True) for r in results)),
            }
        finally:
            control.session.close()
