from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..aliyun_service import SHANGHAI
from ..audit import write_audit
from ..auth import require_permission, require_user
from ..config import get_settings
from ..db import get_db
from ..deps import get_service, resolve_instance_id
from ..errors import AppError
from ..models import User
from ..security import read_form_with_csrf
from ..service_errors import ServiceError
from ..web import client_ip, common_context, render

router = APIRouter(prefix="/messages", tags=["messages"])

PAGE_SIZE = 20
TIME_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


def _nav(service, instance_id: str) -> dict:
    return common_context(service.list_instances(), instance_id, "messages")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in (TIME_INPUT_FORMAT, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
    return None


@router.get("")
def message_query(
    request: Request,
    instance: str | None = None,
    topic: str = "",
    start: str = "",
    end: str = "",
    msg_id: str = "",
    key: str = "",
    page: int = 1,
    search: int = 0,
    user: User = Depends(require_permission("message:query")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    settings = get_settings()
    instance_id = resolve_instance_id(instance, service)
    now = datetime.now(SHANGHAI).replace(second=0, microsecond=0)
    default_end = now
    default_start = now - timedelta(minutes=settings.default_message_query_minutes)

    start_dt = _parse_dt(start) if start else default_start
    end_dt = _parse_dt(end) if end else default_end
    error = None

    if start and start_dt is None:
        error = "开始时间格式不正确"
    elif end and end_dt is None:
        error = "结束时间格式不正确"
    elif start_dt is not None and end_dt is not None:
        if end_dt <= start_dt:
            error = "结束时间必须晚于开始时间"
        elif end_dt - start_dt > timedelta(hours=settings.max_message_query_hours):
            error = f"查询时间范围不能超过 {settings.max_message_query_hours} 小时"

    page = max(1, page)
    topic = topic.strip()
    msg_id = msg_id.strip()
    key = key.strip()
    results = None

    if search and error is None:
        if not topic:
            error = "请输入 Topic 名称"
        elif start_dt is None or end_dt is None:
            error = "请选择查询时间范围"
        else:
            try:
                results = service.list_messages(
                    instance_id,
                    topic=topic,
                    start_time=start_dt,
                    end_time=end_dt,
                    msg_id=msg_id,
                    key=key,
                    page=page,
                    page_size=PAGE_SIZE,
                )
            except ServiceError as exc:
                error = exc.message
                write_audit(
                    db,
                    username=user.username,
                    action="message.query",
                    instance_id=instance_id,
                    target=topic,
                    params={
                        "topic": topic,
                        "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "msg_id": msg_id,
                        "key": key,
                        "page": page,
                    },
                    result="failure",
                    error_code=exc.code,
                    ip=client_ip(request),
                )
            else:
                write_audit(
                    db,
                    username=user.username,
                    action="message.query",
                    instance_id=instance_id,
                    target=topic,
                    params={
                        "topic": topic,
                        "start": start_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "end": end_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "msg_id": msg_id,
                        "key": key,
                        "page": page,
                    },
                    ip=client_ip(request),
                )

    topics = []
    try:
        topics = service.list_topics(instance_id, page=1, page_size=100).items
    except ServiceError:
        topics = []

    start_value = start or (start_dt.strftime(TIME_INPUT_FORMAT) if start_dt else "")
    end_value = end or (end_dt.strftime(TIME_INPUT_FORMAT) if end_dt else "")

    return render(
        request,
        "messages/query.html",
        user=user,
        **_nav(service, instance_id),
        topic=topic,
        msg_id=msg_id,
        key=key,
        start_value=start_value,
        end_value=end_value,
        search=search,
        page_obj=results,
        messages=results.items if results else [],
        topics=topics,
        error=error,
        max_hours=settings.max_message_query_hours,
    )


@router.get("/{msg_id}")
def message_detail(
    request: Request,
    msg_id: str,
    topic: str = "",
    instance: str | None = None,
    user: User = Depends(require_permission("message:query")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    topic = topic.strip()
    if not topic:
        raise AppError("缺少 Topic 参数，无法查看消息详情", status_code=400)

    try:
        message = service.get_message_detail(instance_id, topic, msg_id)
    except ServiceError as exc:
        write_audit(
            db,
            username=user.username,
            action="message.detail",
            instance_id=instance_id,
            target=msg_id,
            params={"topic": topic},
            result="failure",
            error_code=exc.code,
            ip=client_ip(request),
        )
        raise

    write_audit(
        db,
        username=user.username,
        action="message.detail",
        instance_id=instance_id,
        target=msg_id,
        params={"topic": topic},
        ip=client_ip(request),
    )
    return render(
        request,
        "messages/detail.html",
        user=user,
        **_nav(service, instance_id),
        message=message,
        topic=topic,
    )
