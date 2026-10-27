"""Analysis worker (R2 starter, needed for the end-to-end demo).

This is the minimal end-to-end loop: claim one job → call the AI service →
validate the output → write ``analysis_runs`` / ``comment_issues`` / ``issues``
and finish the comment + job in one transaction.

R2 hardens this file: lease/fencing, retry/backoff, error-code taxonomy, batch
completion bookkeeping and metrics.  R3 owns the grouping quality; the current
rule is "same product + category reuses the first proposed/confirmed issue".
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import timedelta

import httpx
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_session_factory
from services.common.models import (
    AnalysisRun,
    AnalysisStatus,
    Comment,
    CommentIssue,
    ErrorCode,
    HasIssue,
    Issue,
    IssueStatus,
    Job,
    JobStatus,
    LinkOrigin,
    LinkStatus,
    utcnow,
)
from services.common.schemas import ExtractionResult

configure_logging()
logger = logging.getLogger("services.worker.main")
settings = get_settings()

LEASE_SECONDS = 600
MAX_ATTEMPTS = 3


def claim_next_pending_job(db: Session) -> Job | None:
    stmt = (
        select(Job)
        .where(Job.status == JobStatus.PENDING.value)
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    if db.get_bind().dialect.name == "postgresql":
        stmt = stmt.with_for_update(skip_locked=True)
    job = db.execute(stmt).scalars().first()
    if job is None:
        return None

    now = utcnow()
    job.status = JobStatus.CLAIMED.value
    job.claimed_at = now
    job.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    job.attempts += 1
    db.commit()
    db.refresh(job)
    return job


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return ErrorCode.AI_TIMEOUT.value
    if isinstance(exc, httpx.HTTPError):
        return ErrorCode.AI_ERROR.value
    if isinstance(exc, (ValidationError, ValueError)):
        return ErrorCode.AI_INVALID_OUTPUT.value
    return ErrorCode.UNKNOWN.value


def _comment_version(db: Session, comment: Comment) -> int:
    from services.common.models import CommentRevision

    last = db.execute(
        select(CommentRevision.version)
        .where(CommentRevision.comment_id == comment.id)
        .order_by(CommentRevision.version.desc())
        .limit(1)
    ).scalar()
    return last or 1


def _upsert_link(db: Session, link: CommentIssue | None, **values) -> None:
    if link is None:
        db.add(CommentIssue(**values))
        return
    for key, value in values.items():
        setattr(link, key, value)


def process_job(job_id: int) -> None:
    session_factory = get_session_factory()

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        comment = db.get(Comment, job.comment_id)
        if comment is None:
            raise RuntimeError(f"comment {job.comment_id} not found for job {job_id}")
        payload = {
            "comment_id": comment.id,
            "body": comment.body,
            "product_id": comment.product_id,
        }

    response = httpx.post(
        f"{settings.ai_service_url}/extract-issues",
        json=payload,
        timeout=settings.worker_request_timeout_seconds,
    )
    response.raise_for_status()
    result = ExtractionResult.model_validate(response.json())

    with session_factory() as db:
        job = db.get(Job, job_id)
        comment = db.get(Comment, job.comment_id) if job else None
        if job is None or comment is None:
            return

        run = AnalysisRun(
            job_id=job.id,
            comment_id=comment.id,
            model_version=result.model_version,
            prompt_version=result.prompt_version,
            category_version=result.category_version,
            input_hash=hashlib.sha256(comment.body.encode("utf-8")).hexdigest(),
            output_json=result.model_dump(mode="json"),
            status="succeeded",
        )
        db.add(run)
        db.flush()

        # Supersede previous AI suggestions (human decisions are untouched).
        db.execute(
            update(CommentIssue)
            .where(
                CommentIssue.comment_id == comment.id,
                CommentIssue.origin == LinkOrigin.AI.value,
                CommentIssue.status == LinkStatus.SUGGESTED.value,
                CommentIssue.superseded_at.is_(None),
            )
            .values(superseded_at=utcnow())
        )

        version = _comment_version(db, comment)
        verified = 0
        for extracted in result.issues:
            start = comment.body.find(extracted.evidence_text)
            if start < 0:
                logger.warning(
                    "evidence_not_located",
                    extra={"comment_id": comment.id, "evidence": extracted.evidence_text[:80]},
                )
                continue
            issue = db.execute(
                select(Issue)
                .where(
                    Issue.product_id == comment.product_id,
                    Issue.category_id == extracted.category_id,
                    Issue.status.in_(
                        [IssueStatus.PROPOSED.value, IssueStatus.CONFIRMED.value]
                    ),
                )
                .order_by(Issue.created_at.asc())
                .limit(1)
            ).scalars().first()
            if issue is None:
                issue = Issue(
                    platform=comment.platform,
                    shop_id=comment.shop_id,
                    product_id=comment.product_id,
                    category_id=extracted.category_id,
                    title=extracted.description[:120],
                    description=extracted.description,
                    status=IssueStatus.PROPOSED.value,
                    created_by="ai",
                )
                db.add(issue)
                db.flush()
            existing = db.execute(
                select(CommentIssue).where(
                    CommentIssue.comment_id == comment.id,
                    CommentIssue.issue_id == issue.id,
                )
            ).scalars().first()
            _upsert_link(
                db,
                existing,
                comment_id=comment.id,
                issue_id=issue.id,
                status=LinkStatus.SUGGESTED.value,
                origin=LinkOrigin.AI.value,
                evidence_text=extracted.evidence_text,
                evidence_start=start,
                evidence_end=start + len(extracted.evidence_text),
                evidence_verified=True,
                analysis_run_id=run.id,
                comment_version=version,
                superseded_at=None,
            )
            verified += 1

        has_issue = result.has_issue
        if has_issue == HasIssue.YES and verified == 0:
            has_issue = HasIssue.UNKNOWN

        comment.analysis_status = AnalysisStatus.ANALYZED.value
        comment.has_issue = has_issue.value
        comment.current_analysis_run_id = run.id
        comment.analysis_error = None

        job.status = JobStatus.COMPLETED.value
        job.completed_at = utcnow()
        job.error = None
        job.error_code = None
        db.commit()

    logger.info(
        "job_completed",
        extra={"job_id": job_id, "has_issue": has_issue.value, "verified_issues": verified},
    )


def mark_job_failed(job_id: int, error_code: str, message: str) -> None:
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.FAILED.value
        job.completed_at = utcnow()
        job.error_code = error_code
        job.error = message[:1000]
        comment = db.get(Comment, job.comment_id) if job.comment_id else None
        if comment is not None:
            comment.analysis_status = AnalysisStatus.FAILED.value
            comment.analysis_error = message[:500]
        db.commit()


def recover_stale_jobs() -> int:
    """Return lease-expired claimed jobs to pending (R2 will move this to a cron)."""
    session_factory = get_session_factory()
    with session_factory() as db:
        stale = db.execute(
            select(Job).where(
                Job.status == JobStatus.CLAIMED.value,
                Job.lease_expires_at.is_not(None),
                Job.lease_expires_at < utcnow(),
            )
        ).scalars().all()
        for job in stale:
            job.status = JobStatus.PENDING.value
            job.attempts += 1
            job.error_code = ErrorCode.LEASE_EXPIRED.value
        if stale:
            db.commit()
    return len(stale)


def run_worker() -> None:
    session_factory = get_session_factory()
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "ai_service_url": settings.ai_service_url,
        },
    )

    while True:
        job = None
        try:
            recovered = recover_stale_jobs()
            if recovered:
                logger.info("jobs_recovered", extra={"count": recovered})
            with session_factory() as db:
                job = claim_next_pending_job(db)
            if job is None:
                time.sleep(settings.worker_poll_seconds)
                continue

            logger.info("job_claimed", extra={"job_id": job.id})
            process_job(job.id)
        except KeyboardInterrupt:
            logger.info("worker_stopped")
            raise
        except Exception as exc:  # noqa: BLE001 - boundary of the job loop
            logger.exception("job_processing_failed")
            if job is not None:
                mark_job_failed(job.id, _classify_error(exc), str(exc))
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run_worker()
