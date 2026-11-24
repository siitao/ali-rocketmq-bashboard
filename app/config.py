from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables and .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RocketMQ Console"
    environment: str = "production"

    secret_key: str = "dev-only-secret-change-me"
    database_url: str = "sqlite:///./data/app.db"
    session_ttl_hours: int = 8
    cookie_secure: bool = False

    aliyun_region: str = "cn-hangzhou"
    aliyun_endpoint: str = ""
    allowed_instance_ids: str = ""

    # Optional static credentials for local development. On ECS leave these
    # empty and attach an instance RAM role instead.
    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""

    mock_aliyun: bool = False
    log_level: str = "INFO"

    default_message_query_minutes: int = 30
    max_message_query_hours: int = 24

    @property
    def instance_ids(self) -> list[str]:
        return [item.strip() for item in self.allowed_instance_ids.split(",") if item.strip()]

    @property
    def rocketmq_endpoint(self) -> str:
        if self.aliyun_endpoint:
            return self.aliyun_endpoint
        return f"rocketmq.{self.aliyun_region}.aliyuncs.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
