"""Worker-only settings; shared service addresses remain in common.config."""
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    lease_seconds: float = Field(default=600, gt=0)
    retry_base_seconds: float = Field(default=60, gt=0)
    retry_max_seconds: float = Field(default=900, gt=0)
    recovery_limit: int = Field(default=100, ge=1, le=10000)
    metrics_port: int = Field(default=8200, ge=1, le=65535)

    model_config = SettingsConfigDict(env_prefix="WORKER_", env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def check_retry_range(self):
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds must be >= retry_base_seconds")
        return self


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
