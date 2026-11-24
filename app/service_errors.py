from __future__ import annotations


class ServiceError(Exception):
    """Uniform error raised by the real SDK service and the mock service."""

    def __init__(self, message: str, *, code: str = "ServiceError", status_code: int = 502) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


class InstanceNotAllowed(ServiceError):
    def __init__(self, instance_id: str) -> None:
        super().__init__(
            f"实例 {instance_id} 不在面板白名单内",
            code="InstanceNotAllowed",
            status_code=403,
        )


class ValidationError(ServiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="ValidationError", status_code=400)
