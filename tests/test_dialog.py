import unittest
from wecom_kf import dialog as d


def action(state, op):
    return next(k for k, v in state["actions"].items() if v["op"] == op)


def items(count):
    return [{"title": f"实训{i}" * 40, "course_name": "课堂", "remaining_challenges": i + 1,
             "homework_id": str(i), "course_identifier": "course"} for i in range(count)]


class DialogTests(unittest.TestCase):
    def test_service_menu_is_numbered_and_accepts_full_width_number(self):
        state = {}
        message = d.services(state)
        self.assertEqual(message["msgmenu"]["list"][0]["click"]["content"], "1. 头歌")
        d.advance(state, None, "１", now=1)
        self.assertEqual(state["phase"], "account")

    def test_human_support_menu_and_typed_zero_with_educoder_closed(self):
        state = {"available_services": [], "human_support_enabled": True, "phase": "idle"}
        msg = d.services(state)
        self.assertEqual(msg["msgmenu"]["list"][0]["click"]["content"], "0. 人工客服")
        for content, menu_id in (("０", ""), ("人工客服", action(state, "human_support"))):
            replies, kind = d.advance(state, None, content, menu_id, now=1)
            self.assertIsNone(kind)
            self.assertEqual(replies[0]["text"]["content"], "请长按扫描图中二维码添加人工客服。")
            self.assertEqual(replies[1], {"msgtype": "image", "image": {"asset": "human_service_card"}})
        state["human_support_enabled"] = False
        self.assertEqual(d.advance(state, None, "0", now=2)[0], [d.text("暂无服务。")])

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
        self.assertIsNone(d.advance(state, True, "1、9", now=1, payment_enabled=True)[1])
        old = action(state, "run")
        d.advance(state, True, "２，４", now=1, payment_enabled=True)
        self.assertEqual(state["selected"], [1, 3])
        self.assertEqual(d.advance(state, True, "确认开始", old, now=1)[0], [d.text(d.INVALID)])
        self.assertIsNone(d.advance(state, True, "确认开始", old, now=1)[1])
        self.assertEqual(d.advance(state, True, "确认购买", action(state, "run"), now=1,
                                   payment_enabled=True)[1], "purchase")
        self.assertIsNone(d.advance(state, True, "确认开始", old, now=1)[1])

    def test_five_minutes_latest_reply_and_running_exception(self):
        state = {"phase": "confirm", "selected": [0], "items": items(2), "expires_at": 301,
                 "payment_ready": True}
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
                    if a["value"] == "0":
                        self.assertEqual(entry["click"]["content"], "\n0. 选择全部实训")
                if a["op"] == "home":
                    self.assertEqual(entry["click"]["content"], "\n返回服务菜单")
        self.assertEqual(seen, {str(n) for n in range(32)})

    def test_bound_user_skips_credentials_and_disabled_execution(self):
        state = {"phase": "idle"}
        self.assertEqual(d.advance(state, {"account": "one"}, "头歌")[1], "list")
        d.listed(state, items(2))
        d.advance(state, True, "0", payment_enabled=True)
        self.assertIsNone(d.advance(state, True, "start", action(state, "run"),
                                    execution_enabled=False, payment_enabled=True)[1])

    def test_confirmation_shows_remaining_challenges_and_never_executes_free(self):
        state = {"items": items(2), "selected": [1], "phase": "confirm"}
        msg = d.confirmation(state)
        self.assertIn("待做 2 关", msg["msgmenu"]["list"][0]["text"]["content"])
        self.assertNotIn("run", [a["op"] for a in state["actions"].values()])
        state["actions"]["old"] = {"op": "run"}
        self.assertIsNone(d.advance(state, True, "", "old", payment_enabled=False)[1])
        self.assertEqual(state["phase"], "confirm")

    def test_progress_limit_and_failure_pages(self):
        state = {"phase": "running", "progress_checks": 20, "progress_page": 0}
        failures = [f"第{i}关" for i in range(17)]
        msg = d.progress_reply(state, {"failures": failures}, "running")
        self.assertEqual(len([e for e in msg["msgmenu"]["list"] if e["type"] == "text"]), 6)
        self.assertNotIn("progress", [a["op"] for a in state["actions"].values()])
        page = action(state, "progress_page")
        self.assertEqual(d.advance(state, True, "", page)[1], "progress_page")

    def test_concise_payment_and_progress_copy(self):
        self.assertIn("因微信限制，最低支付 ¥1.00，有效期 5 分钟。", d.PAYMENT_WARNING)
        state = {"phase": "running", "progress_checks": 0}
        self.assertEqual(d.queued(state)["msgmenu"]["tail_content"], "（0/20）")
        state["progress_checks"] = 3
        reply = d.progress_reply(state, {"failures": ["第1关"]}, "running")["msgmenu"]
        self.assertIn("（3/20）", reply["tail_content"])
        self.assertNotIn("最低保留1元", reply["tail_content"])

    def test_foreign_menu_id_rejected(self):
        a, b = {}, {}
        d.services(a)
        d.services(b)
        self.assertEqual(d.advance(b, None, "头歌", action(a, "educoder"))[0], [d.text(d.INVALID)])


if __name__ == "__main__":
    unittest.main()
