from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pythonjsonlogger import jsonlogger


class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/maie6000c"
    ai_service_url: str = "http://ai:8100"
    review_auth_mode: Literal["demo", "session"] = "demo"
    review_demo_operator: str = "demo-reviewer"
    review_cookie_secure: bool = True
    review_session_hours: int = Field(default=8, ge=1, le=24)
    worker_poll_seconds: float = 2.0
    worker_request_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def require_secure_deployment(self):
        if self.app_env not in {"development", "test"}:
            if self.review_auth_mode != "session" or not self.review_cookie_secure:
                raise ValueError(
                    "Non-development deployments require session auth and HTTPS cookies"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


class ServiceJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record: dict, record: logging.LogRecord, message_dict: dict) -> None:
        super().add_fields(log_record, record, message_dict)
        if "service" not in log_record:
            parts = record.name.split(".")
            log_record["service"] = parts[1] if len(parts) > 1 and parts[0] == "services" else "app"


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    settings = get_settings()
    handler = logging.StreamHandler()
    handler.setFormatter(
        ServiceJsonFormatter("%(asctime)s %(levelname)s %(service)s %(name)s %(message)s")
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())

    configure_logging._configured = True  # type: ignore[attr-defined]
