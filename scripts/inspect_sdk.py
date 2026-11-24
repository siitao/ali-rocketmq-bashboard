"""Print the installed RocketMQ SDK surface so request/response field names stay honest.

Maintainer helper: run after `pip install -r requirements.txt` when upgrading the SDK.

    .venv\\Scripts\\python.exe scripts\\inspect_sdk.py
"""

from __future__ import annotations

import inspect

from alibabacloud_rocketmq20220801 import models
from alibabacloud_rocketmq20220801.client import Client

METHODS = [
    "list_instances",
    "get_instance",
    "list_topics",
    "get_topic",
    "create_topic",
    "update_topic",
    "delete_topic",
    "list_consumer_groups",
    "get_consumer_group",
    "create_consumer_group",
    "update_consumer_group",
    "delete_consumer_group",
    "list_consumer_group_subscriptions",
    "get_consumer_group_lag",
    "list_messages",
    "get_message_detail",
]

MODELS = [
    "ListInstancesRequest",
    "GetInstanceRequest",
    "ListTopicsRequest",
    "GetTopicRequest",
    "CreateTopicRequest",
    "UpdateTopicRequest",
    "DeleteTopicRequest",
    "ListConsumerGroupsRequest",
    "GetConsumerGroupRequest",
    "CreateConsumerGroupRequest",
    "UpdateConsumerGroupRequest",
    "DeleteConsumerGroupRequest",
    "ListConsumerGroupSubscriptionsRequest",
    "GetConsumerGroupLagRequest",
    "ListMessagesRequest",
    "GetMessageDetailRequest",
]


def main() -> None:
    print("== Client methods ==")
    for name in METHODS:
        fn = getattr(Client, name, None)
        print(f"{name}{inspect.signature(fn) if fn else '  <MISSING>'}")
    print("\n== All public client methods ==")
    print(", ".join(sorted(n for n in dir(Client) if not n.startswith("_"))))

    print("\n== Request models ==")
    for name in MODELS:
        cls = getattr(models, name, None)
        if cls is None:
            print(f"\n{name}: <MISSING>")
            continue
        print(f"\n{name}")
        try:
            print("  annotations:", getattr(cls, "__annotations__", {}))
            print("  signature:", inspect.signature(cls.__init__))
        except (TypeError, ValueError) as exc:
            print("  <could not inspect>", exc)


if __name__ == "__main__":
    main()
