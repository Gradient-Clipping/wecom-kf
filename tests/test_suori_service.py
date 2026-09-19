import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wecom_kf.suori_service import ShuoriService, ShuoriUnavailable


class FakeClient:
    username = "student"

    def __init__(self, tasks):
        self.tasks = tasks
        self.logged = []
        self.entered = 0
        self.closed = 0

    def login(self, account, password):
        self.logged.append((account, password))

    def enter_training(self):
        self.entered += 1
        return {"PageStatusOk": True}

    def list_tasks(self):
        return list(self.tasks)

    def close(self):
        self.closed += 1


class FakeRun:
    state = {"score": 100, "maximum_score": 100}

    def as_dict(self):
        return {"stage": "scored", "score": 100, "maximum_score": 100}


class FakeWorkflow:
    instances = []

    def __init__(self, client, **kwargs):
        self.client = client
        self.kwargs = kwargs
        self.calls = []
        self.__class__.instances.append(self)

    def run_task(self, task_id, *, term_id, submit):
        self.calls.append((task_id, term_id, submit))
        return FakeRun()

    def verify_task(self, run):
        self.verified = run
        return run


class ShuoriServiceTests(unittest.TestCase):
    def setUp(self):
        self.tasks = [
            {"ID": 7, "TermID": 3, "HWName": "数据库作业", "CourseName": "数据库", "SubmittedCount": 0},
            {"ID": 8, "TermID": 3, "HWName": "网络作业", "CourseName": "网络", "SubmittedCount": 1,
             "RemainingCount": 2},
        ]
        self.clients = []

        def factory(_base_url, **_kwargs):
            client = FakeClient(self.tasks)
            self.clients.append(client)
            return client

        self.factory = factory
        FakeWorkflow.instances.clear()

    def service(self, **kwargs):
        return ShuoriService(
            SimpleNamespace(suori_base_url="http://example.test/srpt"),
            client_factory=self.factory,
            workflow_factory=FakeWorkflow,
            **kwargs,
        )

    def binding(self):
        return {"account": "student", "password": "secret", "login_no": "student"}

    def test_import_and_verify_do_not_require_optional_runtime(self):
        with patch("wecom_kf.suori_service.importlib.import_module", side_effect=ModuleNotFoundError("pyzipper")):
            service = ShuoriService(SimpleNamespace(suori_base_url="http://example.test"))
            # Importing this adapter is enough for a customer-service process to start.
            with self.assertRaises(ShuoriUnavailable):
                service._new_client()

    def test_verify_and_list_follow_platform_task_fields(self):
        service = self.service()
        self.assertEqual(service.verify("student", "secret"), {
            "login": "student", "username": "student", "phone": "未提供"
        })
        items = service.list_homeworks(self.binding())
        self.assertEqual(items[0]["task_id"], 7)
        self.assertEqual(items[0]["term_id"], 3)
        self.assertEqual(items[0]["remaining_challenges"], 1)
        self.assertEqual(items[1]["remaining_challenges"], 2)
        self.assertEqual(self.clients[-1].logged, [("student", "secret")])

    def test_snapshot_is_credential_free_and_rechecks_current_task(self):
        service = self.service()
        snapshot = service.snapshot(self.binding(), [{"task_id": 7, "term_id": 3, "title": "旧名称"}])
        self.assertEqual(snapshot[0]["title"], "数据库作业")
        self.assertNotIn("password", snapshot[0])
        self.assertNotIn("account", snapshot[0])

    def test_billing_one_unit_per_task_and_rejects_duplicates(self):
        snapshot = [{"task_id": 7, "term_id": 3, "title": "数据库作业", "billing_units": 1}]
        self.assertEqual(ShuoriService.billing_items(snapshot), [{
            "id": "3:7", "name": "数据库作业", "quantity": 1,
            "billing_attributes": {"kind": "task", "service": "shuori"},
        }])
        with self.assertRaises(ValueError):
            ShuoriService.billing_items(snapshot + snapshot)

    def test_default_full_score_and_no_submit(self):
        service = self.service()
        self.assertEqual(service.grading_mode, "full_score")
        progress = []
        result = service.solve(self.binding(), [{"task_id": 7, "term_id": 3, "title": "数据库作业"}], progress.append)
        self.assertTrue(result["final"])
        self.assertFalse(result["has_error"])
        self.assertFalse(result["submitted"])
        self.assertEqual(FakeWorkflow.instances[-1].kwargs["grading_mode"], "full_score")
        self.assertEqual(FakeWorkflow.instances[-1].calls, [(7, 3, False)])
        self.assertTrue(progress)

    def test_submit_requires_explicit_strategy(self):
        service = self.service()
        service.solve(self.binding(), [{"task_id": 7, "term_id": 3, "title": "数据库作业"}], lambda _value: None, submit=True)
        self.assertEqual(FakeWorkflow.instances[-1].calls, [(7, 3, True)])
        self.assertIsNotNone(FakeWorkflow.instances[-1].verified)

    def test_failure_contains_score_diagnostic(self):
        class FailedRun:
            state = {"score": 72, "maximum_score": 100}

            def as_dict(self):
                return {"stage": "scored", "score": 72, "maximum_score": 100}

        class FailedWorkflow(FakeWorkflow):
            def run_task(self, task_id, *, term_id, submit):
                return FailedRun()

        service = ShuoriService(
            SimpleNamespace(suori_base_url="http://example.test/srpt"),
            client_factory=self.factory,
            workflow_factory=FailedWorkflow,
        )
        result = service.solve(self.binding(), [{"task_id": 7, "term_id": 3, "title": "数据库作业"}], lambda _value: None)
        self.assertIn("72/100", result["failures"][0])
        self.assertNotEqual(result["failures"][0], "任务：数据库作业")


if __name__ == "__main__":
    unittest.main()
