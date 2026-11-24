"""In-memory RocketMQ service used for local development, demos and tests.

It mirrors the interface of app.aliyun_service.RocketMQService so routers never
need to know which implementation they are talking to.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from .aliyun_types import (
    ConsumeTimespanInfo,
    ConsumerConnectionInfo,
    ConsumerStackInfo,
    GroupInfo,
    InstanceEndpointInfo,
    InstanceInfo,
    InstanceQuotaInfo,
    LagInfo,
    MessageInfo,
    Page,
    SubscriptionInfo,
    TopicInfo,
    TopicLagInfo,
    TopicSubscriptionInfo,
    TraceConsumerInfo,
    TraceConsumerRecordInfo,
    TraceInfo,
    TraceOperationInfo,
    TraceProducerInfo,
)
from .service_errors import InstanceNotAllowed, ServiceError, ValidationError

SHANGHAI = timezone(timedelta(hours=8))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MockRocketMQService:
    def __init__(self, instance_ids: list[str], region: str = "cn-hangzhou") -> None:
        self._lock = threading.RLock()
        self._instance_ids = instance_ids or ["rmq-cn-mock-001"]
        self._region = region
        self._instances: dict[str, InstanceInfo] = {}
        self._topics: dict[str, dict[str, TopicInfo]] = {}
        self._groups: dict[str, dict[str, GroupInfo]] = {}
        self._subscriptions: dict[str, dict[str, list[SubscriptionInfo]]] = {}
        self._lag: dict[str, dict[str, dict[str, int]]] = {}
        self._connections: dict[str, dict[str, list[ConsumerConnectionInfo]]] = {}
        self._stacks: dict[str, dict[str, list[ConsumerStackInfo]]] = {}
        self._consume_timespans: dict[str, dict[str, dict[str, ConsumeTimespanInfo]]] = {}
        self._messages: list[MessageInfo] = []
        self._seed()

    @property
    def allowed(self) -> list[str]:
        return list(self._instance_ids)

    # ------------------------------------------------------------------ seed

    def _seed(self) -> None:
        now = _now()
        for index, instance_id in enumerate(self._instance_ids):
            self._instances[instance_id] = InstanceInfo(
                instance_id=instance_id,
                name=f"mock-rocketmq-{index + 1}",
                status="RUNNING",
                region_id=self._region,
                instance_type="standard",
                description="本地 Mock 实例（MOCK_ALIYUN=1）",
                endpoints=f"http://{instance_id}.mock.local:8080",
                create_time=_fmt(now - timedelta(days=90)),
                endpoint_list=[
                    InstanceEndpointInfo(
                        endpoint_type="TCP",
                        endpoint_url=f"{instance_id}.mock.local:8080",
                        ip_whitelist=["10.0.0.0/8"],
                    ),
                    InstanceEndpointInfo(
                        endpoint_type="HTTP",
                        endpoint_url=f"http://{instance_id}.mock.local:8080",
                        ip_whitelist=["10.0.0.0/8"],
                    ),
                ],
                acl_type="智能身份识别",
                acl_types=["INTELLIGENT"],
                default_vpc_auth_free=True,
                account_username="mock-user",
                retention_hours=72,
                trace_on=True,
                storage_encryption=False,
            )
            self._topics[instance_id] = {}
            self._groups[instance_id] = {}
            self._subscriptions[instance_id] = {}
            self._lag[instance_id] = {}
            self._connections[instance_id] = {}
            self._stacks[instance_id] = {}
            self._consume_timespans[instance_id] = {}

        instance_id = self._instance_ids[0]
        seed_topics = [
            ("order-events", "NORMAL", "订单事件"),
            ("payment-events", "NORMAL", "支付事件"),
            ("inventory-events", "FIFO", "库存事件（顺序）"),
            ("dlq-order-events", "NORMAL", "订单死信"),
        ]
        for offset, (name, message_type, remark) in enumerate(seed_topics):
            self._topics[instance_id][name] = TopicInfo(
                name=name,
                message_type=message_type,
                status="RUNNING",
                remark=remark,
                create_time=_fmt(now - timedelta(days=60 - offset)),
                update_time=_fmt(now - timedelta(days=2 + offset)),
            )

        seed_groups = [
            ("order-consumer", "订单消费组", "Concurrently", 12),
            ("payment-consumer", "支付消费组", "Concurrently", 0),
            ("inventory-consumer", "库存消费组", "Orderly", 340),
        ]
        for offset, (group_id, remark, order_type, _lag) in enumerate(seed_groups):
            retry_desc = (
                "固定间隔 10s · 最多 16 次"
                if order_type == "Orderly"
                else "退避重试 · 最多 16 次"
            )
            self._groups[instance_id][group_id] = GroupInfo(
                group_id=group_id,
                status="RUNNING",
                message_model="CLUSTERING",
                retry_policy=retry_desc,
                max_retry_times=16,
                fixed_interval_retry_time=10 if order_type == "Orderly" else None,
                delivery_order_type=order_type,
                remark=remark,
                create_time=_fmt(now - timedelta(days=50 - offset)),
                update_time=_fmt(now - timedelta(days=3 + offset)),
            )
            self._subscriptions[instance_id][group_id] = []
            self._lag[instance_id][group_id] = {}

        for group_id, topic_name, lag in [
            ("order-consumer", "order-events", 12),
            ("payment-consumer", "payment-events", 0),
            ("inventory-consumer", "inventory-events", 340),
        ]:
            self._subscriptions[instance_id][group_id].append(
                SubscriptionInfo(
                    topic_name=topic_name,
                    filter_type="TAG",
                    filter_expression="*",
                    status="ONLINE",
                    message_model="CLUSTERING",
                )
            )
            self._lag[instance_id][group_id][topic_name] = lag

        connection_seed = {
            "order-consumer": [
                ConsumerConnectionInfo(
                    client_id="order-consumer-1@mock",
                    egress_ip="10.0.0.11",
                    hostname="order-app-1",
                    language="JAVA",
                    version="5.0.8",
                    message_model="CLUSTERING",
                ),
                ConsumerConnectionInfo(
                    client_id="order-consumer-2@mock",
                    egress_ip="10.0.0.12",
                    hostname="order-app-2",
                    language="GO",
                    version="5.0.4",
                    message_model="CLUSTERING",
                ),
            ],
            "payment-consumer": [
                ConsumerConnectionInfo(
                    client_id="payment-consumer-1@mock",
                    egress_ip="10.0.0.21",
                    hostname="payment-app-1",
                    language="JAVA",
                    version="5.0.8",
                    message_model="CLUSTERING",
                )
            ],
            "inventory-consumer": [
                ConsumerConnectionInfo(
                    client_id="inventory-consumer-1@mock",
                    egress_ip="10.0.0.31",
                    hostname="inventory-app-1",
                    language="JAVA",
                    version="5.0.8",
                    message_model="CLUSTERING",
                )
            ],
        }
        for group_id, connections in connection_seed.items():
            self._connections[instance_id][group_id] = connections
            for connection in connections:
                self._stacks[instance_id][connection.client_id] = [
                    ConsumerStackInfo(
                        thread="ConsumeMessageThread_1",
                        tracks=[
                            "at com.example.mq.OrderListener.onMessage(OrderListener.java:42)",
                            "at org.apache.rocketmq.client.impl.consumer.ConsumeMessageConcurrentlyService$ConsumeRequest.run(ConsumeMessageConcurrentlyService.java:421)",
                        ],
                    ),
                    ConsumerStackInfo(
                        thread="ConsumeMessageThread_2",
                        tracks=[
                            "at java.lang.Object.wait(Native Method)",
                            "at org.apache.rocketmq.client.impl.consumer.ConsumeMessageConcurrentlyService$ConsumeRequest.run(ConsumeMessageConcurrentlyService.java:430)",
                        ],
                    ),
                ]

        base_ms = int(now.timestamp() * 1000)
        for group_id, subscriptions in self._subscriptions[instance_id].items():
            self._consume_timespans[instance_id][group_id] = {}
            for subscription in subscriptions:
                self._consume_timespans[instance_id][group_id][subscription.topic_name] = (
                    ConsumeTimespanInfo(
                        consumer_group_id=group_id,
                        topic_name=subscription.topic_name,
                        consume_timestamp=base_ms - 5 * 60 * 1000,
                        min_timestamp=base_ms - 2 * 3600 * 1000,
                        max_timestamp=base_ms - 60 * 1000,
                    )
                )

        payloads = [
            ("order-events", "OrderCreated", "order-1001", {"orderId": "1001", "amount": 128.0, "status": "CREATED"}),
            ("order-events", "OrderPaid", "order-1001", {"orderId": "1001", "amount": 128.0, "status": "PAID"}),
            ("order-events", "OrderCreated", "order-1002", {"orderId": "1002", "amount": 59.9, "status": "CREATED"}),
            ("order-events", "OrderCancelled", "order-1002", {"orderId": "1002", "amount": 59.9, "status": "CANCELLED"}),
            ("order-events", "OrderCreated", "order-1003", {"orderId": "1003", "amount": 899.0, "status": "CREATED"}),
            ("payment-events", "PaymentSucceeded", "order-1001", {"orderId": "1001", "channel": "alipay"}),
            ("payment-events", "PaymentFailed", "order-1002", {"orderId": "1002", "channel": "wechat", "reason": "balance"}),
            ("inventory-events", "StockLocked", "sku-2001", {"sku": "2001", "quantity": 2}),
        ]
        for index, (topic, tag, key, body) in enumerate(payloads):
            created = now - timedelta(minutes=index * 7 + 2)
            msg_id = f"7F00000100002A9F{index + 1:016X}"
            body_text = __import__("json").dumps(body, ensure_ascii=False)
            self._messages.append(
                MessageInfo(
                    msg_id=msg_id,
                    topic_name=topic,
                    born_time=_fmt(created),
                    store_time=_fmt(created),
                    tag=tag,
                    keys=key,
                    body=body_text,
                    message_type="FIFO" if topic == "inventory-events" else "NORMAL",
                    born_host="mock-broker-a",
                    store_host="mock-broker-b",
                    body_size=len(body_text.encode("utf-8")),
                    user_properties={
                        "KEYS": key,
                        "TAGS": tag,
                    },
                    system_properties={
                        "WAIT": "true",
                        "UNIQ_KEY": msg_id,
                        "CLUSTER": "mock-cluster",
                    },
                )
            )
        self._messages.sort(key=lambda item: item.store_time, reverse=True)
        instance = self._instances[instance_id]
        instance.topic_count = len(self._topics[instance_id])
        instance.group_count = len(self._groups[instance_id])
        instance.quotas = [
            InstanceQuotaInfo(
                quota_name="Topic 数量",
                total_count=50,
                used_count=instance.topic_count,
            ),
            InstanceQuotaInfo(
                quota_name="Group 数量",
                total_count=50,
                used_count=instance.group_count,
            ),
            InstanceQuotaInfo(quota_name="发送 TPS", total_count=5000, used_count=1200),
            InstanceQuotaInfo(quota_name="消费 TPS", total_count=5000, used_count=800),
        ]

    # ------------------------------------------------------------- internals

    def _ensure_allowed(self, instance_id: str) -> None:
        if instance_id not in self._instance_ids:
            raise InstanceNotAllowed(instance_id)

    def _topics_for(self, instance_id: str) -> dict[str, TopicInfo]:
        self._ensure_allowed(instance_id)
        return self._topics[instance_id]

    def _groups_for(self, instance_id: str) -> dict[str, GroupInfo]:
        self._ensure_allowed(instance_id)
        return self._groups[instance_id]

    @staticmethod
    def _paginate(items: list, page: int, page_size: int) -> Page:
        page = max(1, page)
        page_size = max(1, min(page_size, 200))
        start = (page - 1) * page_size
        return Page(items=items[start : start + page_size], total=len(items), page=page, page_size=page_size)

    # ------------------------------------------------------------- instances

    def list_instances(self) -> list[InstanceInfo]:
        with self._lock:
            return list(self._instances.values())

    def get_instance(self, instance_id: str) -> InstanceInfo:
        self._ensure_allowed(instance_id)
        with self._lock:
            instance = self._instances.get(instance_id)
        if instance is None:
            raise ServiceError(f"实例 {instance_id} 不存在", code="InstanceNotFound", status_code=404)
        return instance

    # ---------------------------------------------------------------- topics

    def list_topics(self, instance_id: str, page: int = 1, page_size: int = 50, keyword: str = "") -> Page:
        with self._lock:
            topics = list(self._topics_for(instance_id).values())
        if keyword:
            needle = keyword.lower()
            topics = [t for t in topics if needle in t.name.lower() or needle in (t.remark or "").lower()]
        topics.sort(key=lambda t: t.name)
        return self._paginate(topics, page, page_size)

    def get_topic(self, instance_id: str, topic_name: str) -> TopicInfo:
        with self._lock:
            topic = self._topics_for(instance_id).get(topic_name)
        if topic is None:
            raise ServiceError(f"Topic {topic_name} 不存在", code="TopicNotFound", status_code=404)
        return topic

    def create_topic(
        self,
        instance_id: str,
        *,
        name: str,
        message_type: str,
        remark: str = "",
        max_send_tps: int | None = None,
    ) -> None:
        name = name.strip()
        if not name:
            raise ValidationError("Topic 名称不能为空")
        if not name.replace("-", "").replace("_", "").replace("%", "").isalnum():
            raise ValidationError("Topic 名称只能包含字母、数字、-、_ 和 %")
        with self._lock:
            topics = self._topics_for(instance_id)
            if name in topics:
                raise ServiceError(f"Topic {name} 已存在", code="TopicAlreadyExist", status_code=409)
            topics[name] = TopicInfo(
                name=name,
                message_type=message_type,
                status="RUNNING",
                remark=remark,
                create_time=_fmt(_now()),
                update_time=_fmt(_now()),
                max_send_tps=max_send_tps,
            )
            self._instances[instance_id].topic_count = len(topics)

    def update_topic(
        self,
        instance_id: str,
        *,
        name: str,
        remark: str = "",
        max_send_tps: int | None = None,
    ) -> None:
        with self._lock:
            topics = self._topics_for(instance_id)
            topic = topics.get(name)
            if topic is None:
                raise ServiceError(f"Topic {name} 不存在", code="TopicNotFound", status_code=404)
            topic.remark = remark
            topic.max_send_tps = max_send_tps
            topic.update_time = _fmt(_now())

    def delete_topic(self, instance_id: str, topic_name: str) -> None:
        with self._lock:
            topics = self._topics_for(instance_id)
            if topic_name not in topics:
                raise ServiceError(f"Topic {topic_name} 不存在", code="TopicNotFound", status_code=404)
            del topics[topic_name]
            self._instances[instance_id].topic_count = len(topics)
            for group_id, subscriptions in self._subscriptions[instance_id].items():
                self._subscriptions[instance_id][group_id] = [
                    sub for sub in subscriptions if sub.topic_name != topic_name
                ]
                self._lag[instance_id].get(group_id, {}).pop(topic_name, None)

    # ---------------------------------------------------------------- groups

    def list_groups(self, instance_id: str, page: int = 1, page_size: int = 50, keyword: str = "") -> Page:
        with self._lock:
            groups = list(self._groups_for(instance_id).values())
        if keyword:
            needle = keyword.lower()
            groups = [g for g in groups if needle in g.group_id.lower() or needle in (g.remark or "").lower()]
        groups.sort(key=lambda g: g.group_id)
        return self._paginate(groups, page, page_size)

    def get_group(self, instance_id: str, group_id: str) -> GroupInfo:
        with self._lock:
            group = self._groups_for(instance_id).get(group_id)
        if group is None:
            raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
        return group

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
        group_id = group_id.strip()
        if not group_id:
            raise ValidationError("Group ID 不能为空")
        if not group_id.replace("-", "").replace("_", "").replace("%", "").isalnum():
            raise ValidationError("Group ID 只能包含字母、数字、-、_ 和 %")
        retry_desc = (
            f"固定间隔 {fixed_interval_retry_time}s · 最多 {max_retry_times} 次"
            if delivery_order_type == "Orderly"
            else f"退避重试 · 最多 {max_retry_times} 次"
        )
        with self._lock:
            groups = self._groups_for(instance_id)
            if group_id in groups:
                raise ServiceError(
                    f"Group {group_id} 已存在",
                    code="ConsumerGroupAlreadyExist",
                    status_code=409,
                )
            groups[group_id] = GroupInfo(
                group_id=group_id,
                status="RUNNING",
                message_model="CLUSTERING",
                retry_policy=retry_desc,
                max_retry_times=max_retry_times,
                fixed_interval_retry_time=fixed_interval_retry_time
                if delivery_order_type == "Orderly"
                else None,
                delivery_order_type=delivery_order_type,
                max_receive_tps=max_receive_tps,
                remark=remark,
                create_time=_fmt(_now()),
                update_time=_fmt(_now()),
            )
            self._instances[instance_id].group_count = len(groups)
            self._subscriptions[instance_id].setdefault(group_id, [])
            self._lag[instance_id].setdefault(group_id, {})

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
        retry_desc = (
            f"固定间隔 {fixed_interval_retry_time}s · 最多 {max_retry_times} 次"
            if delivery_order_type == "Orderly"
            else f"退避重试 · 最多 {max_retry_times} 次"
        )
        with self._lock:
            group = self._groups_for(instance_id).get(group_id)
            if group is None:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            group.delivery_order_type = delivery_order_type
            group.retry_policy = retry_desc
            group.max_retry_times = max_retry_times
            group.fixed_interval_retry_time = (
                fixed_interval_retry_time if delivery_order_type == "Orderly" else None
            )
            group.max_receive_tps = max_receive_tps
            group.remark = remark
            group.update_time = _fmt(_now())

    def delete_group(self, instance_id: str, group_id: str) -> None:
        with self._lock:
            groups = self._groups_for(instance_id)
            if group_id not in groups:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            del groups[group_id]
            self._instances[instance_id].group_count = len(groups)
            self._subscriptions[instance_id].pop(group_id, None)
            self._lag[instance_id].pop(group_id, None)

    def list_subscriptions(self, instance_id: str, group_id: str) -> list[SubscriptionInfo]:
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            return list(self._subscriptions[instance_id].get(group_id, []))

    def get_group_lag(self, instance_id: str, group_id: str) -> LagInfo:
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            lags = dict(self._lag[instance_id].get(group_id, {}))
        topics = [TopicLagInfo(topic_name=name, ready_count=value) for name, value in sorted(lags.items())]
        return LagInfo(
            group_id=group_id,
            total_ready=sum(item.ready_count for item in topics),
            total_inflight=0,
            topics=topics,
        )

    def list_consumer_connections(
        self, instance_id: str, group_id: str
    ) -> list[ConsumerConnectionInfo]:
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            return list(self._connections[instance_id].get(group_id, []))

    def get_consumer_stack(
        self, instance_id: str, group_id: str, client_id: str
    ) -> list[ConsumerStackInfo]:
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            connections = self._connections[instance_id].get(group_id, [])
            if client_id not in {connection.client_id for connection in connections}:
                raise ServiceError(
                    f"消费者 {client_id} 不在线", code="ConsumerNotFound", status_code=404
                )
            return list(self._stacks[instance_id].get(client_id, []))

    def list_topic_subscriptions(
        self, instance_id: str, topic_name: str
    ) -> list[TopicSubscriptionInfo]:
        with self._lock:
            topics = self._topics_for(instance_id)
            if topic_name not in topics:
                raise ServiceError(f"Topic {topic_name} 不存在", code="TopicNotFound", status_code=404)
            result = []
            for group_id, subscriptions in sorted(self._subscriptions[instance_id].items()):
                for subscription in subscriptions:
                    if subscription.topic_name != topic_name:
                        continue
                    result.append(
                        TopicSubscriptionInfo(
                            consumer_group_id=group_id,
                            topic_name=topic_name,
                            filter_type=subscription.filter_type,
                            filter_expression=subscription.filter_expression,
                            status=subscription.status,
                            message_model=subscription.message_model,
                            consistency="一致",
                        )
                    )
            return result

    def get_consume_timespan(
        self, instance_id: str, group_id: str, topic_name: str
    ) -> ConsumeTimespanInfo | None:
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            timespan = (
                self._consume_timespans[instance_id]
                .get(group_id, {})
                .get(topic_name)
            )
            return timespan

    def reset_consume_offset(
        self,
        instance_id: str,
        group_id: str,
        topic_name: str,
        *,
        reset_type: str,
        reset_time: datetime | None = None,
    ) -> None:
        if reset_type not in {"LATEST_OFFSET", "SPECIFIED_TIME"}:
            raise ValidationError("不支持的位点重置方式")
        if reset_type == "SPECIFIED_TIME" and reset_time is None:
            raise ValidationError("按指定时间回放时必须选择时间")
        with self._lock:
            self._groups_for(instance_id)
            if group_id not in self._groups[instance_id]:
                raise ServiceError(f"Group {group_id} 不存在", code="ConsumerGroupNotFound", status_code=404)
            subscribed = {
                subscription.topic_name
                for subscription in self._subscriptions[instance_id].get(group_id, [])
            }
            if topic_name not in subscribed:
                raise ValidationError("该 Group 未订阅指定 Topic")
            self._lag[instance_id].setdefault(group_id, {})[topic_name] = 0
            timespan = (
                self._consume_timespans[instance_id]
                .setdefault(group_id, {})
                .get(topic_name)
            )
            if timespan is not None:
                timespan.consume_timestamp = int(_now().timestamp() * 1000)

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
            raise ValidationError("请指定 Topic")
        if end_time <= start_time:
            raise ValidationError("结束时间必须晚于开始时间")

        start_local = start_time.astimezone(SHANGHAI)
        end_local = end_time.astimezone(SHANGHAI)
        matches: list[MessageInfo] = []
        with self._lock:
            for message in self._messages:
                if message.topic_name != topic:
                    continue
                stored = datetime.strptime(message.store_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SHANGHAI)
                if not (start_local <= stored <= end_local):
                    continue
                if msg_id and msg_id not in message.msg_id:
                    continue
                if key and key not in (message.keys or ""):
                    continue
                matches.append(message)
        matches.sort(key=lambda item: item.store_time, reverse=True)
        return self._paginate(matches, page, page_size)

    def get_message_detail(self, instance_id: str, topic: str, msg_id: str) -> MessageInfo:
        self._ensure_allowed(instance_id)
        with self._lock:
            for message in self._messages:
                if message.msg_id == msg_id and message.topic_name == topic:
                    return message
        raise ServiceError(f"消息 {msg_id} 不存在", code="MessageNotFound", status_code=404)

    def get_message_trace(
        self,
        instance_id: str,
        topic: str,
        msg_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> TraceInfo | None:
        self._ensure_allowed(instance_id)
        with self._lock:
            message = next(
                (
                    item
                    for item in self._messages
                    if item.msg_id == msg_id and item.topic_name == topic
                ),
                None,
            )
            if message is None:
                return None
            groups = [
                group_id
                for group_id, subscriptions in self._subscriptions[instance_id].items()
                if any(subscription.topic_name == topic for subscription in subscriptions)
            ]
            return TraceInfo(
                message_id=message.msg_id,
                topic_name=message.topic_name,
                tag=message.tag,
                keys=message.keys,
                message_type=message.message_type,
                born_time=message.born_time,
                store_time=message.store_time,
                born_host=message.born_host,
                store_host=message.store_host,
                producer_records=[
                    TraceProducerInfo(
                        arrive_time=message.store_time,
                        client_host="10.0.0.21",
                        produce_duration=8,
                        produce_status="SUCCESS",
                        produce_time=message.born_time,
                        user_name="mock-producer",
                        message_source="SDK",
                    )
                ],
                broker_operations=[
                    TraceOperationInfo(
                        operate_type="STORE",
                        operate_time=message.store_time,
                    )
                ],
                consumer_infos=[
                    TraceConsumerInfo(
                        consumer_group_id=group_id,
                        consume_status="SUCCESS",
                        records=[
                            TraceConsumerRecordInfo(
                                client_host="10.0.0.11",
                                consume_status="SUCCESS",
                                fifo_enable=message.message_type == "FIFO",
                                user_name="mock-consumer",
                                operations=[
                                    TraceOperationInfo(
                                        operate_type="CONSUME",
                                        operate_time=message.store_time,
                                    )
                                ],
                            )
                        ],
                    )
                    for group_id in groups
                ],
            )
