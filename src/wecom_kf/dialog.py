"""Pure conversation transitions; no network, database, or code execution."""

import re
import secrets
import unicodedata
from .service_catalog import available

INVALID = "输入无效，请重新输入"
BLOCKED = "账号验证连续失败3次，客服服务已暂停24小时，请24小时后再试。"
PAGE_SIZE = 6
PROGRESS_LIMIT = 20
FAILURE_PAGE_SIZE = 6
PAYMENT_WARNING = "付款提示\n\n因微信限制，最低支付 ¥1.00，有效期 5 分钟。\n完成付款后，再点击“我已付款，查询到账”。"


def queued(state, *, paid=False):
    title = ("付款成功，正在开始处理。\n\n" if paid else "") + "已确认，任务已加入队列。\n结束后会通知你。"
    return menu(state, title, [("查询当前进度", {"op": "progress"})],
                f"（{state.get('progress_checks', 0)}/{PROGRESS_LIMIT}）")


def progress_reply(state, value, status="running"):
    value = value if isinstance(value, dict) else {}
    labels = {"pending": "排队中", "running": "执行中", "complete": "已结束", "failed": "已结束", "interrupted": "已中断"}
    active = status in {"pending", "running"}
    remaining = max(0, PROGRESS_LIMIT - state.get("progress_checks", 0))
    message = (f"任务进度\n\n状态：{labels.get(status, '待核对')}\n"
               f"已通过实训：{value.get('passed_homeworks', 0)}/{value.get('total_homeworks', 0)}\n\n"
               f"正在处理：\n{value.get('current') or '等待处理'}")
    failures = value.get("failures") or []
    page = max(0, min(state.get("progress_page", 0), max(0, (len(failures) - 1) // FAILURE_PAGE_SIZE)))
    choices = [("再次查询进度", {"op": "progress", "page": 0})] if not active or remaining else []
    lines, tail = [], ""
    if failures:
        message += f"\n\n已失败/跳过关卡（第{page + 1}页）："
        lines = failures[page * FAILURE_PAGE_SIZE:(page + 1) * FAILURE_PAGE_SIZE]
        if state.get("purchase_id"):
            tail = "失败/跳过的关卡会按数量自动退款。Apple支付退款需售后处理。"
        if page:
            choices.append(("上一页失败关卡", {"op": "progress_page", "page": page - 1}))
        if (page + 1) * FAILURE_PAGE_SIZE < len(failures):
            choices.append(("下一页失败关卡", {"op": "progress_page", "page": page + 1}))
    if active:
        tail = (tail + "\n" if tail else "") + f"（{state.get('progress_checks', 0)}/{PROGRESS_LIMIT}）"
    return menu(state, message, choices, tail, lines)


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
    entries = [{"type": "text", "text": {"content": clip(line, 256)}} for line in lines]
    for label, action in choices:
        key = secrets.token_hex(16)
        state["actions"][key] = action
        entries.append({"type": "click", "click": {"id": key, "content": clip(label, 128)}})
    assert len(choices) <= 10 and len(entries) <= 50
    return {"msgtype": "msgmenu", "msgmenu": {
        "head_content": clip(title, 1024), "list": entries, "tail_content": clip(tail, 1024)}}


def services(state):
    choices = [(f"{i}. {item['name']}", {"op": item["code"]}) for i, item in enumerate(available(state), 1)]
    if state.get("human_support_enabled"):
        choices.insert(0, ("0. 人工客服", {"op": "human_support"}))
    if not choices:
        state["actions"] = {}
        return text("暂无服务。")
    return menu(state, "请选择服务：", choices, "也可回复上面的序号。")


def list_menu(state, page=0):
    items = state["items"]
    pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 0 or page >= pages:
        return text(INVALID)
    start = page * PAGE_SIZE
    choices = [(f"{i + 1}. {item['title']}", {"op": "pick", "value": str(i + 1)})
               for i, item in enumerate(items[start:start + PAGE_SIZE], start)]
    choices.append(("\n0. 选择全部实训", {"op": "pick", "value": "0"}))
    if page:
        choices.append(("上一页", {"op": "page", "page": page - 1}))
    if page + 1 < pages:
        choices.append(("下一页", {"op": "page", "page": page + 1}))
    choices.append(("\n返回服务菜单", {"op": "home"}))
    return menu(state, f"未全部完成的实训\n共 {len(items)} 个 · 第 {page + 1}/{pages} 页", choices,
                "单选可点击；多选请回复序号，如 1,2、3。\n回复 0 选择全部，可跨页输入序号。")


def confirmation(state, page=0):
    selected = state["selected"]
    pages = (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE
    if page < 0 or page >= pages:
        return text(INVALID)
    shown = selected[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    lines = [f"{i + 1}. {clip(state['items'][i]['title'], 180)}（待做 {state['items'][i]['remaining_challenges']} 关）" for i in shown]
    choices = [("返回实训列表", {"op": "page", "page": 0})]
    if page:
        choices.append(("上一页已选", {"op": "selected_page", "page": page - 1}))
    if page + 1 < pages:
        choices.append(("下一页已选", {"op": "selected_page", "page": page + 1}))
    if state.get("payment_ready"):
        choices.append(("确认选择并创建订单", {"op": "run"}))
    tail = "有误可直接回复序号重选。"
    if not state.get("payment_ready"):
        tail += "\n支付服务暂未开放，当前不能开始任务。"
    return menu(state, f"已选 {len(selected)} 个实训\n请核对（第 {page + 1}/{pages} 页）：", choices, tail, lines)


def begin_list(state):
    state.update(phase="listing", actions={})
    return [text("正在获取未全部完成的实训，请稍候。")], "list"


def advance(state, binding, content, menu_id="", *, entered=False, now=0, execution_enabled=True, payment_enabled=False):
    """Mutate one customer's state; return replies and at most one queued job kind."""
    enabled = {item["code"] for item in available(state)}
    if (not enabled and not state.get("human_support_enabled")) or (state.get("phase", "idle") != "idle" and "educoder" not in enabled):
        if state.get("phase") not in {"running", "paying", "purchasing"}:
            for key in ("pending", "profile", "items", "selected", "job_id"):
                state.pop(key, None)
            state["phase"] = "idle"
        state["actions"] = {}
        return [services(state)], None
    if state.get("blocked_until", 0) > now:
        return [text(BLOCKED)], None
    if state.get("blocked_until"):
        state.update(blocked_until=0, failures=0, phase="idle", actions={})
    phase = state.get("phase", "idle")
    action = state.get("actions", {}).get(menu_id) if menu_id else None
    if state.get("human_support_enabled") and (action and action.get("op") == "human_support" or
                                               phase == "idle" and not menu_id and normalize(content or "") == "0"):
        return [text("请长按扫描图中二维码添加人工客服。"),
                {"msgtype": "image", "image": {"asset": "human_service_card"}}], None
    if phase not in {"running", "paying", "purchasing"} and state.get("expires_at", now + 1) <= now:
        for key in ("pending", "profile", "items", "selected", "actions", "job_id"):
            state.pop(key, None)
        state.update(phase="idle", expires_at=now + 300)
        return [services(state)], None
    if entered:
        if phase in {"paying", "purchasing", "running"}:
            return [text("当前订单或任务仍在处理中，请查询付款结果或任务进度。")], None
        if phase not in {"running", "verifying", "listing"}:
            state.update(phase="idle", pending={}, selected=[], actions={})
        return [services(state)], None
    if phase == "running":
        action = state.get("actions", {}).get(menu_id) if menu_id else None
        if action and action.get("op") == "progress_page":
            state["progress_page"] = action["page"]
            return [], "progress_page"
        if (action and action.get("op") == "progress") or normalize(content or "") in {"查询进度", "查询当前进度"}:
            state["progress_page"] = action.get("page", 0) if action else 0
            return [], "progress"
        return [queued(state)], None
    if phase in {"paying", "purchasing"}:
        action = state.get("actions", {}).get(menu_id) if menu_id else None
        if phase == "paying" and action and action.get("op") == "payment_check":
            state["actions"] = {}
            return [], "payment_check"
        return [text("正在创建或核对订单，请稍候。")], None
    if phase in {"verifying", "listing"}:
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
    typed_service = next((item["code"] for i, item in enumerate(available(state), 1)
                          if normalize(content or "") in {item["name"], str(i)}), None) if phase == "idle" else None
    if "educoder" in enabled and (op == "educoder" or typed_service == "educoder"):
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
        state["payment_ready"] = payment_enabled
        if op == "run" and phase == "confirm":
            if not execution_enabled:
                return [text("执行服务暂未开放，请稍后再试。")], None
            if not payment_enabled:
                return [text("支付服务暂未开放，当前不能开始任务。")], None
            state.update(phase="purchasing", actions={})
            return [text("正在核对待做关卡并创建订单，请稍候。")], "purchase"
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
        return ([text(PAYMENT_WARNING)] if payment_enabled else []) + [confirmation(state)], None
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
    return [menu(state, label, [("重新输入账号", {"op": "cancel_bind"}),
                               ("核对无误，确认绑定", {"op": "bind"})],
                 "请核对登录号。确认后此微信将绑定该账号，后续不可更改。")]


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
