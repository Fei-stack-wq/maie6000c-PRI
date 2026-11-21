"""All decision state and audit writes commit together under the comment lock."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.reviews.rules import (
    blocked_reason, body_hash, digest, evidence_valid, review_token,
)
from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction, utcnow
from services.common.schemas import ReviewDecisionRead, ReviewDecisionRequest


def conflict(code: str):
    raise HTTPException(status_code=409, detail={"code": code})


def receipt(db: Session, request_id: str, request_hash: str, model=ReviewDecisionRead):
    action = db.execute(select(IssueAction).where(
        IssueAction.request_id == request_id,
    )).scalar_one_or_none()
    if action is None:
        return None
    if action.request_hash != request_hash:
        conflict("idempotency_conflict")
    return model.model_validate(action.result_json)


def decide(db: Session, link_id: int, payload: ReviewDecisionRequest, operator: str):
    request_data = payload.model_dump(mode="json")
    revising = payload.mode == "revise"
    if not revising:
        # Keep first-stage persisted idempotency receipts replayable after this upgrade.
        request_data.pop("mode")
    request_hash = digest({"link_id": link_id, "operator": operator, **request_data})
    saved = receipt(db, payload.request_id, request_hash)
    if saved:
        return saved
    # Read only the immutable parent ID before locking. No ORM link is cached here.
    comment_id = db.execute(select(CommentIssue.comment_id).where(
        CommentIssue.id == link_id,
    )).scalar_one_or_none()
    if comment_id is None:
        raise HTTPException(404, detail={"code": "link_not_found"})
    # Worker/import also lock Comment before writing its links. Never acquire Job locks here.
    comment = db.execute(select(Comment).where(
        Comment.id == comment_id,
    ).with_for_update()).scalar_one()
    saved = receipt(db, payload.request_id, request_hash)
    if saved:
        return saved
    link = db.execute(select(CommentIssue).where(
        CommentIssue.id == link_id,
    ).with_for_update()).scalar_one()
    issue = db.execute(select(Issue).where(
        Issue.id == link.issue_id,
    ).with_for_update()).scalar_one()
    run = db.get(AnalysisRun, link.analysis_run_id) if link.analysis_run_id else None
    if payload.expected_token != review_token(link, comment, issue):
        conflict("review_changed")
    reason = blocked_reason(link, comment, issue, run, revising=revising)
    if reason:
        conflict(reason)
    next_status = "accepted" if payload.decision == "accept" else "rejected"
    if revising and next_status == link.status:
        conflict("decision_unchanged")
    if payload.decision == "accept" and not evidence_valid(link, comment):
        conflict("invalid_evidence")
    before = {
        "status": link.status, "review_version": link.review_version,
        "decided_by": link.decided_by,
        "decided_at": link.decided_at.isoformat() if link.decided_at else None,
    }
    previous_action_id = db.execute(select(IssueAction.id).where(
        IssueAction.comment_issue_id == link.id,
    ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
    now = utcnow()
    link.status = next_status
    link.decided_by, link.decided_at = operator, now
    link.review_version += 1
    action = IssueAction(
        issue_id=issue.id, comment_issue_id=link.id,
        action="change" if revising else payload.decision.value,
        from_status=before["status"], to_status=link.status,
        operator=operator, note=payload.note, request_id=payload.request_id,
        request_hash=request_hash,
        payload_json={
            "operation": "revise_decision" if revising else "initial_decision",
            "previous_action_id": previous_action_id,
            "before": before, "after": {
                "status": link.status, "review_version": link.review_version,
                "decided_by": operator, "decided_at": now.isoformat(),
            },
            "snapshot": {
                "comment_id": comment.id, "body": comment.body,
                "body_hash": body_hash(comment.body), "comment_version": link.comment_version,
                "analysis_run_id": link.analysis_run_id, "issue_id": issue.id,
                "issue_version": issue.version, "issue_title": issue.title,
                "category_id": issue.category_id, "evidence_text": link.evidence_text,
                "evidence_start": link.evidence_start, "evidence_end": link.evidence_end,
            },
        },
    )
    db.add(action)
    try:
        db.flush()
        result = ReviewDecisionRead(
            action_id=action.id, request_id=payload.request_id, link_id=link.id,
            status=link.status, review_version=link.review_version,
            operator=operator, decided_at=now,
        )
        action.result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        # A globally duplicated request ID on another comment is also safe.
        saved = receipt(db, payload.request_id, request_hash)
        if saved:
            return saved
        raise
    except Exception:
        db.rollback()
        raise
