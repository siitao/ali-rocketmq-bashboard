from __future__ import annotations


class AppError(Exception):
    """User-facing error rendered as an HTML page."""

    def __init__(self, message: str, status_code: int = 400, hint: str | None = None) -> None:
        self.message = message
        self.status_code = status_code
        self.hint = hint
        super().__init__(message)


class AuthRequired(Exception):
    """Raised by dependencies when an unauthenticated user hits a protected page."""

    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url
        super().__init__("authentication required")
