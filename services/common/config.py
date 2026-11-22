from __future__ import annotations

import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pythonjsonlogger import jsonlogger

from typing import Literal

class Settings(BaseSettings):
    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://postgres:postgres@db:5432/maie6000c"
    ai_service_url: str = "http://ai:8100"
    worker_poll_seconds: float = 2.0
    worker_request_timeout_seconds: float = 20.0

    llm_provider: Literal["heuristic", "openai_compatible"] = "heuristic"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_api_key_header: str = "api-key"
    llm_timeout_seconds: float = 8.0
    llm_prompt_version: str = "review-extraction-v1"

    # Semantic grouping (sentence embeddings). Not used for /extract-issues.
    grouping_enabled: bool = True
    # Dual thresholds: T_main (with keyword overlap) and T_overlap (no-overlap bypass).
    # Locked on LLM description pairs when available (see data/grouping_eval/EVAL_NOTES.md).
    grouping_similarity_threshold: float = 0.35  # T_main
    grouping_keyword_gate: bool = True
    grouping_overlap_threshold: float = 0.55  # T_overlap (>= T_main)
    # Ambiguous when best and second-best scores are too close → create_new.
    grouping_top2_margin: float = 0.08
    grouping_embedding_backend: Literal[
        "auto", "sentence_transformers", "hashing", "none"
    ] = "auto"
    grouping_embedding_model: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


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
