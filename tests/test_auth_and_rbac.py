from __future__ import annotations

import pytest

from conftest import get_csrf, login


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["mock"] is True


def test_login_required_redirects(client):
    response = client.get("/topics", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_login_and_dashboard(client):
    page = client.get("/login")
    assert page.status_code == 200
    assert "登录" in page.text

    login(client, "viewer", "viewer1234")
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "实例概览" in dashboard.text
    assert "rmq-cn-mock-001" in dashboard.text


def test_invalid_login_and_rate_limit(client):
    token = get_csrf(client, "/login")
    for attempt in range(5):
        response = client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "nobody",
                "password": "wrong-password",
                "next": "/",
            },
        )
        assert response.status_code == 401

    limited = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "nobody",
            "password": "wrong-password",
            "next": "/",
        },
    )
    assert limited.status_code == 429
    assert "次数过多" in limited.text


def test_rate_limit_applies_across_usernames_from_one_ip(client):
    token = get_csrf(client, "/login")
    for index in range(20):
        response = client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": f"nobody-{index}",
                "password": "wrong-password",
                "next": "/",
            },
        )
        assert response.status_code == 401

    limited = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "yet-another-name",
            "password": "wrong-password",
            "next": "/",
        },
    )
    assert limited.status_code == 429


@pytest.mark.parametrize(
    "value",
    [
        "//evil.example",
        "/\\evil.example",
        "https://evil.example",
        "javascript:alert(1)",
        " /topics",
    ],
)
def test_safe_next_url_blocks_external_targets(value):
    from app.security import safe_next_url

    assert safe_next_url(value) == "/"


def test_safe_next_url_keeps_local_paths():
    from app.security import safe_next_url

    assert safe_next_url("/topics?instance=rmq-cn-mock-001") == "/topics?instance=rmq-cn-mock-001"
    assert safe_next_url("/") == "/"
    assert safe_next_url(None) == "/"


def test_login_rejects_open_redirect(client):
    page = client.get("/login", params={"next": "//evil.example"})
    assert 'name="next" value="/"' in page.text

    token = get_csrf(client, "/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": "admin",
            "password": "admin12345",
            "next": "/\\evil.example",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_admin_rejects_overlong_password(client):
    login(client)
    token = get_csrf(client, "/admin/users")
    response = client.post(
        "/admin/users",
        data={
            "csrf_token": token,
            "username": "longpass",
            "password": "a" * 129,
            "role": "viewer",
        },
    )
    assert response.status_code == 400
    assert "128" in response.text


def test_csrf_is_required(client):
    login(client)
    response = client.post("/topics/new", data={"name": "no-csrf"})
    assert response.status_code == 400
    assert "CSRF" in response.text


def test_viewer_cannot_write(client):
    login(client, "viewer", "viewer1234")
    page = client.get("/topics/new")
    assert page.status_code == 403

    token = get_csrf(client, "/")
    response = client.post(
        "/topics/new",
        data={
            "csrf_token": token,
            "name": "viewer-topic",
            "message_type": "NORMAL",
            "remark": "",
        },
    )
    assert response.status_code == 403


def test_operator_can_create_topic_and_is_audited(client, db):
    from app.audit import write_audit  # noqa: F401  (ensures module import path)
    from conftest import audit_rows

    login(client, "operator", "operator123")
    form_page = client.get("/topics/new")
    assert form_page.status_code == 200

    token = get_csrf(client, "/topics/new")
    response = client.post(
        "/topics/new",
        data={
            "csrf_token": token,
            "name": "test-topic",
            "message_type": "NORMAL",
            "remark": "created by test",
            "max_send_tps": "100",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/topics/test-topic" in response.headers["location"]

    detail = client.get("/topics/test-topic")
    assert detail.status_code == 200
    assert "test-topic" in detail.text

    rows = audit_rows(db, "topic.create")
    assert any(
        row.username == "operator" and row.target == "test-topic" and row.result == "success"
        for row in rows
    )

    # Operators may update but not delete.
    assert client.get("/topics/test-topic/edit").status_code == 200
    delete_page = client.get("/topics/test-topic/delete")
    assert delete_page.status_code == 403


def test_admin_topic_delete_requires_exact_name(client, db):
    from app.deps import get_service
    from conftest import audit_rows

    login(client)
    get_service().create_topic(
        "rmq-cn-mock-001",
        name="delete-me",
        message_type="NORMAL",
        remark="",
    )

    page = client.get("/topics/delete-me/delete")
    assert page.status_code == 200
    token = get_csrf(client, "/topics/delete-me/delete")

    wrong = client.post(
        "/topics/delete-me/delete",
        data={"csrf_token": token, "confirm_name": "delete-me-typo"},
    )
    assert wrong.status_code == 400
    assert get_service().get_topic("rmq-cn-mock-001", "delete-me").name == "delete-me"

    correct = client.post(
        "/topics/delete-me/delete",
        data={"csrf_token": token, "confirm_name": "delete-me"},
        follow_redirects=False,
    )
    assert correct.status_code == 303

    missing = client.get("/topics/delete-me")
    assert missing.status_code == 404

    rows = audit_rows(db, "topic.delete")
    assert any(row.result == "failure" for row in rows)
    assert any(row.result == "success" for row in rows)


def test_instance_whitelist_blocks_other_instances(client):
    login(client, "viewer", "viewer1234")
    response = client.get("/topics", params={"instance": "rmq-cn-not-allowed"})
    assert response.status_code == 403
    assert "白名单" in response.text

    from app.deps import get_service
    from app.service_errors import InstanceNotAllowed

    service = get_service()
    try:
        service.get_topic("rmq-cn-not-allowed", "order-events")
    except InstanceNotAllowed:
        pass
    else:
        raise AssertionError("instance whitelist was not enforced")
