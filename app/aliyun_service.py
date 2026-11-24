"""Thin, auditable wrapper around the Alibaba Cloud RocketMQ 2022-08-01 OpenAPI.

Management operations use RAM credentials (ECS instance role or environment
variables). Instance usernames/passwords used for producing and consuming
messages are never read, stored or displayed here.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_rocketmq20220801 import models as m
from alibabacloud_rocketmq20220801.client import Client as RocketMQClient
from alibabacloud_tea_openapi import models as om
from darabonba.exceptions import DaraException
from Tea.exceptions import TeaException

from .aliyun_types import (
    GroupInfo,
    InstanceInfo,
    LagInfo,
    MessageInfo,
    Page,
    SubscriptionInfo,
    TopicInfo,
    TopicLagInfo,
)
from .config import Settings, get_settings
from .service_errors import InstanceNotAllowed, ServiceError, ValidationError

logger = logging.getLogger(__name__)

SHANGHAI = timezone(timedelta(hours=8))
T = TypeVar("T")

MESSAGE_TYPES = {"NORMAL", "FIFO", "DELAY", "TRANSACTION"}
ORDER_TYPES = {"Concurrently", "Orderly"}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_%\-]{1,64}$")


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class _TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + ttl_seconds, value)

    def invalidate(self, prefix: str) -> None:
        with self._lock:
            for key in [key for key in self._data if key.startswith(prefix)]:
                self._data.pop(key, None)


# `TeaException` (from the Tea runtime) and `DaraException` are not related classes.
SDK_EXCEPTIONS = (TeaException, DaraException)


class RocketMQService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.allowed = list(self.settings.instance_ids)
        if not self.allowed:
            raise RuntimeError(
                "ALLOWED_INSTANCE_IDS 未配置：为防止面板操作整个账号的实例，必须显式指定实例白名单。"
            )

        common_config = {
            "endpoint": self.settings.rocketmq_endpoint,
            "connect_timeout": 5_000,
            "read_timeout": 20_000,
        }
        if (
            self.settings.alibaba_cloud_access_key_id
            and self.settings.alibaba_cloud_access_key_secret
        ):
            # pydantic-settings loads .env for us, but the Aliyun credential
            # provider only reads OS environment variables. Pass static keys
            # explicitly so local .env configuration actually works.
            config = om.Config(
                access_key_id=self.settings.alibaba_cloud_access_key_id,
                access_key_secret=self.settings.alibaba_cloud_access_key_secret,
                **common_config,
            )
            logger.info("RocketMQ OpenAPI 使用配置中的 AccessKey（仅建议本地调试）")
        else:
            credential = CredentialClient()
            config = om.Config(credential=credential, **common_config)
        self.client = RocketMQClient(config)
        self._cache = _TTLCache()

    # --------------------------------------------------------------- helpers

    def _ensure_allowed(self, instance_id: str) -> None:
        if not instance_id:
            raise ValidationError("缺少实例 ID")
        if instance_id not in self.allowed:
            raise InstanceNotAllowed(instance_id)

    def _call(self, action: str, func: Callable[[], T]) -> T:
        try:
            return func()
        except SDK_EXCEPTIONS as exc:
            code = getattr(exc, "code", None) or "OpenApiError"
            message = getattr(exc, "message", None) or str(exc)
            logger.warning("RocketMQ OpenAPI %s failed: code=%s message=%s", action, code, message)
            raise self._to_service_error(code, message) from exc
        except ServiceError:
            raise
        except Exception as exc:  # noqa: BLE001 - network/parse failures must not leak internals
            logger.exception("RocketMQ OpenAPI %s failed unexpectedly", action)
            raise ServiceError("调用阿里云 OpenAPI 失败，请稍后重试", code="OpenApiUnavailable") from exc

    @staticmethod
    def _to_service_error(code: str, message: str) -> ServiceError:
        throttled = "Throttl" in code
        forbidden = any(token in code for token in ("Forbidden", "NoPermission", "AccessDenied"))
        not_found = any(token in code for token in ("NotExist", "NotFound"))
        already_exists = "Exist" in code and not not_found
        if throttled:
            friendly = "阿里云接口触发限流，请稍后重试"
            status = 429
        elif forbidden:
            friendly = "面板使用的 RAM 角色缺少对应权限，请联系云账号管理员"
            status = 403
        elif not_found:
            friendly = message or "目标资源不存在"
            status = 404
        elif already_exists:
            friendly = message or "目标资源已存在"
            status = 409
        else:
            friendly = message or "阿里云接口调用失败"
            status = 502
        return ServiceError(friendly, code=code, status_code=status)

    def _data(self, response: Any, action: str) -> Any:
        body = getattr(response, "body", None)
        if body is None:
            raise ServiceError(f"{action} 返回为空", code="EmptyResponse")
        if getattr(body, "success", None) is False:
            code = getattr(body, "code", None) or "OpenApiError"
            message = (
                getattr(body, "message", None)
                or getattr(body, "dynamic_message", None)
                or f"{action} 失败"
            )
            raise ServiceError(message, code=code, status_code=400)
        return getattr(body, "data", None)

    @staticmethod
    def _normalize_page_size(page_size: int) -> int:
        """RocketMQ list APIs only accept 10..100; items outside get rejected."""
        try:
            value = int(page_size)
        except (TypeError, ValueError):
            value = 10
        return max(10, min(value, 100))

    @staticmethod
    def _api_time(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=SHANGHAI)
        return value.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")

    # ------------------------------------------------------------ view models

    @staticmethod
    def _map_instance(item: Any) -> InstanceInfo:
        instance_id = getattr(item, "instance_id", "") or ""
        return InstanceInfo(
            instance_id=instance_id,
            name=getattr(item, "instance_name", "") or instance_id,
            status=getattr(item, "status", "") or "",
            region_id=getattr(item, "region_id", "") or "",
            instance_type=getattr(item, "series_code", "") or getattr(item, "sub_series_code", "") or "",
            description=getattr(item, "remark", "") or "",
            create_time=getattr(item, "create_time", "") or "",
            topic_count=getattr(item, "topic_count", None),
            group_count=getattr(item, "group_count", None),
        )

    @staticmethod
    def _map_instance_detail(item: Any) -> InstanceInfo:
        instance_id = getattr(item, "instance_id", "") or ""
        endpoints = ""
        network = getattr(item, "network_info", None)
        if network is not None:
            parts = [
                f"{getattr(endpoint, 'endpoint_type', '') or 'endpoint'}: "
                f"{getattr(endpoint, 'endpoint_url', '') or ''}"
                for endpoint in (getattr(network, "endpoints", None) or [])
                if getattr(endpoint, "endpoint_url", None)
            ]
            endpoints = "；".join(parts)
        return InstanceInfo(
            instance_id=instance_id,
            name=getattr(item, "instance_name", "") or instance_id,
            status=getattr(item, "status", "") or "",
            region_id=getattr(item, "region_id", "") or "",
            instance_type=getattr(item, "series_code", "") or getattr(item, "sub_series_code", "") or "",
            description=getattr(item, "remark", "") or "",
            endpoints=endpoints,
            create_time=getattr(item, "create_time", "") or "",
            topic_count=getattr(item, "topic_count", None),
            group_count=getattr(item, "group_count", None),
        )

    @staticmethod
    def _map_topic(item: Any) -> TopicInfo:
        return TopicInfo(
            name=getattr(item, "topic_name", "") or "",
            message_type=getattr(item, "message_type", "") or "",
            status=getattr(item, "status", "") or "",
            remark=getattr(item, "remark", "") or "",
            create_time=getattr(item, "create_time", "") or "",
            update_time=getattr(item, "update_time", "") or "",
            max_send_tps=getattr(item, "max_send_tps", None),
        )

    @staticmethod
    def _map_group(item: Any) -> GroupInfo:
        policy = getattr(item, "consume_retry_policy", None)
        retry = ""
        if policy is not None:
            retry_policy = getattr(policy, "retry_policy", "") or ""
            max_retry = getattr(policy, "max_retry_times", None)
            if retry_policy == "FixedRetryPolicy":
                retry = (
                    f"固定间隔 {getattr(policy, 'fixed_interval_retry_time', '-') or '-'}s"
                    f" · 最多 {max_retry if max_retry is not None else '-'} 次"
                )
            else:
                retry = f"退避重试 · 最多 {max_retry if max_retry is not None else '-'} 次"
        return GroupInfo(
            group_id=getattr(item, "consumer_group_id", "") or "",
            status=getattr(item, "status", "") or "",
            message_model=getattr(item, "message_model", "") or "",
            retry_policy=retry,
            max_retry_times=(
                getattr(policy, "max_retry_times", None) if policy is not None else None
            ),
            fixed_interval_retry_time=(
                getattr(policy, "fixed_interval_retry_time", None) if policy is not None else None
            ),
            delivery_order_type=getattr(item, "delivery_order_type", "") or "",
            max_receive_tps=getattr(item, "max_receive_tps", None),
            exclusive=bool(getattr(item, "exclusive", False)),
            remark=getattr(item, "remark", "") or "",
            create_time=getattr(item, "create_time", "") or "",
            update_time=getattr(item, "update_time", "") or "",
        )

    @staticmethod
    def _map_message(item: Any, fallback_topic: str = "") -> MessageInfo:
        keys = getattr(item, "message_keys", None) or []
        return MessageInfo(
            msg_id=getattr(item, "message_id", "") or "",
            topic_name=getattr(item, "topic_name", "") or fallback_topic,
            born_time=getattr(item, "born_time", "") or "",
            store_time=getattr(item, "store_time", "") or "",
            tag=getattr(item, "message_tag", "") or "",
            keys=", ".join(str(key) for key in keys),
            body=getattr(item, "body", "") or "",
            message_type=getattr(item, "message_type", "") or "",
            born_host=getattr(item, "born_host", "") or "",
            store_host=getattr(item, "store_host", "") or "",
            body_size=_as_int(getattr(item, "body_size", 0)),
            user_properties=dict(getattr(item, "user_properties", None) or {}),
            system_properties=dict(getattr(item, "system_properties", None) or {}),
        )

    # ------------------------------------------------------------- instances

    def list_instances(self) -> list[InstanceInfo]:
        cached = self._cache.get("instances")
        if cached is not None:
            return cached

        found: dict[str, InstanceInfo] = {}
        page = 1
        while page <= 10 and len(found) < len(self.allowed):
            request = m.ListInstancesRequest(page_number=page, page_size=100)
            response = self._call("ListInstances", lambda: self.client.list_instances(request))
            data = self._data(response, "ListInstances")
            if data is None:
                break
            items = getattr(data, "list", None) or []
            for item in items:
                if getattr(item, "instance_id", None) in self.allowed:
                    info = self._map_instance(item)
                    found[info.instance_id] = info
            total = _as_int(getattr(data, "total_count", 0))
            if not items or page * 100 >= total:
                break
            page += 1

        result = [found[instance_id] for instance_id in self.allowed if instance_id in found]
        self._cache.set("instances", result, 60)
        return result

    def get_instance(self, instance_id: str) -> InstanceInfo:
        self._ensure_allowed(instance_id)
        cache_key = f"instance:{instance_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = self._call("GetInstance", lambda: self.client.get_instance(instance_id))
        data = self._data(response, "GetInstance")
        if data is None:
            raise ServiceError(f"实例 {instance_id} 不存在", code="InstanceNotFound", status_code=404)
        info = self._map_instance_detail(data)
        self._cache.set(cache_key, info, 60)
        return info

    # ---------------------------------------------------------------- topics

    def list_topics(
        self,
        instance_id: str,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
    ) -> Page:
        self._ensure_allowed(instance_id)
        page_size = self._normalize_page_size(page_size)
        cache_key = f"topics:{instance_id}:{page}:{page_size}:{keyword}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        request = m.ListTopicsRequest(
            page_number=page,
            page_size=page_size,
            filter=keyword or None,
        )
        response = self._call(
            "ListTopics", lambda: self.client.list_topics(instance_id, request)
        )
        data = self._data(response, "ListTopics")
        items = [self._map_topic(item) for item in (getattr(data, "list", None) or [])]
        total = _as_int(getattr(data, "total_count", 0)) or len(items)
        result = Page(items=items, total=total, page=page, page_size=page_size)
        self._cache.set(cache_key, result, 10)
        return result

    def get_topic(self, instance_id: str, topic_name: str) -> TopicInfo:
        self._ensure_allowed(instance_id)
        cache_key = f"topic:{instance_id}:{topic_name}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = self._call("GetTopic", lambda: self.client.get_topic(instance_id, topic_name))
        data = self._data(response, "GetTopic")
        if data is None:
            raise ServiceError(f"Topic {topic_name} 不存在", code="TopicNotFound", status_code=404)
        info = self._map_topic(data)
        self._cache.set(cache_key, info, 15)
        return info

    def create_topic(
        self,
        instance_id: str,
        *,
        name: str,
        message_type: str,
        remark: str = "",
        max_send_tps: int | None = None,
    ) -> None:
        self._ensure_allowed(instance_id)
        name = (name or "").strip()
        self._validate_name(name, "Topic")
        if message_type not in MESSAGE_TYPES:
            raise ValidationError("不支持的 Topic 消息类型")
        if max_send_tps is not None and max_send_tps <= 0:
            raise ValidationError("最大发送 TPS 必须大于 0")

        request = m.CreateTopicRequest(
            message_type=message_type,
            remark=remark or None,
            max_send_tps=max_send_tps,
        )
        self._call(
            "CreateTopic", lambda: self.client.create_topic(instance_id, name, request)
        )
        self._invalidate_topics(instance_id)

    def update_topic(
        self,
        instance_id: str,
        *,
        name: str,
        remark: str = "",
        max_send_tps: int | None = None,
    ) -> None:
        self._ensure_allowed(instance_id)
        self._validate_name(name, "Topic")
        if max_send_tps is not None and max_send_tps <= 0:
            raise ValidationError("最大发送 TPS 必须大于 0")

        request = m.UpdateTopicRequest(remark=remark or None, max_send_tps=max_send_tps)
        self._call(
            "UpdateTopic",
            lambda: self.client.update_topic(instance_id, name, request),
        )
        self._invalidate_topics(instance_id)

    def delete_topic(self, instance_id: str, topic_name: str) -> None:
        self._ensure_allowed(instance_id)
        self._call("DeleteTopic", lambda: self.client.delete_topic(instance_id, topic_name))
        self._invalidate_topics(instance_id)

    # ---------------------------------------------------------------- groups

    def list_groups(
        self,
        instance_id: str,
        page: int = 1,
        page_size: int = 50,
        keyword: str = "",
    ) -> Page:
        self._ensure_allowed(instance_id)
        page_size = self._normalize_page_size(page_size)
        cache_key = f"groups:{instance_id}:{page}:{page_size}:{keyword}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        request = m.ListConsumerGroupsRequest(
            page_number=page,
            page_size=page_size,
            filter=keyword or None,
        )
        response = self._call(
            "ListConsumerGroups",
            lambda: self.client.list_consumer_groups(instance_id, request),
        )
        data = self._data(response, "ListConsumerGroups")
        items = [self._map_group(item) for item in (getattr(data, "list", None) or [])]
        total = _as_int(getattr(data, "total_count", 0)) or len(items)
        result = Page(items=items, total=total, page=page, page_size=page_size)
        self._cache.set(cache_key, result, 10)
        return result

    def get_group(self, instance_id: str, group_id: str) -> GroupInfo:
        self._ensure_allowed(instance_id)
        cache_key = f"group:{instance_id}:{group_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        response = self._call(
            "GetConsumerGroup",
            lambda: self.client.get_consumer_group(instance_id, group_id),
        )
        data = self._data(response, "GetConsumerGroup")
        if data is None:
            raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
        info = self._map_group(data)
        self._cache.set(cache_key, info, 15)
        return info

    def create_group(
        self,
        instance_id: str,
        *,
        group_id: str,
        delivery_order_type: str = "Concurrently",
        max_retry_times: int = 16,
        fixed_interval_retry_time: int = 10,
        max_receive_tps: int | None = None,
        remark: str = "",
    ) -> None:
        self._ensure_allowed(instance_id)
        group_id = (group_id or "").strip()
        self._validate_name(group_id, "Group")
        self._validate_group_options(
            delivery_order_type, max_retry_times, fixed_interval_retry_time, max_receive_tps
        )

        policy = m.CreateConsumerGroupRequestConsumeRetryPolicy(
            retry_policy="FixedRetryPolicy"
            if delivery_order_type == "Orderly"
            else "DefaultRetryPolicy",
            max_retry_times=max_retry_times,
            fixed_interval_retry_time=fixed_interval_retry_time
            if delivery_order_type == "Orderly"
            else None,
        )
        request = m.CreateConsumerGroupRequest(
            consume_retry_policy=policy,
            delivery_order_type=delivery_order_type,
            max_receive_tps=max_receive_tps,
            remark=remark or None,
        )
        self._call(
            "CreateConsumerGroup",
            lambda: self.client.create_consumer_group(instance_id, group_id, request),
        )
        self._invalidate_groups(instance_id)

    def update_group(
        self,
        instance_id: str,
        *,
        group_id: str,
        delivery_order_type: str = "Concurrently",
        max_retry_times: int = 16,
        fixed_interval_retry_time: int = 10,
        max_receive_tps: int | None = None,
        remark: str = "",
    ) -> None:
        self._ensure_allowed(instance_id)
        self._validate_name(group_id, "Group")
        self._validate_group_options(
            delivery_order_type, max_retry_times, fixed_interval_retry_time, max_receive_tps
        )

        policy = m.UpdateConsumerGroupRequestConsumeRetryPolicy(
            retry_policy="FixedRetryPolicy"
            if delivery_order_type == "Orderly"
            else "DefaultRetryPolicy",
            max_retry_times=max_retry_times,
            fixed_interval_retry_time=fixed_interval_retry_time
            if delivery_order_type == "Orderly"
            else None,
        )
        request = m.UpdateConsumerGroupRequest(
            consume_retry_policy=policy,
            delivery_order_type=delivery_order_type,
            max_receive_tps=max_receive_tps,
            remark=remark or None,
        )
        self._call(
            "UpdateConsumerGroup",
            lambda: self.client.update_consumer_group(instance_id, group_id, request),
        )
        self._invalidate_groups(instance_id)

    def delete_group(self, instance_id: str, group_id: str) -> None:
        self._ensure_allowed(instance_id)
        self._call(
            "DeleteConsumerGroup",
            lambda: self.client.delete_consumer_group(instance_id, group_id),
        )
        self._invalidate_groups(instance_id)

    def list_subscriptions(self, instance_id: str, group_id: str) -> list[SubscriptionInfo]:
        self._ensure_allowed(instance_id)
        cache_key = f"subs:{instance_id}:{group_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        request = m.ListConsumerGroupSubscriptionsRequest()
        response = self._call(
            "ListConsumerGroupSubscriptions",
            lambda: self.client.list_consumer_group_subscriptions(instance_id, group_id, request),
        )
        data = self._data(response, "ListConsumerGroupSubscriptions")
        items = [
            SubscriptionInfo(
                topic_name=getattr(item, "topic_name", "") or "",
                filter_type=getattr(item, "filter_expression_type", "") or "",
                filter_expression=getattr(item, "filter_expression", "") or "",
                status=getattr(item, "subscription_status", "") or "",
                message_model=getattr(item, "message_model", "") or "",
            )
            for item in (data or [])
        ]
        self._cache.set(cache_key, items, 15)
        return items

    def get_group_lag(self, instance_id: str, group_id: str) -> LagInfo:
        self._ensure_allowed(instance_id)
        cache_key = f"lag:{instance_id}:{group_id}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        request = m.GetConsumerGroupLagRequest()
        response = self._call(
            "GetConsumerGroupLag",
            lambda: self.client.get_consumer_group_lag(instance_id, group_id, request),
        )
        data = self._data(response, "GetConsumerGroupLag")
        if data is None:
            result = LagInfo(group_id=group_id)
        else:
            topics = []
            for topic_name, value in (getattr(data, "topic_lag_map", None) or {}).items():
                topics.append(
                    TopicLagInfo(
                        topic_name=topic_name,
                        ready_count=_as_int(getattr(value, "ready_count", 0)),
                        inflight_count=_as_int(getattr(value, "inflight_count", 0)),
                        delivery_duration=_as_int(getattr(value, "delivery_duration", 0)),
                        last_consume_timestamp=_as_int(
                            getattr(value, "last_consume_timestamp", 0)
                        ),
                    )
                )
            topics.sort(key=lambda item: item.ready_count, reverse=True)

            total = getattr(data, "total_lag", None)
            total_ready = _as_int(getattr(total, "ready_count", 0)) if total else 0
            total_inflight = _as_int(getattr(total, "inflight_count", 0)) if total else 0
            delivery_duration = _as_int(getattr(total, "delivery_duration", 0)) if total else 0
            last_consume_timestamp = (
                _as_int(getattr(total, "last_consume_timestamp", 0)) if total else 0
            )
            if total is None:
                total_ready = sum(item.ready_count for item in topics)
                total_inflight = sum(item.inflight_count for item in topics)
            result = LagInfo(
                group_id=group_id,
                total_ready=total_ready,
                total_inflight=total_inflight,
                delivery_duration=delivery_duration,
                last_consume_timestamp=last_consume_timestamp,
                topics=topics,
            )
        self._cache.set(cache_key, result, 10)
        return result

    # -------------------------------------------------------------- messages

    def list_messages(
        self,
        instance_id: str,
        *,
        topic: str,
        start_time: datetime,
        end_time: datetime,
        msg_id: str = "",
        key: str = "",
        page: int = 1,
        page_size: int = 20,
    ) -> Page:
        self._ensure_allowed(instance_id)
        if not topic:
            raise ValidationError("请指定 Topic 名称")
        if end_time <= start_time:
            raise ValidationError("结束时间必须晚于开始时间")
        page_size = self._normalize_page_size(page_size)

        request = m.ListMessagesRequest(
            start_time=self._api_time(start_time),
            end_time=self._api_time(end_time),
            message_id=msg_id or None,
            message_key=key or None,
            page_number=page,
            page_size=page_size,
        )
        response = self._call(
            "ListMessages",
            lambda: self.client.list_messages(instance_id, topic, request),
        )
        data = self._data(response, "ListMessages")
        items = [
            self._map_message(item, fallback_topic=topic)
            for item in (getattr(data, "list", None) or [])
        ]
        total = _as_int(getattr(data, "total_count", 0)) or len(items)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get_message_detail(self, instance_id: str, topic: str, msg_id: str) -> MessageInfo:
        self._ensure_allowed(instance_id)
        response = self._call(
            "GetMessageDetail",
            lambda: self.client.get_message_detail(instance_id, topic, msg_id),
        )
        data = self._data(response, "GetMessageDetail")
        if data is None:
            raise ServiceError(f"消息 {msg_id} 不存在", code="MessageNotFound", status_code=404)
        return self._map_message(data, fallback_topic=topic)

    # ----------------------------------------------------------------- cache

    def _invalidate_topics(self, instance_id: str) -> None:
        self._cache.invalidate(f"topics:{instance_id}:")
        self._cache.invalidate(f"topic:{instance_id}:")
        self._cache.invalidate(f"lag:{instance_id}:")
        self._cache.invalidate(f"instance:{instance_id}")
        self._cache.invalidate("instances")

    def _invalidate_groups(self, instance_id: str) -> None:
        self._cache.invalidate(f"groups:{instance_id}:")
        self._cache.invalidate(f"group:{instance_id}:")
        self._cache.invalidate(f"subs:{instance_id}:")
        self._cache.invalidate(f"lag:{instance_id}:")
        self._cache.invalidate(f"instance:{instance_id}")
        self._cache.invalidate("instances")

    # ------------------------------------------------------------ validation

    @staticmethod
    def _validate_name(value: str, label: str) -> None:
        if not value:
            raise ValidationError(f"{label} 名称不能为空")
        if not NAME_PATTERN.match(value):
            raise ValidationError(f"{label} 名称只能包含字母、数字、-、_、%，且不超过 64 个字符")

    @staticmethod
    def _validate_group_options(
        delivery_order_type: str,
        max_retry_times: int,
        fixed_interval_retry_time: int,
        max_receive_tps: int | None,
    ) -> None:
        if delivery_order_type not in ORDER_TYPES:
            raise ValidationError("投递顺序只能是 Concurrently 或 Orderly")
        if not 0 <= max_retry_times <= 100:
            raise ValidationError("最大重试次数必须在 0 到 100 之间")
        if delivery_order_type == "Orderly" and not 1 <= fixed_interval_retry_time <= 600:
            raise ValidationError("顺序投递的固定重试间隔必须在 1 到 600 秒之间")
        if max_receive_tps is not None and max_receive_tps <= 0:
            raise ValidationError("最大接收 TPS 必须大于 0")
