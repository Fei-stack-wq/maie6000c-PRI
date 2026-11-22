"""Transactional task lifecycle. Every final write is fenced by its original claim."""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.orm import Session

from services.common.models import (
    AnalysisRun, AnalysisStatus, Comment, CommentIssue, Issue, IssueStatus,
    Job, JobStatus, LinkOrigin, LinkStatus, utcnow,
)
from services.common.schemas import ExistingIssueRef, GroupingAction, GroupSuggestionResult
from services.worker.app.analysis import (
    AnalysisInput,
    VerifiedAnalysis,
    call_suggest_groups,
    load_analysis_input,
)
from services.worker.app.metrics import JOB_EVENTS
from services.worker.app.policy import Failure, calculate_retry_delay, should_retry
from services.worker.app.settings import WorkerSettings

logger = logging.getLogger("services.worker.jobs")


def aware(value: datetime) -> datetime:
    # SQLite drops timezone information; PostgreSQL retains it.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass(frozen=True)
class JobClaim:
    id: int
    comment_id: str
    claimed_at: datetime
    attempts: int


def lock_owned_job(db: Session, claim: JobClaim, now: datetime) -> Job | None:
    job = db.execute(
        select(Job).where(Job.id == claim.id).with_for_update()
    ).scalar_one_or_none()
    owned = (
        job is not None and job.status == JobStatus.CLAIMED.value
        and job.claimed_at is not None and aware(job.claimed_at) == aware(claim.claimed_at)
        and job.attempts == claim.attempts and job.lease_expires_at is not None
        and aware(job.lease_expires_at) > aware(now)
    )
    return job if owned else None


def claim_next_pending_job(
    db: Session, settings: WorkerSettings, now: datetime | None = None,
) -> JobClaim | None:
    now = now or utcnow()
    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.PENDING.value, Job.attempts < Job.max_attempts,
            or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now),
        )
        .order_by(Job.created_at, Job.id).with_for_update(skip_locked=True).limit(1)
    )
    job = db.execute(stmt).scalar_one_or_none()
    if job is None:
        return None
    comment = db.execute(
        select(Comment).where(Comment.id == job.comment_id).with_for_update()
    ).scalar_one_or_none()
    if comment is None:
        job.status = JobStatus.FAILED.value
        job.error_code = "comment_not_found"
        job.error = "Comment no longer exists."
        job.completed_at = now
        db.commit()
        return None
    job.status = JobStatus.CLAIMED.value
    job.claimed_at = now
    job.lease_expires_at = now + timedelta(seconds=settings.lease_seconds)
    job.next_attempt_at = None
    job.completed_at = None
    job.attempts += 1
    comment.analysis_status = AnalysisStatus.ANALYZING.value
    claim = JobClaim(job.id, job.comment_id, now, job.attempts)
    db.commit()
    JOB_EVENTS.labels("claimed").inc()
    logger.info("job_claimed", extra={"job_id": claim.id, "attempt": claim.attempts})
    return claim


def load_input_for_claim(db: Session, claim: JobClaim) -> AnalysisInput | None:
    if lock_owned_job(db, claim, utcnow()) is None:
        return None
    return load_analysis_input(db, claim.comment_id)


def _clear_claim(job: Job) -> None:
    job.claimed_at = None
    job.lease_expires_at = None


def _supersede_suggestions(db: Session, comment_id: str) -> None:
    db.execute(
        update(CommentIssue).where(
            CommentIssue.comment_id == comment_id,
            CommentIssue.origin == LinkOrigin.AI.value,
            CommentIssue.status == LinkStatus.SUGGESTED.value,
            CommentIssue.decided_at.is_(None), CommentIssue.decided_by.is_(None),
            CommentIssue.superseded_at.is_(None),
        ).values(superseded_at=utcnow())
    )


