"""Recover lease-expired claimed jobs (R2 ops tool).

Run (Compose):
  docker compose run --rm worker python scripts/recover_stale_jobs.py

Or with local env pointing at Postgres:
  python scripts/recover_stale_jobs.py
"""

from __future__ import annotations

import sys

from services.common.db import get_session_factory
from services.worker.app.lifecycle import recover_stale_jobs


def main() -> int:
    session_factory = get_session_factory()
    with session_factory() as db:
        count = recover_stale_jobs(db)
    print(f"recovered={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
