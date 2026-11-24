"""Read-only smoke test against a real RocketMQ 5.0 instance.

Never creates, updates or deletes anything. Requires the instance ID to be
present in ALLOWED_INSTANCE_IDS.

Windows:
    set ALLOWED_INSTANCE_IDS=rmq-cn-xxxxxxxx
    set ALIYUN_REGION=cn-hangzhou
    set ALIBABA_CLOUD_ACCESS_KEY_ID=...
    set ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
    .venv\\Scripts\\python.exe scripts\\smoke_aliyun.py

Linux/macOS:
    ALLOWED_INSTANCE_IDS=rmq-cn-xxxxxxxx ALIYUN_REGION=cn-hangzhou \\
    ALIBABA_CLOUD_ACCESS_KEY_ID=... ALIBABA_CLOUD_ACCESS_KEY_SECRET=... \\
    .venv/bin/python scripts/smoke_aliyun.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.aliyun_service import RocketMQService  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.service_errors import ServiceError  # noqa: E402


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="RocketMQ Console 只读冒烟检查")
    parser.add_argument(
        "--instance-id",
        default=settings.instance_ids[0] if settings.instance_ids else "",
        help="要检查的实例 ID（必须在 ALLOWED_INSTANCE_IDS 中）",
    )
    parser.add_argument("--page-size", type=int, default=10)
    args = parser.parse_args()

    if not args.instance_id:
        print("请通过 ALLOWED_INSTANCE_IDS 或 --instance-id 指定实例", file=sys.stderr)
        return 2

    service = RocketMQService(settings)
    if args.instance_id not in service.allowed:
        print(
            f"实例 {args.instance_id} 不在 ALLOWED_INSTANCE_IDS 中，拒绝执行",
            file=sys.stderr,
        )
        return 2

    try:
        instances = service.list_instances()
        print(f"[ok] ListInstances: 白名单内找到 {len(instances)} 个实例")
        info = service.get_instance(args.instance_id)
        print(f"[ok] GetInstance: {info.instance_id} status={info.status} region={info.region_id}")

        topics = service.list_topics(args.instance_id, page=1, page_size=args.page_size)
        print(f"[ok] ListTopics: total={topics.total}")
        for topic in topics.items[:5]:
            print(f"     - {topic.name} ({topic.message_type}, {topic.status})")

        groups = service.list_groups(args.instance_id, page=1, page_size=args.page_size)
        print(f"[ok] ListConsumerGroups: total={groups.total}")
        for group in groups.items[:5]:
            print(f"     - {group.group_id} ({group.status})")

        if groups.items:
            group_id = groups.items[0].group_id
            subscriptions = service.list_subscriptions(args.instance_id, group_id)
            print(f"[ok] ListConsumerGroupSubscriptions({group_id}): {len(subscriptions)} 个订阅")
            lag = service.get_group_lag(args.instance_id, group_id)
            print(
                f"[ok] GetConsumerGroupLag({group_id}): ready={lag.total_ready} "
                f"inflight={lag.total_inflight} topics={len(lag.topics)}"
            )
    except ServiceError as exc:
        print(f"[failed] {exc.code}: {exc.message}", file=sys.stderr)
        return 1

    print("\n只读检查全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
