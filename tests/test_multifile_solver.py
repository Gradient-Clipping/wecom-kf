import json
import unittest
from unittest.mock import Mock, patch

from educoder.deepseek import DeepSeekConfig, SubmissionToolCall
from educoder.solver import ShixunSolver


class MultiFileSolverTests(unittest.TestCase):
    def setup_solver(self, path, match):
        master, client, bank = Mock(), Mock(), Mock()
        master.clone.return_value = client
        client.tasks.get.return_value = {
            "game": {"identifier": "game", "evaluate_count": 0},
            "myshixun": {"identifier": "repo"},
            "challenge": {"subject": "Q", "path": path, "task_pass": "Full statement"},
        }
        files = {"src/main.py": "starter\n", "src/cmp.py": "compare()\n",
                 "src/test.sh": "python src/main.py\n"}
        client.tasks.read_file.side_effect = lambda game, filename, **kwargs: files[filename]

        def update(game, filename, content, **kwargs):
            files[filename] = content
            return {"commitID": "commit"}

        client.tasks.update_file.side_effect = update
        client.tasks.build.return_value = {"status": 1}
        client.tasks.wait_status.return_value = {
            "status": 2, "test_sets_count": 1, "sets_error_count": 0,
            "test_sets": [{"result": True, "compile_success": 1}],
        }
        bank.match.return_value = match
        bank.add.return_value = 7
        solver = ShixunSolver(master, bank, deepseek=DeepSeekConfig("test"))
        return solver, client, bank, files

    def solve(self, solver):
        with patch("educoder.solver.fetch_question_images", return_value=[]):
            return solver.solve_challenge("game", homework_id=1, shixun_title="S",
                                          allow_skip=False, position=4)

    def test_bank_uses_only_primary_file_for_three_path_task(self):
        match = {"answer_text": "solved\n", "title": "Q", "shixun_title": "S"}
        solver, client, bank, files = self.setup_solver(
            "src/main.py；src/cmp.py；src/test.sh；", match)
        result = self.solve(solver)
        self.assertTrue(result["passed"])
        self.assertEqual(result["position"], 4)
        self.assertEqual(files, {"src/main.py": "solved\n", "src/cmp.py": "compare()\n",
                                 "src/test.sh": "python src/main.py\n"})
        self.assertEqual([call.args[1] for call in client.tasks.update_file.call_args_list], ["src/main.py"])
        self.assertEqual(bank.add.call_args.kwargs["answer_text"], "solved\n")

    def test_ai_receives_read_only_files_and_submits_primary_only(self):
        solver, client, bank, files = self.setup_solver(
            "src/main.py;src/cmp.py;src/test.sh;", None)
        conversations = []

        class FakeConversation:
            def __init__(self, config, content):
                self.messages = [{"role": "user", "content": content}]
                self.usage, self.api_attempts = [], []
                conversations.append(self)

            def next_submission(self):
                return SubmissionToolCall("call_1", "solved\n")

            def submit_result(self, call, result):
                self.messages.append({"role": "tool", "content": json.dumps(result)})

        solver.conversation_factory = FakeConversation
        result = self.solve(solver)
        self.assertTrue(result["passed"])
        context = json.loads(conversations[0].messages[0]["content"][0]["text"])
        self.assertEqual(context["target_file"], "src/main.py")
        self.assertEqual(context["read_only_files"], {
            "src/cmp.py": "compare()\n", "src/test.sh": "python src/main.py\n"})
        self.assertEqual([call.args[1] for call in client.tasks.update_file.call_args_list], ["src/main.py"])
        self.assertEqual(files["src/cmp.py"], "compare()\n")
        self.assertEqual(files["src/test.sh"], "python src/main.py\n")


if __name__ == "__main__":
    unittest.main()
