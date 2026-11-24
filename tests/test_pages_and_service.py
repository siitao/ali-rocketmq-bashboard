from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.aliyun_service import SHANGHAI
from conftest import audit_rows, get_csrf, login


def _message_window() -> dict[str, str]:
    now = datetime.now(SHANGHAI)
    return {
        "start": (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "end": (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
    }


def test_all_pages_render(client):
    login(client)
    paths = [
        "/",
        "/topics",
        "/topics/new",
        "/topics/order-events",
        "/topics/order-events/edit",
        "/topics/order-events/delete",
        "/groups",
        "/groups/new",
        "/groups/order-consumer",
        "/groups/order-consumer/edit",
        "/groups/order-consumer/delete",
        "/groups/order-consumer/reset-offset",
        "/groups/order-consumer/consumers/order-consumer-1@mock/stack",
        "/messages",
        "/messages/7F00000100002A9F0000000000000001/trace?topic=order-events&instance=rmq-cn-mock-001",
        "/admin/users",
        "/admin/audit",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}: {response.text[:500]}"


def test_static_assets_use_root_relative_urls(client):
    login(client, "viewer", "viewer1234")
    page = client.get("/")
    assert 'href="/static/app.css"' in page.text
    assert 'src="/static/app.js"' in page.text
    assert 'href="/static/favicon.svg"' in page.text
    assert "http://testserver/static" not in page.text


def test_message_query_and_detail_are_audited(client, db):
    login(client, "viewer", "viewer1234")
    window = _message_window()
    response = client.get(
        "/messages",
        params={
            "search": 1,
            "topic": "order-events",
            **window,
        },
    )
    assert response.status_code == 200
    assert "查询结果" in response.text

    match = re.search(r"7F[0-9A-F]{16,}", response.text)
    assert match is not None, response.text[:1000]
    msg_id = match.group(0)

    detail = client.get(f"/messages/{msg_id}", params={"topic": "order-events"})
    assert detail.status_code == 200
    assert "消息详情" in detail.text
    assert "消息体" in detail.text

    query_rows = audit_rows(db, "message.query")
    detail_rows = audit_rows(db, "message.detail")
    assert query_rows and query_rows[-1].username == "viewer"
    assert detail_rows and detail_rows[-1].result == "success"
    assert "orderId" not in (query_rows[-1].params_json or "")


def test_message_query_rejects_too_wide_range(client):
    login(client, "viewer", "viewer1234")
    now = datetime.now(SHANGHAI)
    response = client.get(
        "/messages",
        params={
            "search": 1,
            "topic": "order-events",
            "start": (now - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M"),
            "end": now.strftime("%Y-%m-%dT%H:%M"),
        },
    )
    assert response.status_code == 200
    assert "查询时间范围不能超过" in response.text


def test_group_detail_shows_lag_and_subscriptions(client):
    login(client, "viewer", "viewer1234")
    response = client.get("/groups/order-consumer")
    assert response.status_code == 200
    assert "消费堆积" in response.text
    assert "order-events" in response.text
    assert "待消费消息" in response.text
    assert "在线消费者" in response.text
    assert "order-consumer-1@mock" in response.text


def test_viewer_cannot_view_consumer_stack(client):
    login(client, "viewer", "viewer1234")
    response = client.get(
        "/groups/order-consumer/consumers/order-consumer-1@mock/stack"
    )
    assert response.status_code == 403


def test_operator_can_view_consumer_stack(client, db):
    from conftest import audit_rows

    login(client, "operator", "operator123")
    response = client.get(
        "/groups/order-consumer/consumers/order-consumer-1@mock/stack"
    )
    assert response.status_code == 200
    assert "ConsumeMessageThread_1" in response.text
    assert "消费线程栈" in response.text

    rows = audit_rows(db, "consumer.stack")
    assert any(row.target == "order-consumer-1@mock" and row.result == "success" for row in rows)


def test_topic_detail_shows_subscribed_groups(client):
    login(client, "viewer", "viewer1234")
    response = client.get("/topics/order-events")
    assert response.status_code == 200
    assert "订阅该 Topic 的 Group" in response.text
    assert "order-consumer" in response.text


def test_admin_topic_delete_page_shows_impacted_groups(client):
    login(client)
    delete_page = client.get("/topics/order-events/delete")
    assert delete_page.status_code == 200
    assert "正在订阅该 Topic" in delete_page.text
    assert "order-consumer" in delete_page.text


def test_message_trace_page_is_audited(client, db):
    from conftest import audit_rows

    login(client, "viewer", "viewer1234")
    window = _message_window()
    response = client.get(
        "/messages/7F00000100002A9F0000000000000001/trace",
        params={"topic": "order-events", "instance": "rmq-cn-mock-001", **window},
    )
    assert response.status_code == 200
    assert "消息轨迹" in response.text
    assert "生产者" in response.text
    assert "order-consumer" in response.text

    rows = audit_rows(db, "message.trace")
    assert rows and rows[-1].result == "success"


def test_operator_cannot_reset_consume_offset(client):
    login(client, "operator", "operator123")
    response = client.get("/groups/order-consumer/reset-offset")
    assert response.status_code == 403


def test_admin_reset_consume_offset_requires_confirmation_and_audits(client, db):
    from app.deps import get_service
    from conftest import audit_rows

    login(client)
    page = client.get("/groups/order-consumer/reset-offset")
    assert page.status_code == 200
    assert "重置消费位点" in page.text

    token = get_csrf(client, "/groups/order-consumer/reset-offset")
    wrong = client.post(
        "/groups/order-consumer/reset-offset",
        data={
            "csrf_token": token,
            "topic": "order-events",
            "reset_type": "LATEST_OFFSET",
            "confirm_name": "not-the-group",
        },
    )
    assert wrong.status_code == 400
    assert "Group ID 不一致" in wrong.text

    success = client.post(
        "/groups/order-consumer/reset-offset",
        data={
            "csrf_token": token,
            "topic": "order-events",
            "reset_type": "LATEST_OFFSET",
            "confirm_name": "order-consumer",
        },
        follow_redirects=False,
    )
    assert success.status_code == 303
    lag = get_service().get_group_lag("rmq-cn-mock-001", "order-consumer")
    assert lag.total_ready == 0

    rows = audit_rows(db, "group.reset_offset")
    assert any(row.result == "failure" for row in rows)
    assert any(row.result == "success" for row in rows)


def test_dashboard_shows_access_info_and_quotas(client):
    login(client, "viewer", "viewer1234")
    response = client.get("/")
    assert response.status_code == 200
    assert "接入点与访问控制" in response.text
    assert "实例配额" in response.text
    assert "认证模式" in response.text
    assert "TCP" in response.text
    assert "<progress" in response.text


def test_mock_new_features():
    from datetime import datetime, timedelta, timezone

    from app.mock_service import MockRocketMQService

    service = MockRocketMQService(["rmq-test"])

    connections = service.list_consumer_connections("rmq-test", "order-consumer")
    assert len(connections) == 2
    assert connections[0].client_id

    stacks = service.get_consumer_stack(
        "rmq-test", "order-consumer", connections[0].client_id
    )
    assert stacks and stacks[0].thread

    subscriptions = service.list_topic_subscriptions("rmq-test", "order-events")
    assert any(item.consumer_group_id == "order-consumer" for item in subscriptions)

    timespan = service.get_consume_timespan("rmq-test", "order-consumer", "order-events")
    assert timespan is not None and timespan.min_timestamp > 0

    now = datetime.now(timezone.utc)
    trace = service.get_message_trace(
        "rmq-test",
        "order-events",
        "7F00000100002A9F0000000000000001",
        now - timedelta(hours=2),
        now + timedelta(hours=1),
    )
    assert trace is not None
    assert trace.producer_records
    assert trace.consumer_infos

    service.reset_consume_offset(
        "rmq-test",
        "order-consumer",
        "order-events",
        reset_type="LATEST_OFFSET",
    )
    lag = service.get_group_lag("rmq-test", "order-consumer")
    assert lag.total_ready == 0


def test_operator_can_create_group(client, db):
    login(client, "operator", "operator123")
    token = get_csrf(client, "/groups/new")
    response = client.post(
        "/groups/new",
        data={
            "csrf_token": token,
            "group_id": "test-group",
            "delivery_order_type": "Orderly",
            "max_retry_times": "12",
            "fixed_interval_retry_time": "30",
            "max_receive_tps": "200",
            "remark": "created by test",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/groups/test-group" in response.headers["location"]

    detail = client.get("/groups/test-group")
    assert detail.status_code == 200
    assert "test-group" in detail.text

    rows = audit_rows(db, "group.create")
    assert any(row.target == "test-group" and row.result == "success" for row in rows)


def test_admin_user_management_and_self_protection(client, db):
    from app.models import User

    login(client)
    token = get_csrf(client, "/admin/users")
    created = client.post(
        "/admin/users",
        data={
            "csrf_token": token,
            "username": "newdev",
            "password": "newdev123",
            "role": "viewer",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    newdev = db.scalar(select(User).where(User.username == "newdev"))
    assert newdev is not None and newdev.role == "viewer"

    changed = client.post(
        f"/admin/users/{newdev.id}/role",
        data={"csrf_token": token, "role": "operator"},
        follow_redirects=False,
    )
    assert changed.status_code == 303
    db.expire_all()
    assert db.get(User, newdev.id).role == "operator"

    admin = db.scalar(select(User).where(User.username == "admin"))
    self_demote = client.post(
        f"/admin/users/{admin.id}/role",
        data={"csrf_token": token, "role": "viewer"},
    )
    assert self_demote.status_code == 400
    assert "不能修改自己的角色" in self_demote.text

    self_disable = client.post(
        f"/admin/users/{admin.id}/active",
        data={"csrf_token": token, "action": "disable"},
    )
    assert self_disable.status_code == 400
    assert "不能停用自己的账号" in self_disable.text

    rows = audit_rows(db, "user.create")
    assert any(row.target == "newdev" for row in rows)


def test_audit_action_labels(client):
    from app.web import action_label

    assert action_label("auth.login") == "登录"
    assert action_label("topic.create") == "创建 Topic"
    assert action_label("custom.action") == "custom.action"
    assert action_label(None) == "-"

    login(client)
    response = client.get("/admin/audit")
    assert response.status_code == 200
    assert ">登录<" in response.text
    assert 'title="auth.login"' in response.text


def test_audit_pagination_renders(client, db):
    from app.models import AuditLog

    login(client)
    for index in range(60):
        db.add(
            AuditLog(
                username="admin",
                action="test.action",
                target=f"target-{index}",
                result="success",
            )
        )
    db.commit()

    response = client.get("/admin/audit")
    assert response.status_code == 200
    assert "下一页" in response.text


def test_page_size_is_clamped_to_api_range():
    from app.aliyun_service import RocketMQService

    assert RocketMQService._normalize_page_size(1) == 10
    assert RocketMQService._normalize_page_size(5) == 10
    assert RocketMQService._normalize_page_size(20) == 20
    assert RocketMQService._normalize_page_size(1000) == 100
    assert RocketMQService._normalize_page_size("50") == 50


def test_mock_service_crud_and_lag():
    from app.mock_service import MockRocketMQService
    from app.service_errors import InstanceNotAllowed, ServiceError

    service = MockRocketMQService(["rmq-test"])
    instances = service.list_instances()
    assert instances[0].instance_id == "rmq-test"
    assert instances[0].topic_count == 4

    service.create_topic("rmq-test", name="extra-topic", message_type="NORMAL", max_send_tps=10)
    topic = service.get_topic("rmq-test", "extra-topic")
    assert topic.max_send_tps == 10
    service.update_topic("rmq-test", name="extra-topic", remark="updated", max_send_tps=20)
    assert service.get_topic("rmq-test", "extra-topic").remark == "updated"

    with pytest.raises(ServiceError):
        service.create_topic("rmq-test", name="extra-topic", message_type="NORMAL")

    service.delete_topic("rmq-test", "extra-topic")
    with pytest.raises(ServiceError):
        service.get_topic("rmq-test", "extra-topic")

    service.create_group("rmq-test", group_id="extra-group", delivery_order_type="Orderly")
    service.update_group("rmq-test", group_id="extra-group", max_receive_tps=50)
    assert service.get_group("rmq-test", "extra-group").max_receive_tps == 50
    service.delete_group("rmq-test", "extra-group")

    lag = service.get_group_lag("rmq-test", "order-consumer")
    assert lag.total_ready == 12
    assert lag.topics[0].topic_name == "order-events"

    now = datetime.now(SHANGHAI)
    messages = service.list_messages(
        "rmq-test",
        topic="order-events",
        start_time=now - timedelta(hours=2),
        end_time=now + timedelta(hours=1),
    )
    assert messages.total >= 5
    detail = service.get_message_detail(
        "rmq-test", "order-events", messages.items[0].msg_id
    )
    assert detail.body

    with pytest.raises(InstanceNotAllowed):
        service.get_topic("other-instance", "order-events")


def test_instance_selector_present_with_multiple_instances():
    from app.mock_service import MockRocketMQService

    service = MockRocketMQService(["rmq-a", "rmq-b"])
    assert len(service.list_instances()) == 2
