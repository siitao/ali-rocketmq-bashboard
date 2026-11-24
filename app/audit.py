from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog

logger = logging.getLogger(__name__)


def write_audit(
    db: Session,
    *,
    username: str,
    action: str,
    instance_id: str | None = None,
    target: str | None = None,
    params: dict[str, Any] | None = None,
    result: str = "success",
    error_code: str | None = None,
    ip: str | None = None,
) -> None:
    payload = None
    if params:
        try:
            payload = json.dumps(params, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            payload = str(params)
        if len(payload) > 2000:
            payload = payload[:2000] + "...(truncated)"

    try:
        db.add(
            AuditLog(
                username=username,
                action=action,
                instance_id=instance_id,
                target=target,
                params_json=payload,
                result=result,
                error_code=error_code,
                ip=ip,
            )
        )
        db.commit()
    except Exception:  # noqa: BLE001 - auditing must never break the user flow
        db.rollback()
        logger.exception("failed to write audit log")
