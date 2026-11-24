"""Normalized view models shared by the real SDK service and the in-memory mock."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InstanceInfo:
    instance_id: str
    name: str = ""
    status: str = ""
    region_id: str = ""
    instance_type: str = ""
    description: str = ""
    endpoints: str = ""
    create_time: str = ""
    topic_count: int | None = None
    group_count: int | None = None


@dataclass(slots=True)
class TopicInfo:
    name: str
    message_type: str = ""
    status: str = ""
    remark: str = ""
    create_time: str = ""
    update_time: str = ""
    max_send_tps: int | None = None


@dataclass(slots=True)
class GroupInfo:
    group_id: str
    status: str = ""
    message_model: str = ""
    retry_policy: str = ""
    max_retry_times: int | None = None
    fixed_interval_retry_time: int | None = None
    delivery_order_type: str = ""
    max_receive_tps: int | None = None
    exclusive: bool = False
    remark: str = ""
    create_time: str = ""
    update_time: str = ""


@dataclass(slots=True)
class SubscriptionInfo:
    topic_name: str
    filter_type: str = ""
    filter_expression: str = ""
    status: str = ""
    message_model: str = ""


@dataclass(slots=True)
class TopicLagInfo:
    topic_name: str
    ready_count: int = 0
    inflight_count: int = 0
    delivery_duration: int = 0
    last_consume_timestamp: int = 0

    @property
    def total(self) -> int:
        return self.ready_count + self.inflight_count


@dataclass(slots=True)
class LagInfo:
    group_id: str
    total_ready: int = 0
    total_inflight: int = 0
    delivery_duration: int = 0
    last_consume_timestamp: int = 0
    topics: list[TopicLagInfo] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.total_ready + self.total_inflight


@dataclass(slots=True)
class MessageInfo:
    msg_id: str
    topic_name: str = ""
    born_time: str = ""
    store_time: str = ""
    tag: str = ""
    keys: str = ""
    body: str = ""
    message_type: str = ""
    born_host: str = ""
    store_host: str = ""
    body_size: int = 0
    user_properties: dict[str, str] = field(default_factory=dict)
    system_properties: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Page:
    items: list[Any]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)
