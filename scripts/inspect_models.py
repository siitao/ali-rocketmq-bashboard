"""Print response model fields for the operations used by the console."""

from __future__ import annotations

import inspect

from alibabacloud_rocketmq20220801 import models as m

PREFIXES = (
    "ListInstancesResponse",
    "GetInstanceResponse",
    "ListTopicsResponse",
    "GetTopicResponse",
    "ListConsumerGroupsResponse",
    "GetConsumerGroupResponse",
    "ListConsumerGroupSubscriptionsResponse",
    "GetConsumerGroupLagResponse",
    "ListMessagesResponse",
    "GetMessageDetailResponse",
    "CreateConsumerGroupRequestConsumeRetryPolicy",
)


def main() -> None:
    names = [name for name in dir(m) if name.startswith(PREFIXES)]
    for name in sorted(names):
        cls = getattr(m, name)
        if not inspect.isclass(cls):
            continue
        try:
            signature = inspect.signature(cls.__init__)
        except (TypeError, ValueError):
            signature = "<unavailable>"
        print(f"{name}{signature}\n")


if __name__ == "__main__":
    main()
