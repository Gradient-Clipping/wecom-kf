"""EduCoder adapter. Account secrets never leave this adapter for model prompts."""

from pathlib import Path
import re
import threading

from educoder import EduCoderClient, QuestionBank, ShixunSolver, extract_course_identifier
from educoder.exceptions import EduCoderError
from educoder.utils import mask_phone
from .failure_details import add_failure, exception_detail, safe_error_text


class InvalidCredentials(RuntimeError):
    pass


def _diagnostics_reason(diagnostics):
    if not isinstance(diagnostics, dict):
        return None
    message = diagnostics.get("message") or diagnostics.get("last_compile_output")
    if message:
        return safe_error_text(message)
    errors = diagnostics.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {"error": errors[0]}
        error_type = first.get("error_type") or first.get("type")
        visible = diagnostics.get("visible_error_count")
        restricted = diagnostics.get("restricted_error_count")
        suffix = []
        if isinstance(visible, int):
            suffix.append(f"可见失败用例 {visible} 个")
        if isinstance(restricted, int) and restricted:
            suffix.append(f"受限失败用例 {restricted} 个")
        return "；".join(filter(None, [safe_error_text(error_type or "评测用例未通过"), *suffix]))
    if diagnostics.get("compile_success") is False:
        return "编译未通过，平台没有返回编译输出"
    return None


def _evaluation_reason(entry):
    """Extract only provider diagnostics that are safe to persist."""
    if not isinstance(entry, dict):
        return "平台返回了无法解析的失败结果"
    # A solver may report ``attempt_limit_reached`` at the top level while the
    # useful compiler/test diagnostic is retained on its last attempt.
    attempts = entry.get("attempts")
    if isinstance(attempts, list):
        for attempt in reversed(attempts):
            reason = _diagnostics_reason(attempt.get("diagnostics")) if isinstance(attempt, dict) else None
            if reason:
                return reason
            if isinstance(attempt, dict) and attempt.get("error"):
                return safe_error_text(attempt["error"])
    error = entry.get("error")
    if error:
        return safe_error_text(error)
    if entry.get("evaluation_uncertain"):
        return "评测状态不确定，平台没有确认本次提交结果"
    diagnostics = entry.get("diagnostics")
    reason = _diagnostics_reason(diagnostics)
    if reason:
        return reason
    return "平台返回未通过，但没有提供更具体的诊断信息"


