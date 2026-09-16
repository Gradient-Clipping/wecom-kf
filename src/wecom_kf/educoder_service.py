"""EduCoder adapter. Account secrets never leave this adapter for model prompts."""

from pathlib import Path
import re
import threading

from educoder import EduCoderClient, QuestionBank, ShixunSolver, extract_course_identifier
from educoder.exceptions import EduCoderError
from educoder.utils import mask_phone


class InvalidCredentials(RuntimeError):
    pass


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
        result = {"passed_homeworks": 0, "total_homeworks": len(items), "passed_units": 0,
                  "current": "", "failures": [], "homeworks": [], "final": False, "unknown": False}
        guard = threading.Lock()
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
                    result["passed_units"] += passed
                    completed = bool(answer.get("skipped")) or (bool(entries) and all(r.get("passed") for r in entries))
                    result["passed_homeworks"] += int(completed)
                    result["homeworks"].append({"title": item["title"], "ok": completed,
                                   "skipped_completed": answer.get("skipped_completed_count", 0),
                                   "passed": passed,
                                   "total": answer.get("selected_count", 0)})
                    for entry in answer.get("results", []):
                        if not entry.get("passed"):
                            title = entry.get("challenge", "")
                            result["failures"].append(f"实训：{item['title']}\n第{entry['position']}关：{title}")
                except Exception:
                    result["unknown"] = True
                    result["homeworks"].append({"title": item["title"], "ok": False, "reason": "upstream_or_evaluation_error"})
                    for c in item.get("challenges", []):
                        result["failures"].append(f"实训：{item['title']}\n第{c['position']}关：{c['name']}")
                progress(result)
            result.update(final=not result["unknown"], current="已结束" if not result["unknown"] else "评测结果待核对")
            return result
        finally:
            client.session.close()
