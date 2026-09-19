"""Administrator display and filter contract; contains no runtime or account data."""

from .service_catalog import registered_services


JOB_KINDS = {
    "verify": {"label": "账号验证"},
    "list": {"label": "任务列表"},
    "solve": {"label": "任务执行"},
    "purchase": {"label": "购买处理"},
    "payment_check": {"label": "支付确认"},
}
JOB_STATUSES = {
    "pending": {"label": "排队", "group": "active", "tone": "neutral"},
    "running": {"label": "运行中", "group": "active", "tone": "warn"},
    "complete": {"label": "已结束", "group": "ended", "tone": "neutral"},
    "failed": {"label": "失败", "group": "ended", "tone": "bad"},
    "cancelled": {"label": "已取消", "group": "ended", "tone": "neutral"},
    "interrupted": {"label": "中断", "group": "ended", "tone": "warn"},
}
# Legacy values remain readable without expanding the supported filter contract.
DISPLAY_JOB_STATUSES = {
    "queued": {"label": "排队", "group": "active", "tone": "neutral"},
}
REPLY_STATUSES = {
    "pending": {"label": "待发送"},
    "sent": {"label": "已发送"},
    "delivered": {"label": "已送达"},
    "retry": {"label": "待重试"},
    "failed": {"label": "失败"},
}


def admin_metadata():
    """Fresh JSON-compatible copies keep callers from mutating the registry."""
    return {
        "version": 1,
        "services": registered_services(),
        "job_kinds": [{"code": code, **value} for code, value in JOB_KINDS.items()],
        "job_statuses": [
            {"code": code, **value, "filterable": code in JOB_STATUSES}
            for code, value in (JOB_STATUSES | DISPLAY_JOB_STATUSES).items()
        ],
        "reply_statuses": [{"code": code, **value} for code, value in REPLY_STATUSES.items()],
    }
