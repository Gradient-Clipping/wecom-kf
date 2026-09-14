import unittest
from wecom_kf import dialog as d


def action(state, op):
    return next(k for k, v in state["actions"].items() if v["op"] == op)


def items(count):
    return [{"title": f"实训{i}" * 40, "course_name": "课堂", "homework_id": str(i), "course_identifier": "course"} for i in range(count)]


class DialogTests(unittest.TestCase):
    def test_service_menu_is_numbered_and_accepts_full_width_number(self):
        state = {}
        message = d.services(state)
        self.assertEqual(message["msgmenu"]["list"][0]["click"]["content"], "1. 头歌")
        d.advance(state, None, "１", now=1)
        self.assertEqual(state["phase"], "account")

    def test_normalization_and_validation(self):
        self.assertEqual(d.selection("１， ２、\n３\u200b\ufeff", 4), [0, 1, 2])
        self.assertEqual(d.selection("０", 3), [0, 1, 2])
        self.assertEqual(d.selection("2,2,1", 3), [1, 0])
        for value in ("", "0,1", "-1", "1.5", "5", "1,,2", "1;2", "9" * 100):
            with self.assertRaises(ValueError):
                d.selection(value, 4)

    def test_password_preserves_all_characters(self):
        state = {"phase": "password", "pending": {"account": "me"}}
        password = "  密码Ａ\u200b\n "
        replies, kind = d.advance(state, None, password, now=1)
        self.assertEqual(kind, "verify")
        self.assertEqual(state["pending"]["password"], password)
        self.assertNotIn(password, str(replies))

    def test_login_lockout_and_expiry_do_not_reset_failures(self):
        state = {}
        for count in (1, 2, 3):
            replies = d.verified(state, None, invalid=True, now=1)
            self.assertEqual(state["failures"], count)
        for value in ("菜单", "头歌", "1", "任意消息"):
            self.assertEqual(d.advance(state, None, value, now=800)[0], [d.text(d.BLOCKED)])
        self.assertEqual(state["blocked_until"], 86401)
        d.advance(state, None, "你好", now=86402)
        self.assertEqual(state["failures"], 0)
        state = {"failures": 2, "phase": "password", "pending": {"password": "secret"}, "expires_at": 10}
        d.advance(state, None, "secret", now=11)
        self.assertEqual(state["failures"], 2)
        self.assertNotIn("pending", state)

    def test_transient_errors_do_not_count(self):
        state = {"failures": 2, "pending": {"password": "secret"}}
        d.verified(state, None, unavailable=True, now=5)
        self.assertEqual(state["failures"], 2)
        self.assertEqual(state["pending"], {})

    def test_full_flow_reselection_and_stale_confirm(self):
        state = {}
        d.advance(state, None, "hello", now=1)
        d.advance(state, None, "头歌", action(state, "educoder"), now=1)
        d.advance(state, None, "account", now=1)
        self.assertEqual(d.advance(state, None, "password", now=1)[1], "verify")
        d.verified(state, {"login": "login", "username": "user", "phone": "138****1234"})
        self.assertEqual(d.advance(state, None, "确认绑定", action(state, "bind"), now=1)[1], "bind_and_list")
        d.listed(state, items(30))
        self.assertIsNone(d.advance(state, True, "1、9", now=1)[1])
        old = action(state, "run")
        d.advance(state, True, "２，４", now=1)
        self.assertEqual(state["selected"], [1, 3])
        self.assertEqual(d.advance(state, True, "确认开始", old, now=1)[0], [d.text(d.INVALID)])
        self.assertEqual(d.advance(state, True, "确认开始", action(state, "run"), now=1)[1], "solve")
        self.assertIsNone(d.advance(state, True, "确认开始", old, now=1)[1])

    def test_five_minutes_latest_reply_and_running_exception(self):
        state = {"phase": "confirm", "selected": [0], "items": items(2), "expires_at": 301}
        d.confirmation(state)
        old = action(state, "run")
        self.assertIsNone(d.advance(state, True, "确认", old, now=301)[1])
        self.assertEqual(state["phase"], "idle")
        state = {"phase": "running", "expires_at": 1, "job_id": "abc"}
        d.advance(state, True, "hi", now=99999)
        self.assertEqual(state["phase"], "running")
        self.assertEqual(state["job_id"], "abc")

    def test_every_item_has_menu_and_byte_limits(self):
        state = {"items": items(31)}
        seen = set()
        for page in range(6):
            msg = d.list_menu(state, page)["msgmenu"]
            self.assertLessEqual(len(msg["list"]), 10)
            for entry in msg["list"]:
                self.assertLessEqual(len(entry["click"]["content"].encode()), 128)
                a = state["actions"][entry["click"]["id"]]
                if a["op"] == "pick":
                    seen.add(a["value"])
        self.assertEqual(seen, {str(n) for n in range(32)})

    def test_bound_user_skips_credentials_and_disabled_execution(self):
        state = {"phase": "idle"}
        self.assertEqual(d.advance(state, {"account": "one"}, "头歌")[1], "list")
        d.listed(state, items(2))
        d.advance(state, True, "0")
        self.assertIsNone(d.advance(state, True, "start", action(state, "run"), execution_enabled=False)[1])

    def test_foreign_menu_id_rejected(self):
        a, b = {}, {}
        d.services(a)
        d.services(b)
        self.assertEqual(d.advance(b, None, "头歌", action(a, "educoder"))[0], [d.text(d.INVALID)])


if __name__ == "__main__":
    unittest.main()
