"""Analysis worker (R2): claim → AI extract → validate → persist with fencing.

Owns Job reliability: lease/fencing, retry/backoff, error-code taxonomy,
manual replay helpers (used by API thin routes + ops scripts), and metrics.
R3 owns grouping quality; this file only depends on the HTTP ExtractionResult
contract.
"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import time
from datetime import datetime
from time import perf_counter

import httpx
from pydantic import ValidationError
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.common.config import configure_logging, get_settings
from services.common.db import get_session_factory
from services.common.models import (
    AnalysisRun,
    AnalysisStatus,
    Comment,
    CommentIssue,
    CommentRevision,
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
from services.worker.app.lifecycle import (
    LEASE_SECONDS,
    CommentMissingError,
    JobConflictError,
    JobNotFoundError,
    backoff_delta,
    claim_next_pending_job,
    fail_or_retry,
    fence_complete_job,
    mark_comment_analyzing,
    recover_job,
    recover_stale_jobs,
    requeue_batch_jobs,
    retry_job,
    sanitize_error_message,
    should_auto_retry,
)
from services.worker.app.metrics import (
    WORKER_AI_LATENCY,
    WORKER_EVIDENCE_MISS,
    WORKER_JOBS_CLAIMED,
    WORKER_JOBS_COMPLETED,
    WORKER_JOBS_FAILED,
    WORKER_JOBS_REQUEUED,
    WORKER_QUEUE_DEPTH,
    start_metrics_server,
)

configure_logging()
logger = logging.getLogger("services.worker.main")
settings = get_settings()

# Re-export lifecycle symbols so existing tests/scripts can import from main.
__all__ = [
    "LEASE_SECONDS",
    "CommentMissingError",
    "JobConflictError",
    "JobNotFoundError",
    "backoff_delta",
    "claim_next_pending_job",
    "fail_or_retry",
    "fence_complete_job",
    "process_job",
    "recover_job",
    "recover_stale_jobs",
    "requeue_batch_jobs",
    "retry_job",
    "run_worker",
    "sanitize_error_message",
    "should_auto_retry",
]

_shutdown = False


def _request_shutdown(signum: int, frame: object | None) -> None:  # noqa: ARG001
    global _shutdown
    logger.info("worker_shutdown_requested", extra={"signal": signum})
    _shutdown = True


def _classify_error(exc: Exception) -> str:
    if isinstance(exc, CommentMissingError):
        return ErrorCode.COMMENT_NOT_FOUND.value
    if isinstance(exc, httpx.TimeoutException):
        return ErrorCode.AI_TIMEOUT.value
    if isinstance(exc, httpx.HTTPError):
        return ErrorCode.AI_ERROR.value
    if isinstance(exc, SQLAlchemyError):
        return ErrorCode.DB_ERROR.value
    if isinstance(exc, (ValidationError, ValueError)):
        return ErrorCode.AI_INVALID_OUTPUT.value
    return ErrorCode.UNKNOWN.value


def _comment_version(db: Session, comment: Comment) -> int:
    last = db.execute(
        select(CommentRevision.version)
        .where(CommentRevision.comment_id == comment.id)
        .order_by(CommentRevision.version.desc())
        .limit(1)
    ).scalar()
    return last or 1


def _upsert_ai_link(db: Session, existing: CommentIssue | None, **values: object) -> bool:
    """Write or refresh an AI suggested link. Never overwrite accepted/rejected."""
    if existing is not None and existing.status in (
        LinkStatus.ACCEPTED.value,
        LinkStatus.REJECTED.value,
    ):
        logger.info(
            "skip_human_link",
            extra={
                "comment_id": existing.comment_id,
                "issue_id": existing.issue_id,
                "status": existing.status,
            },
        )
        return False
    if existing is None:
        db.add(CommentIssue(**values))
        return True
    for key, value in values.items():
        setattr(existing, key, value)
    return True


def _refresh_queue_depth(db: Session) -> None:
    now = utcnow()
    depth = db.execute(
        select(func.count())
        .select_from(Job)
        .where(
            Job.status == JobStatus.PENDING.value,
            or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
        )
    ).scalar()
    WORKER_QUEUE_DEPTH.set(int(depth or 0))


def _fail_claimed(
    job_id: int,
    seen_claimed_at: datetime | None,
    error_code: str,
    message: str,
) -> None:
    session_factory = get_session_factory()
    with session_factory() as db:
        outcome = fail_or_retry(db, job_id, seen_claimed_at, error_code, message)
    if outcome == "requeued":
        WORKER_JOBS_REQUEUED.labels(error_code).inc()
    elif outcome == "failed":
        WORKER_JOBS_FAILED.labels(error_code).inc()


def process_job(job_id: int) -> None:
    session_factory = get_session_factory()
    seen_claimed_at: datetime | None = None

    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.CLAIMED.value:
            return
        seen_claimed_at = job.claimed_at
        comment = db.get(Comment, job.comment_id)
        if comment is None:
            _fail_claimed(
                job_id,
                seen_claimed_at,
                ErrorCode.COMMENT_NOT_FOUND.value,
                f"comment {job.comment_id} not found for job {job_id}",
            )
            return
        payload = {
            "comment_id": comment.id,
            "body": comment.body,
            "product_id": comment.product_id,
        }
        try:
            mark_comment_analyzing(db, job, seen_claimed_at)
        except CommentMissingError as exc:
            _fail_claimed(
                job_id,
                seen_claimed_at,
                ErrorCode.COMMENT_NOT_FOUND.value,
                str(exc),
            )
            return

    started = perf_counter()
    try:
        response = httpx.post(
            f"{settings.ai_service_url}/extract-issues",
            json=payload,
            timeout=settings.worker_request_timeout_seconds,
        )
        response.raise_for_status()
        result = ExtractionResult.model_validate(response.json())
    except Exception as exc:  # noqa: BLE001 - classified at the job boundary
        WORKER_AI_LATENCY.observe(perf_counter() - started)
        logger.exception(
            "job_processing_failed",
            extra={"job_id": job_id, "error_code": _classify_error(exc)},
        )
        _fail_claimed(job_id, seen_claimed_at, _classify_error(exc), str(exc))
        return

    WORKER_AI_LATENCY.observe(perf_counter() - started)

    with session_factory() as db:
        job = db.get(Job, job_id)
        comment = db.get(Comment, job.comment_id) if job else None
        if job is None or comment is None:
            return
        if job.status != JobStatus.CLAIMED.value or job.claimed_at != seen_claimed_at:
            logger.warning(
                "fencing_rejected_before_persist",
                extra={"job_id": job_id, "status": job.status},
            )
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

        # Only supersede AI suggestions; human accepted/rejected stay put.
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
                WORKER_EVIDENCE_MISS.inc()
                logger.warning(
                    "evidence_not_located",
                    extra={
                        "comment_id": comment.id,
                        "evidence": extracted.evidence_text[:80],
                    },
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
            wrote = _upsert_ai_link(
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
            if wrote:
                verified += 1

        has_issue = result.has_issue
        if has_issue == HasIssue.YES and verified == 0:
            has_issue = HasIssue.UNKNOWN

        comment.analysis_status = AnalysisStatus.ANALYZED.value
        comment.has_issue = has_issue.value
        comment.current_analysis_run_id = run.id
        comment.analysis_error = None

        if not fence_complete_job(db, job_id, seen_claimed_at):
            db.rollback()
            return
        db.commit()

    WORKER_JOBS_COMPLETED.inc()
    logger.info(
        "job_completed",
        extra={
            "job_id": job_id,
            "has_issue": has_issue.value,
            "verified_issues": verified,
        },
    )


def mark_job_failed(job_id: int, error_code: str, message: str) -> None:
    """Apply fail_or_retry only while the job is still claimed (fencing-safe)."""
    session_factory = get_session_factory()
    with session_factory() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != JobStatus.CLAIMED.value:
            return
        outcome = fail_or_retry(db, job_id, job.claimed_at, error_code, message)
        if outcome == "requeued":
            WORKER_JOBS_REQUEUED.labels(error_code).inc()
        elif outcome == "failed":
            WORKER_JOBS_FAILED.labels(error_code).inc()


def run_worker() -> None:
    global _shutdown
    _shutdown = False
    signal.signal(signal.SIGTERM, _request_shutdown)
    signal.signal(signal.SIGINT, _request_shutdown)

    metrics_port = int(os.environ.get("WORKER_METRICS_PORT", "8200"))
    try:
        start_metrics_server(metrics_port)
        logger.info("worker_metrics_started", extra={"port": metrics_port})
    except OSError as exc:
        logger.warning("worker_metrics_unavailable", extra={"error": str(exc)})

    session_factory = get_session_factory()
    logger.info(
        "worker_started",
        extra={
            "poll_seconds": settings.worker_poll_seconds,
            "ai_service_url": settings.ai_service_url,
            "lease_seconds": LEASE_SECONDS,
        },
    )

    while not _shutdown:
        job = None
        try:
            with session_factory() as db:
                recovered = recover_stale_jobs(db)
                _refresh_queue_depth(db)
            if recovered:
                logger.info("jobs_recovered", extra={"count": recovered})

            with session_factory() as db:
                job = claim_next_pending_job(db)
            if job is None:
                time.sleep(settings.worker_poll_seconds)
                continue

            WORKER_JOBS_CLAIMED.inc()
            logger.info(
                "job_claimed",
                extra={
                    "job_id": job.id,
                    "attempts": job.attempts,
                    "claimed_at": job.claimed_at.isoformat() if job.claimed_at else None,
                },
            )
            try:
                process_job(job.id)
            except Exception as exc:  # noqa: BLE001 - already recorded via _fail_claimed
                logger.exception(
                    "job_processing_failed",
                    extra={"job_id": job.id, "error_code": _classify_error(exc)},
                )
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            logger.exception("worker_loop_error")
            if job is not None:
                mark_job_failed(job.id, _classify_error(exc), str(exc))
            time.sleep(settings.worker_poll_seconds)

    logger.info("worker_stopped_cleanly")


if __name__ == "__main__":
    run_worker()
