"""EduCoder adapter. Account secrets never leave this adapter for model prompts."""

from pathlib import Path
import re

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
                    result.append({"course_identifier": str(cid), "homework_id": hid,
                                   "course_name": str(course.get("name") or course.get("course_name") or cid),
                                   "title": str(item.get("name") or item.get("shixun_name") or hid)})
            return result
        finally:
            client.session.close()

    def solve(self, binding, items, progress):
        client = self.client(binding["account"], binding["password"])
        result = []
        try:
            info = client.ensure_logged_in()
            if str(info.get("login")) != binding["login_no"]:
                raise RuntimeError("Bound identity mismatch")
            bank = QuestionBank(self.settings.bank_path)
            if not Path(self.settings.bank_path).is_file():
                raise RuntimeError("Question bank not provisioned")
            solver = ShixunSolver(client, bank, max_attempts=5, evaluation_timeout=180,
                                  on_event=lambda event: progress(None))
            for item in items:
                progress(None)
                try:
                    answer = solver.solve_shixun(item["course_identifier"], item["homework_id"],
                                                 include_completed=False, max_workers=4)
                    result.append({"title": item["title"], "ok": bool(answer["ok"]),
                                   "skipped_completed": answer.get("skipped_completed_count", 0),
                                   "passed": sum(bool(r.get("passed")) for r in answer.get("results", [])),
                                   "total": answer.get("selected_count", 0)})
                except Exception:
                    result.append({"title": item["title"], "ok": False, "reason": "upstream_or_evaluation_error"})
                progress(result)
            return result
        finally:
            client.session.close()
