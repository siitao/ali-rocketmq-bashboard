"""Normalized view models shared by the real SDK service and the in-memory mock."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class InstanceEndpointInfo:
    endpoint_type: str = ""
    endpoint_url: str = ""
    ip_whitelist: list[str] = field(default_factory=list)


@dataclass(slots=True)
class InstanceQuotaInfo:
    quota_name: str = ""
    free_count: float | None = None
    total_count: float | None = None
    used_count: float | None = None


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
    endpoint_list: list[InstanceEndpointInfo] = field(default_factory=list)
    acl_type: str = ""
    acl_types: list[str] = field(default_factory=list)
    default_vpc_auth_free: bool | None = None
    account_username: str = ""
    quotas: list[InstanceQuotaInfo] = field(default_factory=list)
    retention_hours: int | None = None
    trace_on: bool | None = None
    storage_encryption: bool | None = None


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
class ConsumerConnectionInfo:
    client_id: str
    egress_ip: str = ""
    hostname: str = ""
    language: str = ""
    version: str = ""
    message_model: str = ""


@dataclass(slots=True)
class ConsumerStackInfo:
    thread: str = ""
    tracks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TopicSubscriptionInfo:
    consumer_group_id: str
    topic_name: str = ""
    filter_type: str = ""
    filter_expression: str = ""
    status: str = ""
    message_model: str = ""
    consistency: str = ""


@dataclass(slots=True)
class ConsumeTimespanInfo:
    consumer_group_id: str = ""
    topic_name: str = ""
    consume_timestamp: int = 0
    min_timestamp: int = 0
    max_timestamp: int = 0


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
class TraceOperationInfo:
    operate_type: str = ""
    operate_time: str = ""
    dead_message: bool = False
    invisible_time: int | None = None


@dataclass(slots=True)
class TraceProducerInfo:
    arrive_time: str = ""
    client_host: str = ""
    produce_duration: int | None = None
    produce_status: str = ""
    produce_time: str = ""
    recall_time: str = ""
    user_name: str = ""
    message_source: str = ""
    dlq_origin_message_id: str = ""
    dlq_origin_topic: str = ""


@dataclass(slots=True)
class TraceConsumerRecordInfo:
    client_host: str = ""
    consume_status: str = ""
    fifo_enable: bool = False
    pop_ck: str = ""
    user_name: str = ""
    operations: list[TraceOperationInfo] = field(default_factory=list)


@dataclass(slots=True)
class TraceConsumerInfo:
    consumer_group_id: str = ""
    consume_status: str = ""
    dead_message: bool = False
    dead_letter_topic: str = ""
    dead_letter_message_id: str = ""
    dlq_time: str = ""
    records: list[TraceConsumerRecordInfo] = field(default_factory=list)


@dataclass(slots=True)
class TraceInfo:
    message_id: str = ""
    topic_name: str = ""
    tag: str = ""
    keys: str = ""
    message_type: str = ""
    born_time: str = ""
    store_time: str = ""
    born_host: str = ""
    store_host: str = ""
    transaction_id: str = ""
    producer_records: list[TraceProducerInfo] = field(default_factory=list)
    broker_delay_status: str = ""
    broker_preset_delay_time: str = ""
    broker_recall_result: str = ""
    broker_operations: list[TraceOperationInfo] = field(default_factory=list)
    consumer_infos: list[TraceConsumerInfo] = field(default_factory=list)


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
