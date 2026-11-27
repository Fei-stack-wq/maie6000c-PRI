"""Explicitly reassess a human-managed link against the current source text."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from services.api.app.reviews.commands import conflict, receipt
from services.api.app.reviews.history import evidence_body
from services.api.app.reviews.issue_workflow import issue_snapshot
from services.api.app.reviews.reassign import snapshot
from services.api.app.reviews.rules import (
    body_hash, digest, evidence_hash, recheck_blocked_reason, review_token,
)
from services.common.models import (
    AnalysisRun, Comment, CommentIssue, CommentRevision, Issue, IssueAction, utcnow,
)
from services.common.schemas import ReviewRecheckRead


def recheck(db, link_id, payload, operator):
    fingerprint = digest({"operation": "recheck_evidence", "link_id": link_id,
                          "operator": operator, **payload.model_dump(mode="json")})
    if saved := receipt(db, payload.request_id, fingerprint, ReviewRecheckRead):
        return saved
    comment_id = db.execute(select(CommentIssue.comment_id).where(
        CommentIssue.id == link_id,
    )).scalar_one_or_none()
    if comment_id is None:
        raise HTTPException(404, detail={"code": "link_not_found"})
    # Same order as ordinary review/import/Worker; never acquire a Job lock here.
    comment = db.execute(select(Comment).where(
        Comment.id == comment_id,
    ).with_for_update()).scalar_one()
    if saved := receipt(db, payload.request_id, fingerprint, ReviewRecheckRead):
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
    if reason := recheck_blocked_reason(link, comment, issue, run):
        conflict(reason)
    if payload.evidence_text is not None and (
        payload.evidence_end > len(comment.body)
        or comment.body[payload.evidence_start:payload.evidence_end] != payload.evidence_text
    ):
        conflict("invalid_evidence")
    next_status = "accepted" if payload.decision == "accept" else "rejected"
    anchor = evidence_hash(link, run)
    if (anchor == body_hash(comment.body) and next_status == link.status
            and (payload.evidence_text, payload.evidence_start, payload.evidence_end)
            == (link.evidence_text, link.evidence_start, link.evidence_end)):
        conflict("recheck_unchanged")
    old_body = evidence_body(db, link, run)
    before = {**snapshot(link, comment, issue), "body": old_body, "body_hash": anchor,
              "body_available": old_body is not None}
    before_issue = issue_snapshot(issue)
    previous = db.execute(select(IssueAction.id).where(
        IssueAction.comment_issue_id == link.id,
    ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
    previous_group = db.execute(select(IssueAction.id).where(
        IssueAction.issue_id == issue.id, IssueAction.comment_issue_id.is_(None),
    ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
    now = utcnow()
    try:
        link.status, link.origin = next_status, "human"
        link.auto_confirmed = False
        link.evidence_text = payload.evidence_text
        link.evidence_start, link.evidence_end = payload.evidence_start, payload.evidence_end
        link.evidence_verified = payload.evidence_text is not None
        link.evidence_body_hash = body_hash(comment.body)
        link.analysis_run_id, link.similarity = None, None
        link.comment_version = db.execute(select(func.max(CommentRevision.version)).where(
            CommentRevision.comment_id == comment.id,
        )).scalar_one() or 1
        link.decided_by, link.decided_at = operator, now
        link.review_version += 1
        issue.status, issue.resolved_at, issue.updated_at = "proposed", None, now
        issue.version += 1
        after = snapshot(link, comment, issue)
        action = IssueAction(
            issue_id=issue.id, comment_issue_id=link.id, action="change",
            from_status=before["status"], to_status=link.status,
            operator=operator, note=payload.note,
            request_id=payload.request_id, request_hash=fingerprint,
            payload_json={"operation": "recheck_evidence", "previous_action_id": previous,
                          "before": before, "after": after, "snapshot": after,
                          "ai_verdict": comment.has_issue,
                          "analysis_status": comment.analysis_status,
                          "source_changed": anchor != link.evidence_body_hash},
        )
        db.add(action)
        db.flush()
        group_action = IssueAction(
            issue_id=issue.id, action="change", from_status=before_issue["status"],
            to_status=issue.status, operator=operator, note=payload.note,
            payload_json={"operation": "evidence_rechecked", "previous_action_id": previous_group,
                          "before": before_issue, "after": issue_snapshot(issue),
                          "link_id": link.id, "link_action_id": action.id,
                          "before_evidence": before, "after_evidence": after},
        )
        db.add(group_action)
        db.flush()
        result = ReviewRecheckRead(
            request_id=payload.request_id, action_id=action.id, link_id=link.id,
            status=link.status, review_version=link.review_version,
            operator=operator, decided_at=now,
            issue_id=issue.id, issue_action_id=group_action.id,
            issue_status=issue.status, issue_version=issue.version,
        )
        action.result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        if saved := receipt(db, payload.request_id, fingerprint, ReviewRecheckRead):
            return saved
        raise
    except Exception:
        db.rollback()
        raise
