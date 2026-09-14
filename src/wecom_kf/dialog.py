"""Pure conversation transitions; no network, database, or code execution."""

import re
import secrets
import unicodedata

INVALID = "输入无效，请重新输入"
BLOCKED = "账号验证连续失败3次，客服服务已暂停24小时，请24小时后再试。"
PAGE_SIZE = 6


def normalize(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value)
                   if not c.isspace() and unicodedata.category(c) != "Cf").replace("、", ",")


def selection(value, count):
    value = normalize(value)
    if value == "0" and count:
        return list(range(count))
    if not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", value) or len(value) > 4096:
        raise ValueError(INVALID)
    parts = value.split(",")
    if any(len(p) > 9 for p in parts):
        raise ValueError(INVALID)
    numbers = [int(p) for p in parts]
    if any(n < 1 or n > count for n in numbers):
        raise ValueError(INVALID)
    return list(dict.fromkeys(n - 1 for n in numbers))


def clip(value, limit):
    value = str(value)
    if len(value.encode()) <= limit:
        return value
    return value.encode()[:limit - 3].decode("utf-8", errors="ignore") + "..."


def text(value):
    return {"msgtype": "text", "text": {"content": clip(value, 2048)}}


def menu(state, title, choices, tail="", lines=()):
    # Store opaque menu actions with the customer, never trust a client-supplied index.
    state["actions"] = {}
    entries = []
    for label, action in choices:
        key = secrets.token_hex(16)
        state["actions"][key] = action
        entries.append({"type": "click", "click": {"id": key, "content": clip(label, 128)}})
    entries += [{"type": "text", "text": {"content": clip(line, 256)}} for line in lines]
    assert len(choices) <= 10 and len(entries) <= 50
    return {"msgtype": "msgmenu", "msgmenu": {
        "head_content": clip(title, 1024), "list": entries, "tail_content": clip(tail, 1024)}}


def services(state):
    return menu(state, "请选择服务", [("1. 头歌", {"op": "educoder"})], "点击菜单或回复服务序号。")


def list_menu(state, page=0):
    items = state["items"]
    pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 0 or page >= pages:
        return text(INVALID)
    start = page * PAGE_SIZE
    choices = [(f"{i + 1}. {item['title']}", {"op": "pick", "value": str(i + 1)})
               for i, item in enumerate(items[start:start + PAGE_SIZE], start)]
    choices.append(("0. 全部实训", {"op": "pick", "value": "0"}))
    if page:
        choices.append(("上一页", {"op": "page", "page": page - 1}))
    if page + 1 < pages:
        choices.append(("下一页", {"op": "page", "page": page + 1}))
    choices.append(("返回服务菜单", {"op": "home"}))
    return menu(state, f"未全部完成的实训：共{len(items)}个，第{page + 1}/{pages}页", choices,
                "点击单个实训，或输入序号（如1,2、3）；0代表全部。可跨页输入序号。")


