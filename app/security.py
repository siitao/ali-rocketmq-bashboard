from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request
from starlette.datastructures import FormData

_hasher = PasswordHasher()

MAX_PASSWORD_LENGTH = 128
# Used to keep login timing comparable when the username does not exist.
DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(32))


def safe_next_url(value: str | None, default: str = "/") -> str:
    """Allow only local absolute paths; block schemes, //host and backslash tricks."""
    if not value:
        return default
    if any(char in value for char in ("\\", "\r", "\n", "\x00")):
        return default
    if not value.startswith("/") or value.startswith("//"):
        return default
    try:
        parsed = urlsplit(value)
    except ValueError:
        return default
    if parsed.scheme or parsed.netloc:
        return default
    return value


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def get_csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf"] = token
    return token


def verify_csrf_token(request: Request, token: str | None) -> bool:
    expected = request.session.get("csrf")
    return bool(expected and token and secrets.compare_digest(expected, token))


async def read_form_with_csrf(request: Request) -> FormData:
    form = await request.form()
    if not verify_csrf_token(request, form.get("csrf_token")):
        raise HTTPException(status_code=400, detail="CSRF 校验失败，请刷新页面后重试")
    return form


class LoginRateLimiter:
    """Single-process in-memory limiter. Deploy with one uvicorn worker."""

    def __init__(
        self,
        max_attempts: int = 5,
        max_ip_attempts: int = 20,
        window_seconds: int = 900,
    ) -> None:
        self.max_attempts = max_attempts
        self.max_ip_attempts = max_ip_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._ip_attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _key(ip: str, username: str) -> str:
        return f"{ip}|{username.strip().lower()}"

    def is_limited(self, ip: str, username: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts[self._key(ip, username)]
            ip_bucket = self._ip_attempts[ip]
            self._trim(bucket, now)
            self._trim(ip_bucket, now)
            return (
                len(bucket) >= self.max_attempts
                or len(ip_bucket) >= self.max_ip_attempts
            )

    def record_failure(self, ip: str, username: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._attempts[self._key(ip, username)]
            ip_bucket = self._ip_attempts[ip]
            self._trim(bucket, now)
            self._trim(ip_bucket, now)
            bucket.append(now)
            ip_bucket.append(now)

    def reset(self, ip: str, username: str) -> None:
        with self._lock:
            self._attempts.pop(self._key(ip, username), None)

    def clear(self) -> None:
        with self._lock:
            self._attempts.clear()
            self._ip_attempts.clear()

    def _trim(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()


login_limiter = LoginRateLimiter()
