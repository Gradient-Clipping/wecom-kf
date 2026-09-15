import unittest
from unittest.mock import Mock, patch

from wecom_kf import dialog
from wecom_kf.store import Store


class ServiceSwitchTests(unittest.TestCase):
    def test_all_closed_overrides_every_phase_and_old_menu_without_cancelling_paid_work(self):
        for phase in ["idle", "account", "password", "verifying", "listing", "confirm", "paying", "purchasing", "running"]:
            state = {"phase": phase, "available_services": [], "blocked_until": 999,
                     "pending": {"password": "private"}, "job_id": "known-job", "actions": {"old": {"op": "run"}}}
            replies, job = dialog.advance(state, True, "1", "old", entered=True, now=1)
            self.assertEqual(replies, [dialog.text("暂无服务。")])
            self.assertIsNone(job)
            self.assertEqual(state["actions"], {})
            if phase in {"running", "paying", "purchasing"}:
                self.assertEqual(state["job_id"], "known-job")
            else:
                self.assertNotIn("pending", state)

    def test_partial_closure_renumbers_menu_and_blocks_old_service(self):
        state = {"phase": "idle", "available_services": [{"code": "other", "name": "其他应用"}]}
        menu = dialog.services(state)
        self.assertEqual(menu["msgmenu"]["list"][0]["click"]["content"], "1. 其他应用")
        state["actions"]["old"] = {"op": "educoder"}
        replies, job = dialog.advance(state, False, "头歌", "old")
        self.assertIsNone(job)
        self.assertNotEqual(state.get("phase"), "account")

    def test_persistent_flags_and_unknown_service(self):
        cursor = Mock()
        cursor.fetchall.return_value = [{"name": "service:educoder", "value": '{"enabled":false}'}]
        store = object.__new__(Store)
        self.assertFalse(store.service_states(cursor)[0]["enabled"])
        with patch.object(store, "transaction") as transaction:
            store.set_service_enabled("educoder", True, "admin")
            args = transaction.return_value.__enter__.return_value.execute.call_args.args[1]
            self.assertEqual(args[0], "service:educoder")
        with self.assertRaises(ValueError):
            store.set_service_enabled("unknown", False, "admin")
