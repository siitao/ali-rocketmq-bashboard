from __future__ import annotations

ROLE_LEVELS = {"viewer": 1, "operator": 2, "admin": 3}
ROLE_LABELS = {"viewer": "只读", "operator": "运维", "admin": "管理员"}

PERMISSIONS = {
    "topic:create": "operator",
    "topic:update": "operator",
    "topic:delete": "admin",
    "group:create": "operator",
    "group:update": "operator",
    "group:delete": "admin",
    "message:query": "viewer",
    "message:trace": "viewer",
    "consumer:stack": "operator",
    "group:reset_offset": "admin",
    "user:manage": "admin",
    "audit:view": "admin",
}


def can(role: str | None, permission: str) -> bool:
    required = PERMISSIONS.get(permission, "admin")
    return ROLE_LEVELS.get(role or "", 0) >= ROLE_LEVELS[required]


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)
