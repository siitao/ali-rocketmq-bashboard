from __future__ import annotations

from functools import lru_cache

from .aliyun_service import RocketMQService
from .config import get_settings
from .errors import AppError
from .mock_service import MockRocketMQService


@lru_cache
def get_service():
    settings = get_settings()
    if settings.mock_aliyun:
        return MockRocketMQService(settings.instance_ids, settings.aliyun_region)
    return RocketMQService(settings)


def resolve_instance_id(requested: str | None, service) -> str:
    settings = get_settings()
    allowed = list(getattr(service, "allowed", None) or settings.instance_ids)
    if requested:
        if allowed and requested not in allowed:
            raise AppError("实例不在面板白名单内", status_code=403)
        return requested
    if allowed:
        return allowed[0]
    instances = service.list_instances()
    if instances:
        return instances[0].instance_id
    raise AppError(
        "没有可用的 RocketMQ 实例，请检查 ALLOWED_INSTANCE_IDS 配置",
        status_code=500,
    )
