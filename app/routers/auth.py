from __future__ import annotations

import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import write_audit
from ..auth import get_current_user
from ..db import get_db
from ..models import User, utcnow
from ..security import (
    DUMMY_PASSWORD_HASH,
    MAX_PASSWORD_LENGTH,
    hash_password,
    login_limiter,
    password_needs_rehash,
    read_form_with_csrf,
    safe_next_url,
    verify_password,
)
from ..web import client_ip, render

router = APIRouter()


def _render_login(
    request: Request,
    db: Session,
    *,
    next_url: str,
    username: str = "",
    error: str | None = None,
    status_code: int = 200,
):
    has_users = bool(db.scalar(select(func.count()).select_from(User)))
    return render(
        request,
        "login.html",
        next_url=next_url,
        username=username,
        error=error,
        has_users=has_users,
        status_code=status_code,
    )


@router.get("/login")
def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return _render_login(request, db, next_url=safe_next_url(next))


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db)):
    form = await read_form_with_csrf(request)
    username = (form.get("username") or "").strip()[:64]
    password = form.get("password") or ""
    next_url = safe_next_url(form.get("next"))
    ip = client_ip(request)

    if login_limiter.is_limited(ip, username):
        write_audit(
            db,
            username=username or "-",
            action="auth.login",
            target=username or None,
            result="failure",
            error_code="RateLimited",
            ip=ip,
        )
        return _render_login(
            request,
            db,
            next_url=next_url,
            username=username,
            error="登录失败次数过多，请 15 分钟后再试",
            status_code=429,
        )

    user = db.scalar(select(User).where(User.username == username))
    password_ok = False
    if password and len(password) <= MAX_PASSWORD_LENGTH:
        password_ok = verify_password(
            password,
            user.password_hash if user is not None else DUMMY_PASSWORD_HASH,
        )
    if user is None or not user.is_active or not password_ok:
        login_limiter.record_failure(ip, username)
        write_audit(
            db,
            username=username or "-",
            action="auth.login",
            target=username or None,
            result="failure",
            error_code="InvalidCredentials",
            ip=ip,
        )
        return _render_login(
            request,
            db,
            next_url=next_url,
            username=username,
            error="用户名或密码错误",
            status_code=401,
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    db.commit()

    login_limiter.reset(ip, username)
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf"] = secrets.token_urlsafe(32)
    write_audit(
        db,
        username=user.username,
        action="auth.login",
        target=user.username,
        result="success",
        ip=ip,
    )
    return RedirectResponse(next_url, status_code=303)


@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    await read_form_with_csrf(request)
    user = get_current_user(request, db)
    if user is not None:
        write_audit(
            db,
            username=user.username,
            action="auth.logout",
            target=user.username,
            ip=client_ip(request),
        )
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
