"""Review-management API (R1 scope: ingestion, comments, batches, read models).

Endpoints implemented here are the R1 slice of ``docs/architecture.md``
§8.  Issue review actions (R4) and stats enrichment (R4) are follow-up PRs; the
read endpoints are present so the static UI and the team can work in parallel.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from time import perf_counter

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from services.api.app.ingestion import ingest_comments, parse_csv, parse_normalized
from services.common.config import configure_logging
from services.common.db import get_db
from services.common.models import (
    AnalysisRun,
    AnalysisStatus,
    BatchRow,
    BatchStatus,
    Comment,
    CommentIssue,
    CommentRevision,
    IngestionBatch,
    Issue,
    IssueAction,
    Job,
    JobStatus,
    utcnow,
)
from services.common.schemas import (
    AnalysisJobRead,
    AnalysisRunRead,
    BatchCreateResponse,
    BatchErrorRead,
    BatchProgressRead,
    BatchUploadRequest,
    CommentDetailRead,
    CommentIssueRead,
    CommentRead,
    CommentRevisionRead,
    HealthResponse,
    IssueActionRead,
    IssueDetailRead,
    IssueRead,
    QueryScope,
    StatsSummaryRead,
)

configure_logging()
logger = logging.getLogger("services.api.main")

app = FastAPI(
    title="Review Management API",
    description="商品评论管理与重复问题发现系统（单平台初版）",
    version="0.2.0",
)

HTTP_REQUESTS = Counter(
    "api_http_requests_total",
    "Total API HTTP requests",
    ["method", "path", "status"],
)
HTTP_REQUEST_LATENCY = Histogram(
    "api_http_request_duration_seconds",
    "API request duration in seconds",
    ["method", "path"],
)
BATCHES_RECEIVED = Counter("api_batches_received_total", "Total review batches received")
COMMENTS_INGESTED = Counter("api_comments_ingested_total", "Total comments accepted")
JOBS_CREATED = Counter("api_jobs_created_total", "Total analysis jobs created")

FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")


def _scope(
    product_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> QueryScope:
    return QueryScope(
        product_id=product_id,
        date_from=date_from,
        date_to=date_to,
        as_of=utcnow(),
    )


def _resolve_batch_status(batch: IngestionBatch, pending: int, processing: int, failed: int) -> str:
    """Derive the presentation status; only import stages are persisted (§4.2)."""
    if batch.status == BatchStatus.REJECTED.value:
        return BatchStatus.REJECTED.value
    if pending or processing:
        return batch.status
    if failed or batch.invalid_rows:
        return BatchStatus.PARTIALLY_FAILED.value
    return BatchStatus.COMPLETED.value


def _batch_progress(db: Session, batch: IngestionBatch) -> BatchProgressRead:
    status_rows = db.execute(
        select(Job.status, func.count()).where(Job.batch_id == batch.id).group_by(Job.status)
    ).all()
    job_status = {status: count for status, count in status_rows}
    job_count = sum(job_status.values())

    comment_rows = db.execute(
        select(Comment.analysis_status, func.count())
        .where(Comment.batch_id == batch.id)
        .group_by(Comment.analysis_status)
    ).all()
    comment_status = {status: count for status, count in comment_rows}
    analyzed = comment_status.get(AnalysisStatus.ANALYZED.value, 0)
    failed = comment_status.get(AnalysisStatus.FAILED.value, 0)
    pending = job_status.get(JobStatus.PENDING.value, 0)
    processing = job_status.get(JobStatus.CLAIMED.value, 0)
    coverage = round(analyzed / batch.accepted_rows, 4) if batch.accepted_rows else None

    return BatchProgressRead(
        batch_id=batch.id,
        status=_resolve_batch_status(batch, pending, processing, failed),
        job_count=job_count,
        analyzed_rows=analyzed,
        failed_rows=failed,
        pending_rows=pending,
        processing_rows=processing,
        analysis_coverage=coverage,
        scope=_scope(),
    )


def _batch_response(batch: IngestionBatch) -> BatchCreateResponse:
    return BatchCreateResponse(
        batch_id=batch.id,
        status=BatchStatus(batch.status),
        declared_rows=batch.declared_rows,
        accepted_rows=batch.accepted_rows,
        duplicate_rows=batch.duplicate_rows,
        invalid_rows=batch.invalid_rows,
    )


def _get_batch(db: Session, batch_id: str) -> IngestionBatch:
    batch = db.get(IngestionBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail={"code": "batch_not_found"})
    return batch


def _issue_counts(db: Session, issue_ids: list[str]) -> dict[str, dict[str, int]]:
    if not issue_ids:
        return {}
    rows = db.execute(
        select(CommentIssue.issue_id, CommentIssue.status, func.count())
        .where(CommentIssue.issue_id.in_(issue_ids))
        .group_by(CommentIssue.issue_id, CommentIssue.status)
    ).all()
    counts: dict[str, dict[str, int]] = {issue_id: {} for issue_id in issue_ids}
    for issue_id, status, count in rows:
        counts[issue_id][status] = count
    return counts


def _issue_read(issue: Issue, counts: dict[str, int]) -> IssueRead:
    data = IssueRead.model_validate(issue)
    data.suggested_count = counts.get("suggested", 0)
    data.accepted_count = counts.get("accepted", 0)
    return data


def _comment_issue_read(link: CommentIssue, comment_body: str | None = None) -> CommentIssueRead:
    data = CommentIssueRead.model_validate(link)
    data.comment_body = comment_body
    return data


# ---------------------------------------------------------------------------
# Middleware + health
# ---------------------------------------------------------------------------
@app.middleware("http")
async def observe_requests(request: Request, call_next):
    start = perf_counter()
    response: Response | None = None
    try:
        response = await call_next(request)
        return response
    finally:
        duration = perf_counter() - start
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        status = str(response.status_code) if response is not None else "500"
        HTTP_REQUESTS.labels(request.method, path, status).inc()
        HTTP_REQUEST_LATENCY.labels(request.method, path).observe(duration)
        logger.info(
            "request_completed",
            extra={
                "method": request.method,
                "path": path,
                "status_code": status,
                "duration_seconds": round(duration, 4),
            },
        )


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(service="api", status="ok")


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(service="api", status="ok")


@app.get("/health/ready", response_model=HealthResponse)
def health_ready(db: Session = Depends(get_db)) -> HealthResponse:
    db.execute(text("SELECT 1"))
    return HealthResponse(service="api", status="ok")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Batches (ingestion)
# ---------------------------------------------------------------------------
@app.post("/review-batches", response_model=BatchCreateResponse, status_code=202)
def create_batch(
    payload: BatchUploadRequest,
    db: Session = Depends(get_db),
) -> BatchCreateResponse:
    if payload.idempotency_key:
        existing = db.execute(
            select(IngestionBatch).where(
                IngestionBatch.idempotency_key == payload.idempotency_key
            )
        ).scalars().first()
        if existing is not None:
            logger.info("batch_idempotent_replay", extra={"batch_id": existing.id})
            return _batch_response(existing)

    batch = IngestionBatch(
        platform=payload.platform,
        source_type=payload.source_type.value,
        file_ref=payload.filename,
        idempotency_key=payload.idempotency_key,
        status=BatchStatus.RECEIVED.value,
    )
    db.add(batch)
    db.flush()

    batch.status = BatchStatus.VALIDATING.value
    if payload.csv_text is not None:
        parsed = parse_csv(payload.csv_text, payload.platform)
    else:
        parsed = parse_normalized(payload.comments or [], payload.platform)

    for error in parsed.errors:
        db.add(
            BatchRow(
                batch_id=batch.id,
                row_number=error.row_number,
                column_name=error.column_name,
                code=error.code,
                message=error.message,
            )
        )
    batch.declared_rows = parsed.declared_rows

    if parsed.fatal:
        batch.status = BatchStatus.REJECTED.value
        batch.invalid_rows = max(1, parsed.declared_rows or len(parsed.errors))
        batch.finished_at = utcnow()
        db.commit()
        raise HTTPException(
            status_code=422,
            detail={
                "code": "batch_rejected",
                "batch_id": batch.id,
                "errors": [
                    {
                        "row_number": error.row_number,
                        "column_name": error.column_name,
                        "code": error.code,
                        "message": error.message,
                    }
                    for error in parsed.errors
                ],
            },
        )

    counts = ingest_comments(db, batch, parsed.comments)
    batch.accepted_rows = counts.accepted_rows
    batch.duplicate_rows = counts.duplicate_rows
    batch.invalid_rows = len(
        {error.row_number for error in parsed.errors if error.code not in ("unknown_columns",)}
    )
    batch.status = BatchStatus.IMPORTED.value
    batch.finished_at = utcnow()
    db.commit()
    db.refresh(batch)

    BATCHES_RECEIVED.inc()
    COMMENTS_INGESTED.inc(counts.accepted_rows)
    JOBS_CREATED.inc(counts.job_count)
    logger.info(
        "batch_imported",
        extra={
            "batch_id": batch.id,
            "accepted_rows": counts.accepted_rows,
            "duplicate_rows": counts.duplicate_rows,
            "invalid_rows": batch.invalid_rows,
        },
    )
    response = _batch_response(batch)
    response.job_count = counts.job_count
    return response


@app.get("/review-batches/{batch_id}", response_model=BatchProgressRead)
def read_batch_progress(batch_id: str, db: Session = Depends(get_db)) -> BatchProgressRead:
    batch = _get_batch(db, batch_id)
    return _batch_progress(db, batch)


@app.get("/review-batches/{batch_id}/errors", response_model=list[BatchErrorRead])
def read_batch_errors(batch_id: str, db: Session = Depends(get_db)) -> list[BatchErrorRead]:
    batch = _get_batch(db, batch_id)
    rows = db.execute(
        select(BatchRow)
        .where(BatchRow.batch_id == batch.id)
        .order_by(BatchRow.row_number.asc())
    ).scalars().all()
    return [BatchErrorRead.model_validate(row) for row in rows]


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------
@app.get("/comments", response_model=list[CommentRead])
def list_comments(
    product_id: str | None = None,
    analysis_status: str | None = None,
    has_issue: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[CommentRead]:
    stmt = select(Comment).order_by(Comment.created_at.desc()).limit(limit).offset(offset)
    if product_id:
        stmt = stmt.where(Comment.product_id == product_id)
    if analysis_status:
        stmt = stmt.where(Comment.analysis_status == analysis_status)
    if has_issue:
        stmt = stmt.where(Comment.has_issue == has_issue)
    comments = db.execute(stmt).scalars().all()
    return [CommentRead.model_validate(comment) for comment in comments]


@app.get("/comments/{comment_id}", response_model=CommentDetailRead)
def read_comment(comment_id: str, db: Session = Depends(get_db)) -> CommentDetailRead:
    comment = db.get(Comment, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail={"code": "comment_not_found"})

    detail = CommentDetailRead.model_validate(comment)
    links = db.execute(
        select(CommentIssue).where(CommentIssue.comment_id == comment.id)
    ).scalars().all()
    detail.issues = [_comment_issue_read(link, comment.body) for link in links]

    revisions = db.execute(
        select(CommentRevision)
        .where(CommentRevision.comment_id == comment.id)
        .order_by(CommentRevision.version.asc())
    ).scalars().all()
    detail.revisions = [CommentRevisionRead.model_validate(rev) for rev in revisions]

    latest_run = db.execute(
        select(AnalysisRun)
        .where(AnalysisRun.comment_id == comment.id)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    ).scalars().first()
    detail.latest_analysis_run = (
        AnalysisRunRead.model_validate(latest_run) if latest_run is not None else None
    )
    return detail


# ---------------------------------------------------------------------------
# Issues (read-only for the current UI; actions belong to R4)
# ---------------------------------------------------------------------------
@app.get("/issues", response_model=list[IssueRead])
def list_issues(
    product_id: str | None = None,
    status: str | None = None,
    category_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[IssueRead]:
    stmt = select(Issue).order_by(Issue.updated_at.desc()).limit(limit).offset(offset)
    if product_id:
        stmt = stmt.where(Issue.product_id == product_id)
    if status:
        stmt = stmt.where(Issue.status == status)
    if category_id:
        stmt = stmt.where(Issue.category_id == category_id)
    issues = db.execute(stmt).scalars().all()
    counts = _issue_counts(db, [issue.id for issue in issues])
    return [_issue_read(issue, counts.get(issue.id, {})) for issue in issues]


@app.get("/issues/{issue_id}", response_model=IssueDetailRead)
def read_issue(issue_id: str, db: Session = Depends(get_db)) -> IssueDetailRead:
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail={"code": "issue_not_found"})
    counts = _issue_counts(db, [issue.id]).get(issue.id, {})
    detail = IssueDetailRead.model_validate(issue)
    detail.suggested_count = counts.get("suggested", 0)
    detail.accepted_count = counts.get("accepted", 0)

    links = db.execute(
        select(CommentIssue).where(CommentIssue.issue_id == issue.id)
    ).scalars().all()
    bodies = {
        comment.id: comment.body
        for comment in db.execute(
            select(Comment).where(Comment.id.in_([link.comment_id for link in links]))
        ).scalars().all()
    } if links else {}
    detail.links = [_comment_issue_read(link, bodies.get(link.comment_id)) for link in links]

    actions = db.execute(
        select(IssueAction)
        .where(IssueAction.issue_id == issue.id)
        .order_by(IssueAction.created_at.asc())
    ).scalars().all()
    detail.actions = [IssueActionRead.model_validate(action) for action in actions]
    return detail


# ---------------------------------------------------------------------------
# Jobs + stats
# ---------------------------------------------------------------------------
@app.get("/jobs/{job_id}", response_model=AnalysisJobRead)
def read_job(job_id: int, db: Session = Depends(get_db)) -> AnalysisJobRead:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail={"code": "job_not_found"})
    return AnalysisJobRead.model_validate(job)


@app.post("/jobs/{job_id}/retry", response_model=AnalysisJobRead)
def retry_job_endpoint(
    job_id: int,
    operator: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
) -> AnalysisJobRead:
    """Thin R2 route: state machine lives in ``services.worker.app.lifecycle``."""
    from services.worker.app.lifecycle import JobConflictError, JobNotFoundError, retry_job

    try:
        job = retry_job(db, job_id, operator=operator or "api")
        db.commit()
        db.refresh(job)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "job_not_found"}) from None
    except JobConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_job_transition", "message": str(exc), "status": exc.status},
        ) from None
    return AnalysisJobRead.model_validate(job)


@app.post("/jobs/{job_id}/recover", response_model=AnalysisJobRead)
def recover_job_endpoint(
    job_id: int,
    operator: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
) -> AnalysisJobRead:
    """Thin R2 route: recover lease-expired claimed jobs."""
    from services.worker.app.lifecycle import JobConflictError, JobNotFoundError, recover_job

    try:
        job = recover_job(db, job_id, operator=operator or "api")
        db.commit()
        db.refresh(job)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail={"code": "job_not_found"}) from None
    except JobConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_job_transition", "message": str(exc), "status": exc.status},
        ) from None
    return AnalysisJobRead.model_validate(job)


@app.get("/stats/summary", response_model=StatsSummaryRead)
def read_stats(
    product_id: str | None = None,
    db: Session = Depends(get_db),
) -> StatsSummaryRead:
    comment_counts = dict(
        db.execute(
            select(Comment.analysis_status, func.count())
            .where(Comment.product_id == product_id if product_id else text("1=1"))
            .group_by(Comment.analysis_status)
        ).all()
    )

    def _issue_link_count(status: str, origin: str | None = None) -> int:
        stmt = (
            select(func.count(func.distinct(CommentIssue.comment_id)))
            .select_from(CommentIssue)
            .join(Issue, Issue.id == CommentIssue.issue_id)
            .where(CommentIssue.status == status)
        )
        if origin:
            stmt = stmt.where(CommentIssue.origin == origin)
        if product_id:
            stmt = stmt.where(Issue.product_id == product_id)
        return db.execute(stmt).scalar() or 0

    analyzed = comment_counts.get(AnalysisStatus.ANALYZED.value, 0)
    received = sum(comment_counts.values())
    return StatsSummaryRead(
        scope=_scope(product_id),
        received_rows=received,
        analyzed_rows=analyzed,
        failed_rows=comment_counts.get(AnalysisStatus.FAILED.value, 0),
        processing_rows=received - analyzed - comment_counts.get(AnalysisStatus.FAILED.value, 0),
        issue_mention_count=_issue_link_count("accepted"),
        ai_suggested_count=_issue_link_count("suggested", "ai"),
        human_accepted_count=_issue_link_count("accepted"),
        analysis_coverage=round(analyzed / received, 4) if received else None,
    )
