import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from wecom_kf.educoder_service import EduCoderService


class ServiceTests(unittest.TestCase):
    def test_homework_list_exposes_remaining_challenges(self):
        client = Mock()
        client.ensure_logged_in.return_value = {"login": "login"}
        client.courses.items.return_value = [{"first_category_url": "/classrooms/course/announcement", "name": "课堂"}]
        client.shixun_homeworks.filtered.return_value = [
            {"homework_id": 1, "name": "实验", "challenge_count": 5, "finished_challenge_count": 2}]
        service = EduCoderService(SimpleNamespace())
        service.client = Mock(return_value=client)
        items = service.list_homeworks({"account": "a", "password": "p", "login_no": "login"})
        self.assertEqual(items[0]["remaining_challenges"], 3)
        client.shixun_homeworks.homework.assert_not_called()

    def test_progress_uses_solver_position_not_title_matching(self):
        client = Mock()
        client.ensure_logged_in.return_value = {"login": "login"}
        with tempfile.TemporaryDirectory() as directory:
            bank = Path(directory) / "bank.sqlite"
            bank.touch()
            service = EduCoderService(SimpleNamespace(bank_path=str(bank)))
            service.client = Mock(return_value=client)
            progress = []

            def fake_solver(*args, **kwargs):
                solver = Mock()

                def solve(*_args, **_kwargs):
                    kwargs["on_event"]({"event": "question_ready", "position": 3, "title": "不同的题目标题"})
                    return {"results": [{"position": 3, "challenge": "不同的题目标题", "passed": False}],
                            "skipped_completed_count": 0, "selected_count": 1}

                solver.solve_shixun.side_effect = solve
                return solver

            with patch("wecom_kf.educoder_service.ShixunSolver", side_effect=fake_solver):
                result = service.solve({"account": "a", "password": "p", "login_no": "login"},
                                       [{"title": "实验", "course_identifier": "c", "homework_id": "1",
                                         "challenges": [{"challenge_id": 1, "name": "旧标题", "position": 3}]}],
                                       lambda value: progress.append(value["current"] if value else None))
        self.assertTrue(any("第3关" in value for value in progress if value))
        self.assertIn("第3关", result["failures"][0])
        self.assertNotIn("?", result["failures"][0])


if __name__ == "__main__":
    unittest.main()
