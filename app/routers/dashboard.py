from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..auth import require_user
from ..config import get_settings
from ..deps import get_service, resolve_instance_id
from ..models import User
from ..service_errors import ServiceError
from ..web import common_context, render

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    instance: str | None = None,
    user: User = Depends(require_user),
    service=Depends(get_service),
):
    settings = get_settings()
    instances = service.list_instances()
    instance_id = resolve_instance_id(instance, service)
    info = next((item for item in instances if item.instance_id == instance_id), None)

    topics_total = None
    groups_total = None
    if info is not None:
        # Enrich with endpoints/quotas; fall back to ListInstances data if the
        # role only has list permission.
        try:
            info = service.get_instance(instance_id)
        except ServiceError:
            pass
        topics_total = info.topic_count
        groups_total = info.group_count
        if topics_total is None:
            topics_total = service.list_topics(instance_id, page=1, page_size=10).total
        if groups_total is None:
            groups_total = service.list_groups(instance_id, page=1, page_size=10).total

    found_ids = {item.instance_id for item in instances}
    missing = [item for item in settings.instance_ids if item not in found_ids]

    return render(
        request,
        "dashboard.html",
        user=user,
        **common_context(instances, instance_id, "dashboard"),
        info=info,
        topics_total=topics_total,
        groups_total=groups_total,
        missing=missing,
        mock=settings.mock_aliyun,
    )
