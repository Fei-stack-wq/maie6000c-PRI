"""Drop the whole database schema and rebuild it from the migrations.

Used for local development: ``make reset-db`` (PostgreSQL, Docker Compose).
Deletes ALL data, including legacy tables from earlier milestones.

Usage:
    python scripts/reset_database.py [--yes]

The optional ``--yes`` skips the interactive confirmation (used in CI / demos).
"""

from __future__ import annotations

import argparse
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from services.common.config import get_settings


def _is_postgres(url: str) -> bool:
    return url.startswith("postgresql")


def reset_postgres(url: str) -> None:
    engine = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


def reset_sqlite(url: str) -> None:
    """Best effort for SQLite dev databases: drop every known table."""
    from services.common import models  # noqa: F401  (register metadata)
    from services.common.db import Base

    engine = create_engine(url)
    try:
        Base.metadata.drop_all(bind=engine)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the review-management database")
    parser.add_argument("--yes", action="store_true", help="skip confirmation")
    args = parser.parse_args()

    settings = get_settings()
    url = settings.database_url
    target = url.split("@")[-1] if "@" in url else url
    if not args.yes:
        print(f"This will DELETE ALL DATA in: {target}")
        answer = input("Type 'reset' to continue: ").strip().lower()
        if answer != "reset":
            print("Aborted.")
            return 1

    if _is_postgres(url):
        reset_postgres(url)
    else:
        reset_sqlite(url)

    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("Database reset and migrated to head.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
