"""Batch lifecycle. Stop and worker completion serialize on the same batch row."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, or_, select, update

from services.common.db import get_db
from services.common.models import (
    AnalysisRun,
    BatchRow,
    Comment,
    CommentIssue,
    CommentRevision,
    IngestionBatch,
    Issue,
    IssueAction,
    Job,
    utcnow,
)

router = APIRouter()


def lock_batch(db, identity, *, include_deleted=False):
    batch = db.scalar(
        select(IngestionBatch)
        .where(IngestionBatch.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if batch is None or (batch.deleted_at is not None and not include_deleted):
        raise HTTPException(404, detail={"code": "batch_not_found"})
    return batch


def active_batch_ids():
    return select(IngestionBatch.id).where(IngestionBatch.deleted_at.is_(None))


def visible_comment():
    return or_(
        Comment.batch_id.is_(None),
        Comment.batch_id.in_(
            select(IngestionBatch.id)
            .where(
                IngestionBatch.deleted_at.is_(None),
                or_(IngestionBatch.stopped_at.is_(None), Comment.analysis_status == "analyzed"),
            )
            .correlate(Comment)
        ),
    )


def visible_issue():
    completed = select(CommentIssue.id).join(Comment).where(
        CommentIssue.issue_id == Issue.id, Comment.batch_id == Issue.batch_id,
        Comment.analysis_status == "analyzed",
    ).correlate(Issue).exists()
    return or_(Issue.batch_id.is_(None), Issue.batch_id.in_(
        select(IngestionBatch.id).where(IngestionBatch.deleted_at.is_(None),
            or_(IngestionBatch.stopped_at.is_(None), completed)).correlate(Issue)))


def cancel_unfinished(db, batch):
    # The batch lock is acquired before job/comment locks, matching Worker.
    ids = list(
        db.scalars(
            select(Job.id).where(Job.batch_id == batch.id).order_by(Job.id).with_for_update()
        )
    )
    unfinished = list(
        db.scalars(
            select(Comment.id)
            .where(
                Comment.batch_id == batch.id,
                Comment.analysis_status.notin_(["analyzed", "cancelled"]),
            )
            .order_by(Comment.id)
            .with_for_update()
        )
    )
    if unfinished:
        batch.stopped_at = batch.stopped_at or utcnow()
        batch.status = "stopped"
        db.execute(
            update(Job)
            .where(Job.id.in_(ids), Job.status != "completed")
            .values(
                status="cancelled",
                next_attempt_at=None,
                claimed_at=None,
                lease_expires_at=None,
                completed_at=utcnow(),
                error_code=None,
                error=None,
            )
        )
        db.execute(
            update(Comment)
            .where(Comment.id.in_(unfinished))
            .values(
                analysis_status="cancelled",
                has_issue=None,
                analysis_error=None,
                current_analysis_run_id=None,
            )
        )
    return len(unfinished)


@router.post("/review-batches/{batch_id}/stop")
def stop(batch_id: str, db=Depends(get_db)):
    batch = lock_batch(db, batch_id)
    count = cancel_unfinished(db, batch)
    db.commit()
    return {"batch_id": batch_id, "cancelled_now": count, "stopped_at": batch.stopped_at}


@router.post("/review-batches/{batch_id}/trash")
def trash(batch_id: str, db=Depends(get_db)):
    batch = lock_batch(db, batch_id, include_deleted=True)
    if batch.deleted_at is None:
        cancel_unfinished(db, batch)
        batch.deleted_at = utcnow()
    db.commit()
    return {"batch_id": batch_id, "deleted_at": batch.deleted_at}


@router.post("/review-batches/{batch_id}/restore")
def restore(batch_id: str, db=Depends(get_db)):
    batch = lock_batch(db, batch_id, include_deleted=True)
    batch.deleted_at = None
    if batch.grouping_policy_version == 0:
        from scripts.regroup_legacy import repair
        db.flush()
        repair(db, batch_id)
    db.commit()
    return {"batch_id": batch_id, "restored": True}


@router.delete("/review-batches/{batch_id}", status_code=204)
def purge(batch_id: str, permanent: bool = Query(False), db=Depends(get_db)):
    if not permanent:
        raise HTTPException(422, detail={"code": "permanent_confirmation_required"})
    batch = lock_batch(db, batch_id, include_deleted=True)
    cancel_unfinished(db, batch)
    comments = list(db.scalars(select(Comment.id).where(Comment.batch_id == batch_id)))
    groups = list(db.scalars(select(Issue.id).where(Issue.batch_id == batch_id)))
    # Refuse malformed historical cross-scope references rather than deleting
    # another upload's data through a foreign-key cascade.
    foreign = db.scalar(
        select(CommentIssue.id)
        .join(Comment)
        .join(Issue, Issue.id == CommentIssue.issue_id)
        .where(
            or_(
                (Comment.batch_id == batch_id) & (Issue.batch_id != batch_id),
                (Issue.batch_id == batch_id) & (Comment.batch_id != batch_id),
            )
        )
        .limit(1)
    )
    parent_conflict = db.scalar(
        select(Issue.id)
        .where(
            Issue.batch_id != batch_id,
            or_(Issue.merged_into_id.in_(groups), Issue.split_from_id.in_(groups)),
        )
        .limit(1)
    )
    if foreign is not None or parent_conflict is not None:
        raise HTTPException(409, detail={"code": "legacy_scope_conflict"})
    links = select(CommentIssue.id).where(
        or_(CommentIssue.comment_id.in_(comments), CommentIssue.issue_id.in_(groups))
    )
    db.execute(
        delete(IssueAction).where(
            or_(IssueAction.issue_id.in_(groups), IssueAction.comment_issue_id.in_(links))
        )
    )
    db.execute(
        delete(CommentIssue).where(
            or_(CommentIssue.comment_id.in_(comments), CommentIssue.issue_id.in_(groups))
        )
    )
    db.execute(delete(AnalysisRun).where(AnalysisRun.comment_id.in_(comments)))
    db.execute(delete(Job).where(or_(Job.batch_id == batch_id, Job.comment_id.in_(comments))))
    db.execute(delete(CommentRevision).where(CommentRevision.comment_id.in_(comments)))
    db.execute(delete(Comment).where(Comment.id.in_(comments)))
    db.execute(update(Issue).where(Issue.merged_into_id.in_(groups)).values(merged_into_id=None))
    db.execute(update(Issue).where(Issue.split_from_id.in_(groups)).values(split_from_id=None))
    db.execute(delete(Issue).where(Issue.id.in_(groups)))
    db.execute(delete(BatchRow).where(BatchRow.batch_id == batch_id))
    db.execute(
        update(IngestionBatch)
        .where(IngestionBatch.resubmitted_from_batch_id == batch_id)
        .values(resubmitted_from_batch_id=None)
    )
    db.execute(delete(IngestionBatch).where(IngestionBatch.id == batch_id))
    db.commit()
    return Response(status_code=204)


@router.get("/review-batches/{batch_id}/records")
def records(
    batch_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    from services.common.schemas import CommentRead

    batch = db.get(IngestionBatch, batch_id)
    if batch is None or batch.deleted_at is not None:
        raise HTTPException(404, detail={"code": "batch_not_found"})
    query = select(Comment).where(Comment.batch_id == batch_id)
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Comment.created_at, Comment.id).offset(offset).limit(limit))
    return {"total": total, "items": [CommentRead.model_validate(row) for row in rows]}


def guard_resource(request, db):
    """Trashed data is unavailable even through a saved detail/write URL."""
    parts = request.url.path.strip("/").split("/")
    if len(parts) < 2:
        return
    kind, identity = parts[:2]
    batch_id = None
    if kind == "review-batches":
        if request.method != "GET":
            return
        batch_id = identity
    elif kind in ("comments", "review-comments"):
        batch_id = db.scalar(select(Comment.batch_id).where(Comment.id == identity))
    elif kind in ("issues", "review-issues"):
        batch_id = db.scalar(select(Issue.batch_id).where(Issue.id == identity))
    elif kind == "comment-issues" and identity.isdigit():
        batch_id = db.scalar(
            select(Comment.batch_id).join(CommentIssue).where(CommentIssue.id == int(identity))
        )
    elif kind == "jobs" and identity.isdigit():
        batch_id = db.scalar(select(Job.batch_id).where(Job.id == int(identity)))
    if batch_id:
        batch = (
            db.scalar(
                select(IngestionBatch)
                .where(IngestionBatch.id == batch_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if request.method not in ("GET", "HEAD", "OPTIONS")
            else db.get(IngestionBatch, batch_id)
        )
        if batch and batch.deleted_at is not None:
            raise HTTPException(404, detail={"code": "batch_not_found"})
