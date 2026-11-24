from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..auth import require_permission, require_user
from ..db import get_db
from ..deps import get_service, resolve_instance_id
from ..models import User
from ..security import read_form_with_csrf
from ..service_errors import ServiceError
from ..web import client_ip, common_context, flash, instance_query, render

router = APIRouter(prefix="/topics", tags=["topics"])

PAGE_SIZE = 50
MESSAGE_TYPES = ["NORMAL", "FIFO", "DELAY", "TRANSACTION"]


def _nav(service, instance_id: str) -> dict:
    return common_context(service.list_instances(), instance_id, "topics")


def _form_values(form) -> dict:
    return {
        "name": (form.get("name") or "").strip(),
        "message_type": (form.get("message_type") or "NORMAL").strip(),
        "remark": (form.get("remark") or "").strip(),
        "max_send_tps": (form.get("max_send_tps") or "").strip(),
    }


@router.get("")
def topic_list(
    request: Request,
    instance: str | None = None,
    page: int = 1,
    q: str = "",
    user: User = Depends(require_user),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    page = max(1, page)
    result = service.list_topics(
        instance_id, page=page, page_size=PAGE_SIZE, keyword=q.strip()
    )
    return render(
        request,
        "topics/list.html",
        user=user,
        **_nav(service, instance_id),
        page_obj=result,
        topics=result.items,
        q=q,
        message_types=MESSAGE_TYPES,
    )


@router.get("/new")
def new_topic(
    request: Request,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:create")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    return render(
        request,
        "topics/form.html",
        user=user,
        **_nav(service, instance_id),
        mode="create",
        topic=None,
        form={"name": "", "message_type": "NORMAL", "remark": "", "max_send_tps": ""},
        error=None,
        message_types=MESSAGE_TYPES,
    )


@router.post("/new")
async def create_topic(
    request: Request,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:create")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    values = _form_values(form)

    error = None
    max_send_tps = None
    if values["max_send_tps"]:
        try:
            max_send_tps = int(values["max_send_tps"])
        except ValueError:
            error = "最大发送 TPS 必须是整数"

    params = {
        "message_type": values["message_type"],
        "remark": values["remark"],
        "max_send_tps": max_send_tps,
    }
    if error is None:
        try:
            service.create_topic(
                instance_id,
                name=values["name"],
                message_type=values["message_type"],
                remark=values["remark"],
                max_send_tps=max_send_tps,
            )
        except ServiceError as exc:
            error = exc.message
            write_audit(
                db,
                username=user.username,
                action="topic.create",
                instance_id=instance_id,
                target=values["name"],
                params=params,
                result="failure",
                error_code=exc.code,
                ip=client_ip(request),
            )
            return render(
                request,
                "topics/form.html",
                user=user,
                **_nav(service, instance_id),
                mode="create",
                topic=None,
                form=values,
                error=error,
                message_types=MESSAGE_TYPES,
                status_code=exc.status_code,
            )

    if error is not None:
        return render(
            request,
            "topics/form.html",
            user=user,
            **_nav(service, instance_id),
            mode="create",
            topic=None,
            form=values,
            error=error,
            message_types=MESSAGE_TYPES,
            status_code=400,
        )

    write_audit(
        db,
        username=user.username,
        action="topic.create",
        instance_id=instance_id,
        target=values["name"],
        params=params,
        ip=client_ip(request),
    )
    flash(request, f"Topic {values['name']} 创建成功")
    return RedirectResponse(
        f"/topics/{quote(values['name'], safe='')}{instance_query(instance_id)}",
        status_code=303,
    )


@router.get("/{topic_name}")
def topic_detail(
    request: Request,
    topic_name: str,
    instance: str | None = None,
    user: User = Depends(require_user),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    topic = service.get_topic(instance_id, topic_name)
    return render(
        request,
        "topics/detail.html",
        user=user,
        **_nav(service, instance_id),
        topic=topic,
        message_types=MESSAGE_TYPES,
    )


@router.get("/{topic_name}/edit")
def edit_topic(
    request: Request,
    topic_name: str,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:update")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    topic = service.get_topic(instance_id, topic_name)
    form = {
        "name": topic.name,
        "message_type": topic.message_type,
        "remark": topic.remark,
        "max_send_tps": topic.max_send_tps if topic.max_send_tps is not None else "",
    }
    return render(
        request,
        "topics/form.html",
        user=user,
        **_nav(service, instance_id),
        mode="edit",
        topic=topic,
        form=form,
        error=None,
        message_types=MESSAGE_TYPES,
    )


@router.post("/{topic_name}/edit")
async def update_topic(
    request: Request,
    topic_name: str,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:update")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    values = _form_values(form)
    values["name"] = topic_name

    error = None
    max_send_tps = None
    if values["max_send_tps"]:
        try:
            max_send_tps = int(values["max_send_tps"])
        except ValueError:
            error = "最大发送 TPS 必须是整数"

    topic = service.get_topic(instance_id, topic_name)
    params = {"remark": values["remark"], "max_send_tps": max_send_tps}
    if error is None:
        try:
            service.update_topic(
                instance_id,
                name=topic_name,
                remark=values["remark"],
                max_send_tps=max_send_tps,
            )
        except ServiceError as exc:
            error = exc.message
            write_audit(
                db,
                username=user.username,
                action="topic.update",
                instance_id=instance_id,
                target=topic_name,
                params=params,
                result="failure",
                error_code=exc.code,
                ip=client_ip(request),
            )
            return render(
                request,
                "topics/form.html",
                user=user,
                **_nav(service, instance_id),
                mode="edit",
                topic=topic,
                form=values,
                error=error,
                message_types=MESSAGE_TYPES,
                status_code=exc.status_code,
            )

    if error is not None:
        return render(
            request,
            "topics/form.html",
            user=user,
            **_nav(service, instance_id),
            mode="edit",
            topic=topic,
            form=values,
            error=error,
            message_types=MESSAGE_TYPES,
            status_code=400,
        )

    write_audit(
        db,
        username=user.username,
        action="topic.update",
        instance_id=instance_id,
        target=topic_name,
        params=params,
        ip=client_ip(request),
    )
    flash(request, f"Topic {topic_name} 已更新")
    return RedirectResponse(
        f"/topics/{quote(topic_name, safe='')}{instance_query(instance_id)}",
        status_code=303,
    )


@router.get("/{topic_name}/delete")
def delete_topic_page(
    request: Request,
    topic_name: str,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:delete")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    topic = service.get_topic(instance_id, topic_name)
    return render(
        request,
        "topics/delete.html",
        user=user,
        **_nav(service, instance_id),
        topic=topic,
        error=None,
    )


@router.post("/{topic_name}/delete")
async def delete_topic(
    request: Request,
    topic_name: str,
    instance: str | None = None,
    user: User = Depends(require_permission("topic:delete")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    confirm_name = (form.get("confirm_name") or "").strip()
    topic = service.get_topic(instance_id, topic_name)

    if confirm_name != topic_name:
        write_audit(
            db,
            username=user.username,
            action="topic.delete",
            instance_id=instance_id,
            target=topic_name,
            result="failure",
            error_code="ConfirmationMismatch",
            ip=client_ip(request),
        )
        return render(
            request,
            "topics/delete.html",
            user=user,
            **_nav(service, instance_id),
            topic=topic,
            error="输入的 Topic 名称不一致，未执行删除",
            status_code=400,
        )

    try:
        service.delete_topic(instance_id, topic_name)
    except ServiceError as exc:
        write_audit(
            db,
            username=user.username,
            action="topic.delete",
            instance_id=instance_id,
            target=topic_name,
            result="failure",
            error_code=exc.code,
            ip=client_ip(request),
        )
        return render(
            request,
            "topics/delete.html",
            user=user,
            **_nav(service, instance_id),
            topic=topic,
            error=exc.message,
            status_code=exc.status_code,
        )

    write_audit(
        db,
        username=user.username,
        action="topic.delete",
        instance_id=instance_id,
        target=topic_name,
        ip=client_ip(request),
    )
    flash(request, f"Topic {topic_name} 已删除", "warning")
    return RedirectResponse(f"/topics{instance_query(instance_id)}", status_code=303)
