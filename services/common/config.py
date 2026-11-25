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

    llm_provider: Literal["heuristic", "openai_compatible"] = "heuristic"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_api_key_header: str = "api-key"
    llm_timeout_seconds: float = Field(default=8.0, gt=0, le=120)
    llm_prompt_version: str = "review-extraction-v1"

    # Semantic grouping (sentence embeddings). Not used for /extract-issues.
    grouping_enabled: bool = True
    # Dual thresholds: T_main (link if keyword overlap) and T_high (no-overlap bypass).
    # Env still uses GROUPING_OVERLAP_THRESHOLD for T_high (see EVAL_NOTES.md).
    grouping_similarity_threshold: float = 0.35  # T_main
    grouping_keyword_gate: bool = True
    grouping_overlap_threshold: float = 0.55  # T_high (>= T_main); no-keyword bypass
    # Ambiguous when best and second-best scores are too close → create_new.
    grouping_top2_margin: float = 0.08
    grouping_embedding_backend: Literal[
        "auto", "sentence_transformers", "hashing", "none"
    ] = "auto"
    grouping_embedding_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def extraction_request_timeout_seconds(self) -> float:
        # Three model attempts, retry pauses, parsing and transport overhead.
        return max(self.worker_request_timeout_seconds, self.llm_timeout_seconds * 3 + 10)

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