def _record_run(
    db: Session, claim: JobClaim, snapshot: AnalysisInput, status: str,
    latency_ms: int, verified: VerifiedAnalysis | None = None, error_code: str | None = None,
) -> AnalysisRun:
    result = verified.result if verified else None
    output = result.model_dump(mode="json") if result else {}
    output["_worker"] = {
        "attempt": claim.attempts, "claimed_at": claim.claimed_at.isoformat(),
        "input_revision_id": snapshot.revision_id,
    }
    if verified:
        output["_worker"]["invalid_evidence_count"] = verified.invalid_evidence_count
    run = AnalysisRun(
        job_id=claim.id, comment_id=snapshot.comment_id,
        model_version=result.model_version if result else "unknown",
        prompt_version=result.prompt_version if result else "unknown",
        category_version=result.category_version if result else "unknown",
        input_hash=snapshot.input_hash, output_json=output, status=status,
        error_code=error_code, latency_ms=latency_ms,
    )
    db.add(run)
    db.flush()
    return run


def _requeue_changed_input(db: Session, job: Job, comment: Comment) -> None:
    # A different input deserves its own retry budget. The cleared claim fences the old input.
    job.status = JobStatus.PENDING.value
    job.attempts = 0
    job.next_attempt_at = utcnow()
    job.completed_at = None
    job.error_code = "input_changed"
    job.error = "Comment changed during analysis; queued the current input."
    job.batch_id = comment.batch_id
    _clear_claim(job)
    comment.analysis_status = AnalysisStatus.QUEUED.value
    comment.has_issue = None
    comment.current_analysis_run_id = None
    comment.analysis_error = None
    _supersede_suggestions(db, comment.id)


