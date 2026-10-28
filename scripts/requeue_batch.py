"""Manually requeue failed jobs for one ingestion batch (R2 ops tool).

Example:
  python scripts/requeue_batch.py --batch-id <uuid> --status failed
"""

from __future__ import annotations

import argparse
import sys

from services.common.db import get_session_factory
from services.common.models import JobStatus
from services.worker.app.lifecycle import requeue_batch_jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Requeue analysis jobs for a batch")
    parser.add_argument("--batch-id", required=True, help="ingestion batch id")
    parser.add_argument(
        "--status",
        default=JobStatus.FAILED.value,
        choices=[JobStatus.FAILED.value],
        help="only failed jobs are supported for manual replay",
    )
    parser.add_argument(
        "--operator",
        default="requeue_batch",
        help="operator label written to structured logs",
    )
    args = parser.parse_args(argv)

    session_factory = get_session_factory()
    with session_factory() as db:
        count = requeue_batch_jobs(
            db,
            args.batch_id,
            status=args.status,
            operator=args.operator,
        )
        db.commit()
    print(f"requeued={count} batch_id={args.batch_id} status={args.status}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