def confirmation(state, page=0):
    selected = state["selected"]
    pages = (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 0 or page >= pages:
        return text(INVALID)
    shown = selected[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    lines = [f"{i + 1}. {state['items'][i]['title']}（{state['items'][i]['course_name']}）" for i in shown]
    choices = [("确认开始", {"op": "run"}), ("返回实训列表", {"op": "page", "page": 0})]
    if page:
        choices.append(("上一页已选", {"op": "selected_page", "page": page - 1}))
    if page + 1 < pages:
        choices.append(("下一页已选", {"op": "selected_page", "page": page + 1}))
    return menu(state, f"已选{len(selected)}个实训，请核对后确认（第{page + 1}/{pages}页）", choices,
                "若有误可以直接重新输入序号重选。", lines)


def begin_list(state):
    state.update(phase="listing", actions={})
    return [text("正在获取未全部完成的实训，请稍候。")], "list"


def advance(state, binding, content, menu_id="", *, entered=False, now=0, execution_enabled=True):
    """Mutate one customer's state; return replies and at most one queued job kind."""
    if state.get("blocked_until", 0) > now:
        return [text(BLOCKED)], None
    if state.get("blocked_until"):
        state.update(blocked_until=0, failures=0, phase="idle", actions={})
    phase = state.get("phase", "idle")
    if phase != "running" and state.get("expires_at", now + 1) <= now:
        for key in ("pending", "profile", "items", "selected", "actions", "job_id"):
            state.pop(key, None)
        state.update(phase="idle", expires_at=now + 300)
        return [services(state)], None
    if entered:
        if phase not in {"running", "verifying", "listing"}:
            state.update(phase="idle", pending={}, selected=[], actions={})
        return [services(state)], None
    if phase in {"running", "verifying", "listing"}:
        msg = {"running": "任务已确认，正在排队或执行，完成后会通知你。",
               "verifying": "正在验证账号，请稍候。", "listing": "正在获取实训，请稍候。"}[phase]
        return [text(msg)], None
    action = state.get("actions", {}).get(menu_id) if menu_id else None
    if menu_id and not action:
        return [text(INVALID)], None
    op = action.get("op") if action else None
    if op == "home" or (not menu_id and phase != "password" and normalize(content or "") == "菜单"):
        state.update(phase="idle", pending={}, actions={})
        return [services(state)], None
    if op == "educoder" or (phase == "idle" and normalize(content or "") in {"头歌", "1"}):
        if binding:
            return begin_list(state)
        state.update(phase="account", pending={}, actions={})
        return [text("请输入你的头歌账号。每个微信只能绑定一个头歌账号，后续不可更改。")], None
    if phase == "idle":
        replies = [services(state)]
        if state.get("last_result"):
            replies.insert(0, text(state["last_result"]))
        return replies, None
    if phase == "account":
        value = (content or "").strip()
        if menu_id or not value or len(value) > 256 or any(c in value for c in "\r\n\x00"):
            return [text(INVALID)], None
        state.update(phase="password", pending={"account": value}, actions={})
        return [text("请输入头歌密码。验证成功并确认后不可更改。")], None
    if phase == "password":
        # Passwords are opaque: never normalize width, trim spaces, or echo them.
        if menu_id or not content or len(content) > 1024 or "\x00" in content:
            return [text(INVALID)], None
        state["pending"]["password"] = content
        state.update(phase="verifying", actions={})
        return [text("正在验证账号，请稍候。")], "verify"
    if phase == "bind":
        if op == "bind":
            state.update(phase="listing", actions={})
            return [text("绑定成功，正在获取未全部完成的实训。")], "bind_and_list"
        if op == "cancel_bind":
            state.update(phase="account", pending={}, actions={})
            return [text("未绑定，请重新输入头歌账号。")], None
        return [text(INVALID)], None
    if phase in {"select", "confirm"}:
        if op == "run" and phase == "confirm":
            if not execution_enabled:
                return [text("执行服务暂未开放，请稍后再试。")], None
            state.update(phase="running", actions={})
            return [text("已确认，任务已加入队列，结束后会通知你。")], "solve"
        if op == "page":
            state["phase"] = "select"
            return [list_menu(state, action["page"])], None
        if op == "selected_page" and phase == "confirm":
            return [confirmation(state, action["page"])], None
        try:
            indices = selection(action["value"] if op == "pick" else content or "", len(state["items"]))
        except ValueError:
            return [text(INVALID)], None
        state.update(phase="confirm", selected=indices)
        return [confirmation(state)], None
    return [text(INVALID)], None


def verified(state, profile, *, invalid=False, unavailable=False, now=0):
    if invalid:
        failures = state.get("failures", 0) + 1
        state.update(failures=failures, pending={}, phase="account", actions={})
        if failures >= 3:
            state.update(blocked_until=now + 86400, phase="idle")
            return [text(BLOCKED)]
        return [text(f"账号或密码错误，剩余{3 - failures}次重试机会。请重新输入头歌账号。")]
    if unavailable:
        state.update(pending={}, phase="account", actions={})
        return [text("头歌暂时无法验证（网络、验证码或服务异常），请稍后重试。")]
    state.update(phase="bind", failures=0, blocked_until=0, profile=profile)
    label = f"验证成功\n登录号：{profile['login']}\n用户名：{profile['username']}\n手机号：{profile['phone']}"
    return [menu(state, label, [("确认绑定", {"op": "bind"}), ("重新输入账号", {"op": "cancel_bind"})],
                 "确认后此微信将绑定该账号，后续不可更改。")]


def listed(state, items, *, failed=False):
    if failed:
        state.update(phase="idle", actions={})
        return [text("实训查询失败，请稍后重试。"), services(state)]
    state.update(items=items, selected=[], actions={})
    if not items:
        state["phase"] = "idle"
        return [text("当前没有未全部完成的实训。"), services(state)]
    state["phase"] = "select"
    return [list_menu(state)]
