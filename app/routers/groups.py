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

router = APIRouter(prefix="/groups", tags=["groups"])

PAGE_SIZE = 50
ORDER_TYPES = ["Concurrently", "Orderly"]


def _nav(service, instance_id: str) -> dict:
    return common_context(service.list_instances(), instance_id, "groups")


def _form_values(form) -> dict:
    return {
        "group_id": (form.get("group_id") or "").strip(),
        "delivery_order_type": (form.get("delivery_order_type") or "Concurrently").strip(),
        "max_retry_times": (form.get("max_retry_times") or "16").strip(),
        "fixed_interval_retry_time": (form.get("fixed_interval_retry_time") or "10").strip(),
        "max_receive_tps": (form.get("max_receive_tps") or "").strip(),
        "remark": (form.get("remark") or "").strip(),
    }


def _parse_options(values: dict) -> tuple[dict | None, str | None]:
    parsed = dict(values)
    try:
        parsed["max_retry_times"] = int(values["max_retry_times"] or 16)
        parsed["fixed_interval_retry_time"] = int(values["fixed_interval_retry_time"] or 10)
        parsed["max_receive_tps"] = (
            int(values["max_receive_tps"]) if values["max_receive_tps"] else None
        )
    except ValueError:
        return None, "重试次数、重试间隔和最大接收 TPS 必须是整数"
    return parsed, None


