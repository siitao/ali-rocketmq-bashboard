from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

import pytest

TMP_DIR = Path(tempfile.mkdtemp(prefix="rmq-console-tests-"))
os.environ.update(
    {
        "MOCK_ALIYUN": "1",
        "ALLOWED_INSTANCE_IDS": "rmq-cn-mock-001",
        "ALIYUN_REGION": "cn-hangzhou",
        "DATABASE_URL": f"sqlite:///{TMP_DIR.as_posix()}/test.db",
        "SECRET_KEY": "test-secret-key",
        "COOKIE_SECURE": "false",
        "LOG_LEVEL": "WARNING",
    }
)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.deps import get_service  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuditLog, User  # noqa: E402
from app.security import hash_password, login_limiter  # noqa: E402

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')

USERS = [
    ("admin", "admin12345", "admin", True),
    ("operator", "operator123", "operator", True),
    ("viewer", "viewer1234", "viewer", True),
]


def get_csrf(client: TestClient, path: str = "/login") -> str:
    response = client.get(path)
    assert response.status_code == 200, response.text
    match = CSRF_RE.search(response.text)
    assert match is not None, response.text[:800]
    return match.group(1)


def login(client: TestClient, username: str = "admin", password: str = "admin12345"):
    token = get_csrf(client, "/login")
    response = client.post(
        "/login",
        data={
            "csrf_token": token,
            "username": username,
            "password": password,
            "next": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for username, password, role, active in USERS:
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    role=role,
                    is_active=active,
                )
            )
        db.commit()

    login_limiter.clear()
    get_service.cache_clear()

    with TestClient(app) as test_client:
        yield test_client

    login_limiter.clear()
    get_service.cache_clear()


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


def audit_rows(db, action: str | None = None):
    from sqlalchemy import select

    statement = select(AuditLog).order_by(AuditLog.id)
    if action:
        statement = statement.where(AuditLog.action == action)
    return db.scalars(statement).all()
