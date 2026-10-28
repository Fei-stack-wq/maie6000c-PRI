"""PostgreSQL-only concurrency check for SKIP LOCKED claim.

Skipped automatically when DATABASE_URL is not PostgreSQL (local SQLite runs).
CI sets DATABASE_URL to the Postgres service, so this test runs there.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest
from datetime import timedelta

from sqlalchemy import delete, update

from services.common.db import make_engine, make_session_factory
from services.common.models import (
    AnalysisStatus,
    Comment,
    Job,
    JobStatus,
    JobType,
    utcnow,
)
from services.worker.app.lifecycle import claim_next_pending_job

DATABASE_URL = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(
    not DATABASE_URL.startswith("postgresql"),
    reason="SKIP LOCKED concurrency requires PostgreSQL (DATABASE_URL)",
)
def test_concurrent_claim_only_one_worker_wins():
    engine = make_engine(DATABASE_URL)
    session_factory = make_session_factory(engine)
    source_id = f"concurrent-{uuid.uuid4()}"
    job_id: int | None = None
    comment_id: str | None = None

    try:
        with session_factory() as db:
            comment = Comment(
                platform="demo",
                shop_id="shop-concurrent",
                product_id="bag-concurrent",
                source_review_id=source_id,
                body="并发认领测试评论：拉链卡住。",
                content_hash=f"hash-{source_id}",
                analysis_status=AnalysisStatus.QUEUED.value,
            )
            db.add(comment)
            db.flush()
            job = Job(
                comment_id=comment.id,
                job_type=JobType.EXTRACT_ISSUES.value,
                status=JobStatus.PENDING.value,
                attempts=0,
                max_attempts=3,
            )
            db.add(job)
            db.flush()
            job_id = job.id
            comment_id = comment.id
            # Ensure this job is the only one claimable right now.
            db.execute(
                update(Job)
                .where(Job.status == JobStatus.PENDING.value, Job.id != job_id)
                .values(next_attempt_at=utcnow() + timedelta(days=365))
            )
            db.commit()

        barrier = threading.Barrier(2)
        results: list[int | None] = []
        lock = threading.Lock()

        def _claim() -> None:
            with session_factory() as db:
                barrier.wait(timeout=10)
                claimed = claim_next_pending_job(db)
                with lock:
                    results.append(claimed.id if claimed is not None else None)

        threads = [threading.Thread(target=_claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert len(results) == 2
        assert results.count(job_id) == 1
        assert results.count(None) == 1

        with session_factory() as db:
            job = db.get(Job, job_id)
            assert job is not None
            assert job.status == JobStatus.CLAIMED.value
            assert job.attempts == 1
    finally:
        with session_factory() as db:
            if job_id is not None:
                db.execute(delete(Job).where(Job.id == job_id))
            if comment_id is not None:
                db.execute(delete(Comment).where(Comment.id == comment_id))
            db.commit()
        engine.dispose()