class EduCoderService:
    def __init__(self, settings):
        self.settings = settings

    def client(self, account, password):
        return EduCoderClient(account, password, cache_dir=self.settings.cache_dir, verbose=False, timeout=30)

    def verify(self, account, password):
        client = self.client(account, password)
        try:
            try:
                client.login()
            except EduCoderError as exc:
                # Only explicit credential rejection counts. Captcha, throttling,
                # HTTP, signing, and unavailable upstream are not bad passwords.
                message = str(exc)
                limited = any(v in message for v in ("验证码", "频繁", "次数", "锁定", "冻结", "稍后", "限制"))
                rejected = re.search(r"(?:密码|口令).{0,8}(?:错误|不正确|不匹配|无效)|(?:无效|错误).{0,12}密码|(?:账号|帐号|账户|用户名|用户)不存在", message)
                if message.startswith("Login rejected:") and rejected and not limited:
                    raise InvalidCredentials() from None
                raise RuntimeError("Authentication unavailable") from None
            info = client.get_user_info()
            if not info.get("login"):
                raise RuntimeError("Missing canonical identity")
            return {"login": str(info["login"]), "username": str(info.get("username") or info.get("real_name") or "未提供"),
                    "phone": mask_phone(info.get("phone"))}
        finally:
            client.session.close()

    def list_homeworks(self, binding):
        client = self.client(binding["account"], binding["password"])
        try:
            info = client.ensure_logged_in()
            if str(info.get("login")) != binding["login_no"]:
                raise RuntimeError("Bound identity mismatch")
            result, seen = [], set()
            for course in client.courses.items():
                cid = extract_course_identifier(course)
                if not cid:
                    continue
                for item in client.shixun_homeworks.filtered(cid, only_not_all_completed=True):
                    hid = str(item.get("homework_id") or "")
                    if not hid or (cid, hid) in seen:
                        continue
                    seen.add((cid, hid))
                    total = item.get("challenge_count")
                    finished = item.get("finished_challenge_count")
                    if total is None or finished is None:
                        detail = client.shixun_homeworks.homework(cid, hid).shixun_info()
                        challenges = detail.get("challenge_list") or []
                        remaining = sum(not c.get("finished") for c in challenges)
                    else:
                        remaining = max(0, int(total) - int(finished))
                    result.append({"course_identifier": str(cid), "homework_id": hid,
                                   "course_name": str(course.get("name") or course.get("course_name") or cid),
                                   "title": str(item.get("name") or item.get("shixun_name") or hid),
                                   "remaining_challenges": remaining})
            return result
        finally:
            client.session.close()

    def snapshot(self, binding, items):
        client = self.client(binding["account"], binding["password"])
        try:
            if str(client.ensure_logged_in().get("login")) != binding["login_no"]:
                raise RuntimeError("Bound identity mismatch")
            result = []
            for item in items:
                info = client.shixun_homeworks.homework(item["course_identifier"], item["homework_id"]).shixun_info()
                challenges = [{"challenge_id": int(c["challenge_id"]), "name": str(c.get("name") or ""),
                               "position": int(c.get("position") or i + 1)}
                              for i, c in enumerate(info.get("challenge_list") or []) if not c.get("finished")]
                if challenges:
                    result.append({**item, "challenges": challenges, "allow_skip": info.get("allow_skip")})
            return result
        finally:
            client.session.close()

    @staticmethod
    def billing_items(snapshot):
        """Expose homeworks as charge items; keep challenge details in the snapshot."""
        result, seen = [], set()
        for item in snapshot:
            item_id = f"{item['course_identifier']}:{item['homework_id']}"
            if item_id in seen:
                raise ValueError("重复的实训收费项。")
            seen.add(item_id)
            challenges = item["challenges"]
            if len({c["challenge_id"] for c in challenges}) != len(challenges):
                raise ValueError("实训关卡重复，无法确认收费数量。")
            if challenges:
                result.append({"id": item_id, "name": item["title"],
                               "quantity": len(challenges), "billing_attributes": {"kind": "unit"}})
        return result

    def solve(self, binding, items, progress):
        client = self.client(binding["account"], binding["password"])
        total_challenges = sum(len(item.get("challenges") or []) for item in items)
        result = {"passed_homeworks": 0, "total_homeworks": len(items), "passed_units": 0,
                  "total_challenges": total_challenges or None, "current": "", "failures": [],
                  "homeworks": [], "final": False, "unknown": False, "has_error": False}
        guard = threading.Lock()
        finalized_units = 0
        try:
            info = client.ensure_logged_in()
            if str(info.get("login")) != binding["login_no"]:
                raise RuntimeError("Bound identity mismatch")
            bank = QuestionBank(self.settings.bank_path)
            if not Path(self.settings.bank_path).is_file():
                raise RuntimeError("Question bank not provisioned")
            current_item = {}
            def on_event(event):
                with guard:
                    if event.get("event") == "question_ready":
                        title = event.get("title", "")
                        result["current"] = f"实训：{current_item.get('title', '')}\n第{event['position']}关：{title}"
                    elif event.get("event") == "evaluated" and event.get("passed"):
                        result["passed_units"] += 1
                    elif event.get("event") in {"question_error", "tool_rejected"}:
                        result["unknown"] = True
                        result["has_error"] = True
                        reason = event.get("error") or event.get("event")
                        add_failure(result, f"实训：{current_item.get('title', '')}\n"
                                           f"第{event.get('position', '当前')}关：{event.get('title', '当前题目')}\n"
                                           f"原因：{safe_error_text(reason)}")
                    progress(result)
            solver = ShixunSolver(client, bank, max_attempts=5, evaluation_timeout=180, on_event=on_event)
            for item in items:
                current_item = item
                result["current"] = f"实训：{item['title']}"
                progress(None)
                try:
                    answer = solver.solve_shixun(item["course_identifier"], item["homework_id"],
                                                 include_completed=False, max_workers=4,
                                                 challenge_ids={c["challenge_id"] for c in item["challenges"]} if "challenges" in item else None)
                    entries = answer.get("results", [])
                    passed = (sum(bool(r.get("passed")) for r in entries) + answer.get("skipped_completed_count", 0)
                              - sum(r.get("skip_reason") == "already_completed" for r in entries))
                    if any(r.get("evaluation_uncertain") for r in entries):
                        result["unknown"] = True
                    result["passed_units"] = max(result["passed_units"], finalized_units + passed)
                    finalized_units += passed
                    completed = bool(answer.get("skipped")) or (bool(entries) and all(r.get("passed") for r in entries))
                    result["has_error"] = result["has_error"] or not completed
                    result["passed_homeworks"] += int(completed)
                    result["homeworks"].append({"title": item["title"], "ok": completed,
                                   "skipped_completed": answer.get("skipped_completed_count", 0),
                                   "passed": passed,
                                   "total": answer.get("selected_count", 0)})
                    for entry in answer.get("results", []):
                        if not entry.get("passed"):
                            title = entry.get("challenge", "")
                            add_failure(result, f"实训：{item['title']}\n第{entry['position']}关：{title}\n"
                                               f"原因：{_evaluation_reason(entry)}")
                    result["has_error"] = result["has_error"] or any(not entry.get("passed") for entry in entries)
                except Exception as exc:
                    result["unknown"] = True
                    result["has_error"] = True
                    reason = exception_detail(exc, secrets=(binding.get("account"), binding.get("password")))
                    result["homeworks"].append({"title": item["title"], "ok": False, "reason": reason})
                    challenges = item.get("challenges", [])
                    if challenges:
                        for c in challenges:
                            add_failure(result, f"实训：{item['title']}\n第{c['position']}关：{c['name']}\n原因：{reason}")
                    else:
                        add_failure(result, f"实训：{item['title']}\n原因：{reason}")
                progress(result)
            result["has_error"] = bool(result["has_error"] or result["failures"])
            # A known, partially failed evaluation is still final; ``has_error``
            # is the operator-facing signal and must not suppress refund math.
            result.update(final=not result["unknown"], current="已结束" if not result["unknown"] else "评测结果待核对")
            return result
        finally:
            client.session.close()