@router.get("")
def group_list(
    request: Request,
    instance: str | None = None,
    page: int = 1,
    q: str = "",
    user: User = Depends(require_user),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    page = max(1, page)
    result = service.list_groups(
        instance_id, page=page, page_size=PAGE_SIZE, keyword=q.strip()
    )
    return render(
        request,
        "groups/list.html",
        user=user,
        **_nav(service, instance_id),
        page_obj=result,
        groups=result.items,
        q=q,
    )


@router.get("/new")
def new_group(
    request: Request,
    instance: str | None = None,
    user: User = Depends(require_permission("group:create")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    return render(
        request,
        "groups/form.html",
        user=user,
        **_nav(service, instance_id),
        mode="create",
        group=None,
        form={
            "group_id": "",
            "delivery_order_type": "Concurrently",
            "max_retry_times": "16",
            "fixed_interval_retry_time": "10",
            "max_receive_tps": "",
            "remark": "",
        },
        error=None,
        order_types=ORDER_TYPES,
    )


@router.post("/new")
async def create_group(
    request: Request,
    instance: str | None = None,
    user: User = Depends(require_permission("group:create")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    values = _form_values(form)
    parsed, error = _parse_options(values)
    if parsed is not None:
        values = parsed

    if error is None:
        try:
            service.create_group(
                instance_id,
                group_id=values["group_id"],
                delivery_order_type=values["delivery_order_type"],
                max_retry_times=values["max_retry_times"],
                fixed_interval_retry_time=values["fixed_interval_retry_time"],
                max_receive_tps=values["max_receive_tps"],
                remark=values["remark"],
            )
        except ServiceError as exc:
            write_audit(
                db,
                username=user.username,
                action="group.create",
                instance_id=instance_id,
                target=values["group_id"],
                params={
                    "delivery_order_type": values["delivery_order_type"],
                    "max_retry_times": values["max_retry_times"],
                    "max_receive_tps": values["max_receive_tps"],
                },
                result="failure",
                error_code=exc.code,
                ip=client_ip(request),
            )
            return render(
                request,
                "groups/form.html",
                user=user,
                **_nav(service, instance_id),
                mode="create",
                group=None,
                form=values,
                error=exc.message,
                order_types=ORDER_TYPES,
                status_code=exc.status_code,
            )

    if error is not None:
        return render(
            request,
            "groups/form.html",
            user=user,
            **_nav(service, instance_id),
            mode="create",
            group=None,
            form=values,
            error=error,
            order_types=ORDER_TYPES,
            status_code=400,
        )

    write_audit(
        db,
        username=user.username,
        action="group.create",
        instance_id=instance_id,
        target=values["group_id"],
        params={
            "delivery_order_type": values["delivery_order_type"],
            "max_retry_times": values["max_retry_times"],
            "max_receive_tps": values["max_receive_tps"],
        },
        ip=client_ip(request),
    )
    flash(request, f"Group {values['group_id']} 创建成功")
    return RedirectResponse(
        f"/groups/{quote(values['group_id'], safe='')}{instance_query(instance_id)}",
        status_code=303,
    )


@router.get("/{group_id}")
def group_detail(
    request: Request,
    group_id: str,
    instance: str | None = None,
    user: User = Depends(require_user),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    group = service.get_group(instance_id, group_id)

    subscriptions = []
    subs_error = None
    try:
        subscriptions = service.list_subscriptions(instance_id, group_id)
    except ServiceError as exc:
        subs_error = exc.message

    lag = None
    lag_error = None
    try:
        lag = service.get_group_lag(instance_id, group_id)
    except ServiceError as exc:
        lag_error = exc.message

    return render(
        request,
        "groups/detail.html",
        user=user,
        **_nav(service, instance_id),
        group=group,
        subscriptions=subscriptions,
        subs_error=subs_error,
        lag=lag,
        lag_error=lag_error,
    )


@router.get("/{group_id}/edit")
def edit_group(
    request: Request,
    group_id: str,
    instance: str | None = None,
    user: User = Depends(require_permission("group:update")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    group = service.get_group(instance_id, group_id)
    form = {
        "group_id": group.group_id,
        "delivery_order_type": group.delivery_order_type or "Concurrently",
        "max_retry_times": str(group.max_retry_times if group.max_retry_times is not None else 16),
        "fixed_interval_retry_time": str(
            group.fixed_interval_retry_time
            if group.fixed_interval_retry_time is not None
            else 10
        ),
        "max_receive_tps": (
            str(group.max_receive_tps) if group.max_receive_tps is not None else ""
        ),
        "remark": group.remark,
    }
    return render(
        request,
        "groups/form.html",
        user=user,
        **_nav(service, instance_id),
        mode="edit",
        group=group,
        form=form,
        error=None,
        order_types=ORDER_TYPES,
    )


@router.post("/{group_id}/edit")
async def update_group(
    request: Request,
    group_id: str,
    instance: str | None = None,
    user: User = Depends(require_permission("group:update")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    values = _form_values(form)
    values["group_id"] = group_id
    parsed, error = _parse_options(values)
    if parsed is not None:
        values = parsed

    group = service.get_group(instance_id, group_id)
    params = {
        "delivery_order_type": values["delivery_order_type"],
        "max_retry_times": values["max_retry_times"],
        "max_receive_tps": values["max_receive_tps"],
    }
    if error is None:
        try:
            service.update_group(
                instance_id,
                group_id=group_id,
                delivery_order_type=values["delivery_order_type"],
                max_retry_times=values["max_retry_times"],
                fixed_interval_retry_time=values["fixed_interval_retry_time"],
                max_receive_tps=values["max_receive_tps"],
                remark=values["remark"],
            )
        except ServiceError as exc:
            write_audit(
                db,
                username=user.username,
                action="group.update",
                instance_id=instance_id,
                target=group_id,
                params=params,
                result="failure",
                error_code=exc.code,
                ip=client_ip(request),
            )
            return render(
                request,
                "groups/form.html",
                user=user,
                **_nav(service, instance_id),
                mode="edit",
                group=group,
                form=values,
                error=exc.message,
                order_types=ORDER_TYPES,
                status_code=exc.status_code,
            )

    if error is not None:
        return render(
            request,
            "groups/form.html",
            user=user,
            **_nav(service, instance_id),
            mode="edit",
            group=group,
            form=values,
            error=error,
            order_types=ORDER_TYPES,
            status_code=400,
        )

    write_audit(
        db,
        username=user.username,
        action="group.update",
        instance_id=instance_id,
        target=group_id,
        params=params,
        ip=client_ip(request),
    )
    flash(request, f"Group {group_id} 已更新")
    return RedirectResponse(
        f"/groups/{quote(group_id, safe='')}{instance_query(instance_id)}",
        status_code=303,
    )


@router.get("/{group_id}/delete")
def delete_group_page(
    request: Request,
    group_id: str,
    instance: str | None = None,
    user: User = Depends(require_permission("group:delete")),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    group = service.get_group(instance_id, group_id)
    return render(
        request,
        "groups/delete.html",
        user=user,
        **_nav(service, instance_id),
        group=group,
        error=None,
    )


@router.post("/{group_id}/delete")
async def delete_group(
    request: Request,
    group_id: str,
    instance: str | None = None,
    user: User = Depends(require_permission("group:delete")),
    db: Session = Depends(get_db),
    service=Depends(get_service),
):
    instance_id = resolve_instance_id(instance, service)
    form = await read_form_with_csrf(request)
    confirm_name = (form.get("confirm_name") or "").strip()
    group = service.get_group(instance_id, group_id)

    if confirm_name != group_id:
        write_audit(
            db,
            username=user.username,
            action="group.delete",
            instance_id=instance_id,
            target=group_id,
            result="failure",
            error_code="ConfirmationMismatch",
            ip=client_ip(request),
        )
        return render(
            request,
            "groups/delete.html",
            user=user,
            **_nav(service, instance_id),
            group=group,
            error="输入的 Group ID 不一致，未执行删除",
            status_code=400,
        )

    try:
        service.delete_group(instance_id, group_id)
    except ServiceError as exc:
        write_audit(
            db,
            username=user.username,
            action="group.delete",
            instance_id=instance_id,
            target=group_id,
            result="failure",
            error_code=exc.code,
            ip=client_ip(request),
        )
        return render(
            request,
            "groups/delete.html",
            user=user,
            **_nav(service, instance_id),
            group=group,
            error=exc.message,
            status_code=exc.status_code,
        )

    write_audit(
        db,
        username=user.username,
        action="group.delete",
        instance_id=instance_id,
        target=group_id,
        ip=client_ip(request),
    )
    flash(request, f"Group {group_id} 已删除", "warning")
    return RedirectResponse(f"/groups{instance_query(instance_id)}", status_code=303)
