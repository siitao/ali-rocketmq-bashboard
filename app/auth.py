from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from .db import get_db
from .errors import AppError, AuthRequired
from .models import User
from .rbac import can


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        user = db.get(User, int(user_id))
    except (TypeError, ValueError):
        request.session.clear()
        return None
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


def require_user(request: Request, user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        next_url = request.url.path
        if request.url.query:
            next_url += "?" + request.url.query
        raise AuthRequired(next_url)
    return user


def require_permission(permission: str):
    def dependency(user: User = Depends(require_user)) -> User:
        if not can(user.role, permission):
            raise AppError("没有权限执行该操作", status_code=403)
        return user

    return dependency
