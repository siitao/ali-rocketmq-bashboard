"""Inspect details that are easy to get wrong: lag shapes, time formats, client config."""

from __future__ import annotations

import inspect

from alibabacloud_credentials.client import Client as CredentialClient
from alibabacloud_rocketmq20220801 import models as m
from alibabacloud_rocketmq20220801.client import Client
from alibabacloud_tea_openapi import models as om


def show(cls, name: str) -> None:
    if cls is None:
        print(f"{name}: <MISSING>")
        return
    try:
        print(f"{name}: {inspect.signature(cls.__init__)}")
        doc = inspect.getdoc(cls)
        if doc:
            print(f"  doc: {doc[:500]}")
    except (TypeError, ValueError) as exc:
        print(f"{name}: <unavailable> {exc}")


def main() -> None:
    print("== constructors ==")
    show(Client, "RocketMQ Client")
    show(om.Config, "OpenAPI Config")
    show(CredentialClient, "Credential Client")

    print("\n== lag shapes ==")
    for name in [
        "DataTopicLagMapValue",
        "DataLiteTopicLagMapValue",
        "GetConsumerGroupLagResponseBodyDataTopicLagMapValue",
        "GetConsumerGroupLagResponseBodyDataLiteTopicLagMapValue",
    ]:
        show(getattr(m, name, None), name)

    print("\n== ListMessages docs ==")
    show(m.ListMessagesRequest, "ListMessagesRequest")
    print(inspect.getdoc(Client.list_messages) or "<no docstring>")

    print("\n== CreateTopic docs ==")
    show(m.CreateTopicRequest, "CreateTopicRequest")
    print(inspect.getdoc(Client.create_topic) or "<no docstring>")

    print("\n== GetConsumerGroupLag docs ==")
    show(m.GetConsumerGroupLagRequest, "GetConsumerGroupLagRequest")
    print(inspect.getdoc(Client.get_consumer_group_lag) or "<no docstring>")


if __name__ == "__main__":
    main()
