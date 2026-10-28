"""Job lifecycle helpers owned by R2 (claim / fencing / retry / recover).

API routes and ops scripts should call these functions instead of duplicating
status-machine logic. Shared schemas/models are not modified here.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from services.common.models import (
    AnalysisStatus,
    Comment,
    ErrorCode,
    Job,
    JobStatus,
    utcnow,
)

logger = logging.getLogger("services.worker.lifecycle")

LEASE_SECONDS = 600
DEFAULT_MAX_ATTEMPTS = 3
# Backoff after the N-th failed claim: 1 min / 5 min / 15 min.
BACKOFF_SECONDS = (60, 300, 900)

_RETRYABLE = frozenset(
    {
        ErrorCode.AI_TIMEOUT.value,
        ErrorCode.AI_ERROR.value,
        ErrorCode.DB_ERROR.value,
        ErrorCode.LEASE_EXPIRED.value,
    }
)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class JobNotFoundError(Exception):
    """Raised when a job id does not exist."""


class JobConflictError(Exception):
    """Illegal status transition (maps to HTTP 409)."""

    def __init__(self, message: str, *, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class CommentMissingError(Exception):
    """Comment row missing for a job — maps to error_code=comment_not_found."""


def sanitize_error_message(message: str, limit: int = 1000) -> str:
    """Strip URLs and truncate so API/DB never store internal endpoints."""
    cleaned = _URL_RE.sub("<redacted-url>", message or "")
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit]


def backoff_delta(attempts: int) -> timedelta:
    idx = min(max(attempts, 1), len(BACKOFF_SECONDS)) - 1
    return timedelta(seconds=BACKOFF_SECONDS[idx])


def should_auto_retry(error_code: str, attempts: int, max_attempts: int) -> bool:
    if attempts >= max_attempts:
        return False
    if error_code in _RETRYABLE:
        return True
    # ai_invalid_output: one automatic re-queue only (after first failed claim).
    if error_code == ErrorCode.AI_INVALID_OUTPUT.value and attempts < 2:
        return True
    return False


def _is_due(next_attempt_at: datetime | None, now: datetime) -> bool:
    if next_attempt_at is None:
        return True
    return _as_utc(next_attempt_at) <= _as_utc(now)


def claim_next_pending_job(db: Session, *, lease_seconds: int = LEASE_SECONDS) -> Job | None:
    """Atomically claim the oldest due pending job (SKIP LOCKED on PostgreSQL)."""
    now = utcnow()
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.PENDING.value,
                or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
            )
            .order_by(Job.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = db.execute(stmt).scalars().first()
    else:
        # SQLite: naive/aware mismatch on timestamptz — filter due jobs in Python.
        candidates = db.execute(
            select(Job)
            .where(Job.status == JobStatus.PENDING.value)
            .order_by(Job.created_at.asc())
        ).scalars().all()
        job = next((item for item in candidates if _is_due(item.next_attempt_at, now)), None)
        if job is not None:
            # Re-load with a write lock simulation: refresh and re-check status.
            db.refresh(job)
            if job.status != JobStatus.PENDING.value or not _is_due(job.next_attempt_at, now):
                job = None

    if job is None:
        return None

    job.status = JobStatus.CLAIMED.value
    job.claimed_at = now
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.attempts += 1
    job.next_attempt_at = None
    db.commit()
    db.refresh(job)
    return job


def mark_comment_analyzing(db: Session, job: Job, seen_claimed_at: datetime | None) -> bool:
    """Set comment to analyzing if this worker still holds the claim."""
    if not _fence_holds(job, seen_claimed_at):
        return False
    comment = db.get(Comment, job.comment_id) if job.comment_id else None
    if comment is None:
        raise CommentMissingError(f"comment {job.comment_id} missing for job {job.id}")
    comment.analysis_status = AnalysisStatus.ANALYZING.value
    db.commit()
    return True


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fence_holds(job: Job, seen_claimed_at: datetime | None) -> bool:
    if job.status != JobStatus.CLAIMED.value:
        return False
    if seen_claimed_at is None or job.claimed_at is None:
        return False
    # Compare as UTC; SQLite may drop tzinfo or round microseconds.
    delta = abs((_as_utc(job.claimed_at) - _as_utc(seen_claimed_at)).total_seconds())
    return delta < 0.001


def fence_complete_job(
    db: Session,
    job_id: int,
    seen_claimed_at: datetime | None,
) -> bool:
    """Mark job completed only if still claimed with the same claimed_at."""
    now = utcnow()
    result = db.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status == JobStatus.CLAIMED.value,
            Job.claimed_at == seen_claimed_at,
        )
        .values(
            status=JobStatus.COMPLETED.value,
            completed_at=now,
            error=None,
            error_code=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    if result.rowcount == 0:
        logger.warning(
            "fencing_rejected_complete",
            extra={"job_id": job_id, "seen_claimed_at": str(seen_claimed_at)},
        )
        return False
    return True


def fail_or_retry(
    db: Session,
    job_id: int,
    seen_claimed_at: datetime | None,
    error_code: str,
    message: str,
) -> str:
    """Apply fencing then either re-queue with backoff or mark failed.

    Returns ``completed`` | ``requeued`` | ``failed`` | ``fenced`` | ``missing``.
    """
    job = db.get(Job, job_id)
    if job is None:
        return "missing"
    if not _fence_holds(job, seen_claimed_at):
        logger.warning(
            "fencing_rejected_fail",
            extra={"job_id": job_id, "status": job.status, "error_code": error_code},
        )
        return "fenced"

    safe = sanitize_error_message(message)
    comment = db.get(Comment, job.comment_id) if job.comment_id else None
    now = utcnow()
    max_attempts = job.max_attempts or DEFAULT_MAX_ATTEMPTS

    if should_auto_retry(error_code, job.attempts, max_attempts):
        job.status = JobStatus.PENDING.value
        job.next_attempt_at = now + backoff_delta(job.attempts)
        job.claimed_at = None
        job.lease_expires_at = None
        job.completed_at = None
        job.error_code = error_code
        job.error = safe
        if comment is not None:
            comment.analysis_status = AnalysisStatus.QUEUED.value
            comment.analysis_error = safe[:500]
        db.commit()
        logger.info(
            "job_requeued",
            extra={
                "job_id": job_id,
                "error_code": error_code,
                "attempts": job.attempts,
                "next_attempt_at": job.next_attempt_at.isoformat(),
            },
        )
        return "requeued"

    job.status = JobStatus.FAILED.value
    job.completed_at = now
    job.lease_expires_at = None
    job.error_code = error_code
    job.error = safe
    if comment is not None:
        comment.analysis_status = AnalysisStatus.FAILED.value
        comment.analysis_error = safe[:500]
    db.commit()
    logger.info(
        "job_failed",
        extra={"job_id": job_id, "error_code": error_code, "attempts": job.attempts},
    )
    return "failed"


def _apply_lease_recovery(job: Job, comment: Comment | None, now: datetime) -> str:
    """Mutate one stale claimed job. Returns ``requeued`` or ``failed``."""
    job.attempts += 1
    job.error_code = ErrorCode.LEASE_EXPIRED.value
    job.error = sanitize_error_message("lease expired; claim recovered")
    max_attempts = job.max_attempts or DEFAULT_MAX_ATTEMPTS
    if job.attempts >= max_attempts:
        job.status = JobStatus.FAILED.value
        job.completed_at = now
        job.lease_expires_at = None
        if comment is not None:
            comment.analysis_status = AnalysisStatus.FAILED.value
            comment.analysis_error = job.error[:500]
        return "failed"

    job.status = JobStatus.PENDING.value
    job.claimed_at = None
    job.lease_expires_at = None
    job.completed_at = None
    job.next_attempt_at = None
    if comment is not None:
        comment.analysis_status = AnalysisStatus.QUEUED.value
        comment.analysis_error = job.error[:500]
    return "requeued"


def _is_lease_expired(lease_expires_at: datetime | None, now: datetime | None = None) -> bool:
    if lease_expires_at is None:
        return False
    current = _as_utc(now or utcnow())
    return _as_utc(lease_expires_at) < current


def recover_stale_jobs(db: Session) -> int:
    """Return lease-expired claimed jobs to pending (or failed at max attempts)."""
    now = utcnow()
    # SQLite may store naive datetimes; filter expiry in Python after fetch.
    candidates = db.execute(
        select(Job).where(
            Job.status == JobStatus.CLAIMED.value,
            Job.lease_expires_at.is_not(None),
        )
    ).scalars().all()
    stale = [job for job in candidates if _is_lease_expired(job.lease_expires_at, now)]
    if not stale:
        return 0

    for job in stale:
        comment = db.get(Comment, job.comment_id) if job.comment_id else None
        outcome = _apply_lease_recovery(job, comment, now)
        logger.info(
            "job_lease_recovered",
            extra={"job_id": job.id, "outcome": outcome, "attempts": job.attempts},
        )
    db.commit()
    return len(stale)


def retry_job(db: Session, job_id: int, *, operator: str | None = None) -> Job:
    """Manual replay: failed → pending, attempts reset to 0."""
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    if job.status != JobStatus.FAILED.value:
        raise JobConflictError(
            f"retry only allowed for failed jobs (status={job.status})",
            status=job.status,
        )

    job.status = JobStatus.PENDING.value
    job.attempts = 0
    job.next_attempt_at = None
    job.claimed_at = None
    job.lease_expires_at = None
    job.completed_at = None
    job.error_code = None
    job.error = None

    comment = db.get(Comment, job.comment_id) if job.comment_id else None
    if comment is not None:
        comment.analysis_status = AnalysisStatus.QUEUED.value
        comment.analysis_error = None

    logger.info(
        "job_manual_retry",
        extra={"job_id": job_id, "comment_id": job.comment_id, "operator": operator or "system"},
    )
    return job


def recover_job(db: Session, job_id: int, *, operator: str | None = None) -> Job:
    """Manual recover: claimed + lease expired → pending (or failed at cap)."""
    job = db.get(Job, job_id)
    if job is None:
        raise JobNotFoundError(f"job {job_id} not found")
    if job.status != JobStatus.CLAIMED.value:
        raise JobConflictError(
            f"recover only allowed for claimed jobs (status={job.status})",
            status=job.status,
        )
    now = utcnow()
    if not _is_lease_expired(job.lease_expires_at, now):
        raise JobConflictError(
            "recover only allowed when lease has expired",
            status=job.status,
        )

    comment = db.get(Comment, job.comment_id) if job.comment_id else None
    outcome = _apply_lease_recovery(job, comment, now)
    logger.info(
        "job_manual_recover",
        extra={
            "job_id": job_id,
            "comment_id": job.comment_id,
            "operator": operator or "system",
            "outcome": outcome,
            "attempts": job.attempts,
        },
    )
    return job


def requeue_batch_jobs(
    db: Session,
    batch_id: str,
    *,
    status: str = JobStatus.FAILED.value,
    operator: str | None = None,
) -> int:
    """Reset jobs in a batch matching ``status`` back to pending. Returns count."""
    if status != JobStatus.FAILED.value:
        raise ValueError("requeue_batch currently only supports status=failed")

    jobs = db.execute(
        select(Job).where(Job.batch_id == batch_id, Job.status == status)
    ).scalars().all()
    count = 0
    for job in jobs:
        retry_job(db, job.id, operator=operator)
        count += 1
    return count
