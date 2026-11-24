from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..aliyun_types import Page
from ..audit import write_audit
from ..auth import require_permission
from ..db import get_db
from ..errors import AppError
from ..models import AuditLog, User
from ..rbac import ROLE_LABELS, ROLE_LEVELS
from ..security import MAX_PASSWORD_LENGTH, hash_password, read_form_with_csrf
from ..web import client_ip, flash, render

router = APIRouter(prefix="/admin", tags=["admin"])

AUDIT_PAGE_SIZE = 50


def _active_admins(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.is_active.is_(True))
        )
        or 0
    )


def _users_page(
    request: Request,
    db: Session,
    user: User,
    *,
    error: str | None = None,
    form: dict | None = None,
    status_code: int = 200,
):
    users = db.scalars(select(User).order_by(User.created_at, User.id)).all()
    return render(
        request,
        "admin/users.html",
        user=user,
        users=users,
        roles=sorted(ROLE_LEVELS),
        role_labels=ROLE_LABELS,
        active_admins=_active_admins(db),
        error=error,
        form=form or {"username": "", "role": "viewer"},
        status_code=status_code,
    )


@router.get("/users")
def users_page(
    request: Request,
    user: User = Depends(require_permission("user:manage")),
    db: Session = Depends(get_db),
):
    return _users_page(request, db, user)


@router.post("/users")
async def create_user(
    request: Request,
    user: User = Depends(require_permission("user:manage")),
    db: Session = Depends(get_db),
):
    form = await read_form_with_csrf(request)
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    role = (form.get("role") or "viewer").strip()
    values = {"username": username, "role": role}

    error = None
    if not username:
        error = "用户名不能为空"
    elif len(username) > 64:
        error = "用户名不能超过 64 个字符"
    elif role not in ROLE_LEVELS:
        error = "角色不合法"
    elif len(password) < 8:
        error = "密码至少 8 位"
    elif len(password) > MAX_PASSWORD_LENGTH:
        error = f"密码不能超过 {MAX_PASSWORD_LENGTH} 位"
    elif db.scalar(select(User).where(User.username == username)) is not None:
        error = f"用户 {username} 已存在"

    if error is not None:
        return _users_page(request, db, user, error=error, form=values, status_code=400)

    db.add(User(username=username, password_hash=hash_password(password), role=role))
    db.commit()
    write_audit(
        db,
        username=user.username,
        action="user.create",
        target=username,
        params={"role": role},
        ip=client_ip(request),
    )
    flash(request, f"用户 {username} 已创建（{ROLE_LABELS.get(role, role)}）")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/role")
async def change_role(
    request: Request,
    user_id: int,
    user: User = Depends(require_permission("user:manage")),
    db: Session = Depends(get_db),
):
    form = await read_form_with_csrf(request)
    role = (form.get("role") or "").strip()
    target = db.get(User, user_id)
    if target is None:
        raise AppError("用户不存在", status_code=404)

    error = None
    if role not in ROLE_LEVELS:
        error = "角色不合法"
    elif target.id == user.id and role != "admin":
        error = "不能修改自己的角色，请联系其他管理员"
    elif target.role == "admin" and role != "admin" and target.is_active and _active_admins(db) <= 1:
        error = "系统至少需要保留一个启用的管理员"

    if error is not None:
        return _users_page(request, db, user, error=error, status_code=400)

    previous = target.role
    target.role = role
    db.commit()
    write_audit(
        db,
        username=user.username,
        action="user.role",
        target=target.username,
        params={"from": previous, "to": role},
        ip=client_ip(request),
    )
    flash(request, f"{target.username} 的角色已改为 {ROLE_LABELS.get(role, role)}")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/active")
async def toggle_active(
    request: Request,
    user_id: int,
    user: User = Depends(require_permission("user:manage")),
    db: Session = Depends(get_db),
):
    form = await read_form_with_csrf(request)
    action = (form.get("action") or "").strip()
    target = db.get(User, user_id)
    if target is None:
        raise AppError("用户不存在", status_code=404)

    enable = action == "enable"
    error = None
    if action not in {"enable", "disable"}:
        error = "操作不合法"
    elif not enable and target.id == user.id:
        error = "不能停用自己的账号"
    elif (
        not enable
        and target.role == "admin"
        and target.is_active
        and _active_admins(db) <= 1
    ):
        error = "系统至少需要保留一个启用的管理员"

    if error is not None:
        return _users_page(request, db, user, error=error, status_code=400)

    target.is_active = enable
    db.commit()
    write_audit(
        db,
        username=user.username,
        action="user.enable" if enable else "user.disable",
        target=target.username,
        ip=client_ip(request),
    )
    flash(request, f"用户 {target.username} 已{'启用' if enable else '停用'}")
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/password")
async def reset_password(
    request: Request,
    user_id: int,
    user: User = Depends(require_permission("user:manage")),
    db: Session = Depends(get_db),
):
    form = await read_form_with_csrf(request)
    password = form.get("password") or ""
    target = db.get(User, user_id)
    if target is None:
        raise AppError("用户不存在", status_code=404)

    if len(password) < 8 or len(password) > MAX_PASSWORD_LENGTH:
        return _users_page(
            request,
            db,
            user,
            error=f"密码长度需为 8–{MAX_PASSWORD_LENGTH} 位",
            status_code=400,
        )

    target.password_hash = hash_password(password)
    db.commit()
    write_audit(
        db,
        username=user.username,
        action="user.password",
        target=target.username,
        ip=client_ip(request),
    )
    flash(request, f"已重置 {target.username} 的密码")
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/audit")
def audit_page(
    request: Request,
    username: str = "",
    action: str = "",
    result: str = "",
    page: int = 1,
    user: User = Depends(require_permission("audit:view")),
    db: Session = Depends(get_db),
):
    page = max(1, page)
    conditions = []
    username = username.strip()
    action = action.strip()
    result = result.strip()
    if username:
        conditions.append(AuditLog.username.contains(username))
    if action:
        conditions.append(AuditLog.action == action)
    if result:
        conditions.append(AuditLog.result == result)

    total = (
        db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    )
    entries = db.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * AUDIT_PAGE_SIZE)
        .limit(AUDIT_PAGE_SIZE)
    ).all()

    actions = db.scalars(
        select(AuditLog.action).distinct().order_by(AuditLog.action)
    ).all()

    return render(
        request,
        "admin/audit.html",
        user=user,
        page_obj=Page(entries, total, page, AUDIT_PAGE_SIZE),
        entries=entries,
        actions=actions,
        username=username,
        action=action,
        result=result,
    )
