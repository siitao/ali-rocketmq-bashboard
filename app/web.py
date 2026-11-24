from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .rbac import can, role_label
from .security import get_csrf_token

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SHANGHAI = timezone(timedelta(hours=8))

templates.env.globals.update(
    can=can,
    role_label=role_label,
    csrf_token=get_csrf_token,
    app_name=get_settings().app_name,
)


def format_dt(value: datetime | None, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not value:
        return "-"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(SHANGHAI).strftime(fmt)


templates.env.filters["dt"] = format_dt


def status_class(value: str | None) -> str:
    normalized = (value or "").upper()
    if normalized in {
        "RUNNING",
        "ACTIVE",
        "NORMAL",
        "OK",
        "ENABLED",
        "SUCCESS",
        "ONLINE",
        "CONSISTENT",
    }:
        return "badge-success"
    if normalized in {
        "CREATING",
        "PENDING",
        "UPDATING",
        "CONFIGURING",
        "PARTIAL",
        "INCONSISTENT",
    }:
        return "badge-warning"
    if normalized in {
        "FAILED",
        "ERROR",
        "RELEASED",
        "DELETED",
        "DISABLED",
        "OFFLINE",
    }:
        return "badge-danger"
    return "badge-neutral"


MESSAGE_TYPE_LABELS = {
    "NORMAL": "普通",
    "FIFO": "顺序",
    "DELAY": "定时/延时",
    "TRANSACTION": "事务",
}


def message_type_label(value: str | None) -> str:
    if not value:
        return "-"
    return MESSAGE_TYPE_LABELS.get(value.upper(), value)


templates.env.filters["status_class"] = status_class
templates.env.filters["msg_type"] = message_type_label

ORDER_TYPE_LABELS = {"Concurrently": "并发", "Orderly": "顺序"}
MESSAGE_MODEL_LABELS = {"CLUSTERING": "集群消费", "LITE_SELECTIVE": "轻量订阅"}


def order_type_label(value: str | None) -> str:
    if not value:
        return "-"
    return ORDER_TYPE_LABELS.get(value, value)


def message_model_label(value: str | None) -> str:
    if not value:
        return "-"
    return MESSAGE_MODEL_LABELS.get(value, value)


def duration_label(value) -> str:
    if value is None or value == "":
        return "-"
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def number(value) -> str:
    if value is None or value == "":
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


ACTION_LABELS = {
    "auth.login": "登录",
    "auth.logout": "退出登录",
    "topic.create": "创建 Topic",
    "topic.update": "修改 Topic",
    "topic.delete": "删除 Topic",
    "group.create": "创建 Group",
    "group.update": "修改 Group",
    "group.delete": "删除 Group",
    "message.query": "查询消息",
    "message.detail": "查看消息详情",
    "message.trace": "查看消息轨迹",
    "consumer.stack": "查看消费线程栈",
    "group.reset_offset": "重置消费位点",
    "user.create": "创建用户",
    "user.role": "修改用户角色",
    "user.enable": "启用用户",
    "user.disable": "停用用户",
    "user.password": "重置用户密码",
}


def action_label(value: str | None) -> str:
    if not value:
        return "-"
    return ACTION_LABELS.get(value, value)


def epoch_ms(value) -> str:
    if value is None or value == "":
        return "-"
    try:
        milliseconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    if milliseconds <= 0:
        return "-"
    if milliseconds < 10_000_000_000:
        milliseconds *= 1000
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=SHANGHAI).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (OSError, OverflowError):
        return str(value)


def parse_local_datetime(value: str | None) -> datetime | None:
    """Parse datetime-local / API time strings as Beijing time."""
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
    return None


ACL_TYPE_LABELS = {
    "INTELLIGENT": "智能身份识别",
    "DEFAULT": "智能身份识别（默认）",
    "ACL": "ACL 身份识别",
    "NO_ACL": "未开启",
}


def acl_type_label(value: str | None) -> str:
    if not value:
        return "-"
    return ACL_TYPE_LABELS.get(value.upper(), value)


templates.env.filters["order_type"] = order_type_label
templates.env.filters["message_model"] = message_model_label
templates.env.filters["duration"] = duration_label
templates.env.filters["number"] = number
templates.env.filters["epoch_ms"] = epoch_ms
templates.env.filters["action_label"] = action_label
templates.env.filters["acl_type"] = acl_type_label


def instance_query(instance_id: str | None) -> str:
    return f"?instance={quote(instance_id, safe='')}" if instance_id else ""


def common_context(instances, instance_id: str | None, active_nav: str) -> dict:
    return {
        "instance_options": instances,
        "instance_id": instance_id,
        "active_nav": active_nav,
        "instance_qs": instance_query(instance_id),
    }


def client_ip(request: Request) -> str:
    # Never read X-Forwarded-For directly here: without a trusted proxy it is
    # attacker-controlled. Uvicorn's ProxyHeadersMiddleware resolves it using
    # --forwarded-allow-ips, so request.client.host is the address to audit.
    return ((request.client.host if request.client else "") or "")[:64]


def flash(request: Request, message: str, level: str = "success") -> None:
    request.session.setdefault("_flashes", []).append({"message": message, "level": level})


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("_flashes", [])


def render(
    request: Request,
    template: str,
    *,
    user=None,
    status_code: int = 200,
    **context,
):
    context.setdefault("request", request)
    context.setdefault("user", user)
    context.setdefault("flashes", pop_flashes(request))
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=context,
        status_code=status_code,
    )