def _group_lock(db: Session, snapshot: AnalysisInput, category: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        raw = repr((snapshot.platform, snapshot.shop_id, snapshot.product_id, category))
        key = int.from_bytes(hashlib.sha256(raw.encode()).digest()[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def _list_active_issues(
    db: Session, snapshot: AnalysisInput, category_id: str,
) -> list[Issue]:
    return list(db.execute(
        select(Issue).where(
            Issue.platform == snapshot.platform, Issue.shop_id == snapshot.shop_id,
            Issue.product_id == snapshot.product_id,
            Issue.category_id == category_id,
            Issue.merged_into_id.is_(None),
            Issue.status.in_([IssueStatus.PROPOSED.value, IssueStatus.CONFIRMED.value]),
        ).order_by(Issue.created_at, Issue.id).with_for_update()
    ).scalars().all())


def _category_baseline_pick(candidates: list[Issue]) -> Issue | None:
    """Reuse the earliest active group in this category (pre-semantic behaviour)."""
    return candidates[0] if candidates else None


def _request_group_suggestion(
    snapshot: AnalysisInput,
    category_id: str,
    candidate_text: str,
    candidates: list[Issue],
    ai_service_url: str | None,
    timeout: float,
) -> GroupSuggestionResult | None:
    if not ai_service_url or not candidates:
        return None
    refs = [
        ExistingIssueRef(
            id=issue.id,
            title=issue.title or "",
            description=issue.description or "",
        )
        for issue in candidates
    ]
    try:
        return call_suggest_groups(
            product_id=snapshot.product_id,
            category_id=category_id,
            candidate_text=candidate_text,
            existing_issues=refs,
            url=ai_service_url,
            timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001 - grouping hint must not fail the job
        logger.warning(
            "suggest_groups_failed",
            extra={
                "product_id": snapshot.product_id,
                "category_id": category_id,
                "exception_type": type(exc).__name__,
            },
        )
        JOB_EVENTS.labels("suggest_groups_failed").inc()
        return None


def _select_issue_for_extracted(
    db: Session,
    snapshot: AnalysisInput,
    category_id: str,
    candidate_text: str,
    ai_service_url: str | None,
    timeout: float,
) -> tuple[Issue, float | None]:
    candidates = _list_active_issues(db, snapshot, category_id)
    suggestion = _request_group_suggestion(
        snapshot, category_id, candidate_text, candidates, ai_service_url, timeout,
    )
    by_id = {issue.id: issue for issue in candidates}

    if suggestion is not None:
        if (
            suggestion.action == GroupingAction.LINK_EXISTING
            and suggestion.issue_id
            and suggestion.issue_id in by_id
        ):
            return by_id[suggestion.issue_id], suggestion.similarity
        if suggestion.action == GroupingAction.CREATE_NEW:
            issue = Issue(
                platform=snapshot.platform, shop_id=snapshot.shop_id,
                product_id=snapshot.product_id, category_id=category_id,
                title=candidate_text[:120], description=candidate_text,
                status=IssueStatus.PROPOSED.value, created_by="ai",
            )
            db.add(issue)
            db.flush()
            return issue, suggestion.similarity
        logger.warning(
            "suggest_groups_invalid_issue_id",
            extra={"issue_id": suggestion.issue_id, "category_id": category_id},
        )

    baseline = _category_baseline_pick(candidates)
    if baseline is not None:
        return baseline, None
    issue = Issue(
        platform=snapshot.platform, shop_id=snapshot.shop_id,
        product_id=snapshot.product_id, category_id=category_id,
        title=candidate_text[:120], description=candidate_text,
        status=IssueStatus.PROPOSED.value, created_by="ai",
    )
    db.add(issue)
    db.flush()
    return issue, None


def save_issue_links(
    db: Session,
    snapshot: AnalysisInput,
    verified: VerifiedAnalysis,
    run_id: int,
    ai_service_url: str | None = None,
    request_timeout_seconds: float = 20.0,
) -> None:
    # Sort lock acquisition to avoid cross-category deadlocks between comments.
    for category in sorted({entry.issue.category_id for entry in verified.issues}):
        _group_lock(db, snapshot, category)
    _supersede_suggestions(db, snapshot.comment_id)
    seen = set()
    for entry in verified.issues:
        extracted = entry.issue
        candidate_text = extracted.description or extracted.evidence_text
        issue, similarity = _select_issue_for_extracted(
            db, snapshot, extracted.category_id, candidate_text,
            ai_service_url, request_timeout_seconds,
        )
        if issue.id in seen:
            continue
        seen.add(issue.id)
        link = db.execute(
            select(CommentIssue).where(
                CommentIssue.comment_id == snapshot.comment_id, CommentIssue.issue_id == issue.id,
            ).with_for_update()
        ).scalar_one_or_none()
        if link is not None and (
            link.status in (LinkStatus.ACCEPTED.value, LinkStatus.REJECTED.value)
            or link.origin == LinkOrigin.HUMAN.value
            or link.decided_at is not None or link.decided_by is not None
        ):
            continue
        if link is None:
            link = CommentIssue(comment_id=snapshot.comment_id, issue_id=issue.id)
            db.add(link)
        link.status = LinkStatus.SUGGESTED.value
        link.origin = LinkOrigin.AI.value
        link.evidence_text = extracted.evidence_text
        link.evidence_start = entry.start
        link.evidence_end = entry.end
        link.evidence_verified = True
        link.similarity = similarity
        link.analysis_run_id = run_id
        link.comment_version = snapshot.comment_version
        link.superseded_at = None
        db.flush()


def complete_job(
    db: Session, claim: JobClaim, snapshot: AnalysisInput,
    verified: VerifiedAnalysis, latency_ms: int, now: datetime | None = None,
    ai_service_url: str | None = None,
    request_timeout_seconds: float = 20.0,
) -> str:
    job = lock_owned_job(db, claim, now or utcnow())
    if job is None:
        return "stale"
    current = load_analysis_input(db, claim.comment_id)
    comment = db.get(Comment, claim.comment_id)
    if current != snapshot:
        _record_run(db, claim, snapshot, "failed", latency_ms, verified, "input_changed")
        _requeue_changed_input(db, job, comment)
        db.commit()
        return "input_changed"
    run = _record_run(db, claim, snapshot, "succeeded", latency_ms, verified)
    save_issue_links(
        db, snapshot, verified, run.id,
        ai_service_url=ai_service_url,
        request_timeout_seconds=request_timeout_seconds,
    )
    comment.analysis_status = AnalysisStatus.ANALYZED.value
    comment.has_issue = verified.has_issue
    comment.current_analysis_run_id = run.id
    comment.analysis_error = None
    job.status = JobStatus.COMPLETED.value
    job.completed_at = now or utcnow()
    job.error = None
    job.error_code = None
    job.next_attempt_at = None
    _clear_claim(job)
    db.commit()
    return "completed"


def handle_job_failure(
    db: Session, claim: JobClaim, snapshot: AnalysisInput | None,
    failure: Failure, settings: WorkerSettings, latency_ms: int = 0,
    now: datetime | None = None,
) -> str:
    now = now or utcnow()
    job = lock_owned_job(db, claim, now)
    if job is None:
        return "stale"
    comment = db.execute(
        select(Comment).where(Comment.id == claim.comment_id).with_for_update()
    ).scalar_one_or_none()
    if comment is None:
        job.status = JobStatus.FAILED.value
        job.error_code = "comment_not_found"
        job.error = "Comment no longer exists."
        job.completed_at = now
        _clear_claim(job)
        db.commit()
        return "failed"
    current = load_analysis_input(db, claim.comment_id)
    if snapshot is not None:
        _record_run(db, claim, snapshot, "failed", latency_ms, error_code=failure.code)
        if current != snapshot:
            _requeue_changed_input(db, job, comment)
            db.commit()
            return "input_changed"
    retry = should_retry(failure, job.attempts, job.max_attempts)
    job.error_code = failure.code
    job.error = failure.message
    job.status = JobStatus.PENDING.value if retry else JobStatus.FAILED.value
    job.next_attempt_at = (
        now + timedelta(seconds=calculate_retry_delay(job.attempts, settings)) if retry else None
    )
    job.completed_at = None if retry else now
    _clear_claim(job)
    comment.analysis_status = (
        AnalysisStatus.QUEUED.value if retry else AnalysisStatus.FAILED.value
    )
    comment.analysis_error = failure.message
    db.commit()
    return "retry_scheduled" if retry else "failed"


def recover_stale_jobs(
    db: Session, settings: WorkerSettings, now: datetime | None = None,
) -> int:
    now = now or utcnow()
    stale = db.execute(
        select(Job).where(or_(
            and_(
                Job.status == JobStatus.CLAIMED.value, Job.lease_expires_at <= now,
            ),
            and_(Job.status == JobStatus.PENDING.value, Job.attempts >= Job.max_attempts),
        )).order_by(Job.id).with_for_update(skip_locked=True).limit(settings.recovery_limit)
    ).scalars().all()
    for job in stale:
        comment = db.execute(
            select(Comment).where(Comment.id == job.comment_id).with_for_update()
        ).scalar_one_or_none()
        if (comment is not None and job.status == JobStatus.CLAIMED.value
                and comment.analysis_status == AnalysisStatus.QUEUED.value):
            _requeue_changed_input(db, job, comment)
            continue
        retry = job.attempts < job.max_attempts and comment is not None
        job.status = JobStatus.PENDING.value if retry else JobStatus.FAILED.value
        job.next_attempt_at = now if retry else None
        job.completed_at = None if retry else now
        job.error_code = "lease_expired"
        job.error = "Processing lease expired."
        _clear_claim(job)
        if comment:
            comment.analysis_status = (
                AnalysisStatus.QUEUED.value if retry else AnalysisStatus.FAILED.value
            )
            comment.analysis_error = job.error
    db.commit()
    if stale:
        JOB_EVENTS.labels("recovered").inc(len(stale))
        logger.info("jobs_recovered", extra={"count": len(stale)})
    return len(stale)
