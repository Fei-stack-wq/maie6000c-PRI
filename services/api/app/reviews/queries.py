"""One read shape for the queue and the detail view; snapshots come from the server."""
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session

from services.api.app.reviews.rules import (
    blocked_reason, body_hash, needs_recheck, reassign_blocked_reason,
    recheck_blocked_reason, review_token,
)
from services.api.app.reviews.history import evidence_body
from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction
from services.common.schemas import (
    CommentIssueRead, CommentRead, IssueActionRead, IssueRead, ReviewRead,
)


def context_query():
    return (select(CommentIssue, Comment, Issue, AnalysisRun)
            .join(Comment, Comment.id == CommentIssue.comment_id)
            .join(Issue, Issue.id == CommentIssue.issue_id)
            .outerjoin(AnalysisRun, AnalysisRun.id == CommentIssue.analysis_run_id))


def as_review(db: Session, row, history: bool = False) -> ReviewRead:
    link, comment, issue, run = row
    reason = blocked_reason(link, comment, issue, run)
    revision_reason = blocked_reason(link, comment, issue, run, revising=True)
    reassign_reason = reassign_blocked_reason(link, comment, issue, run)
    recheck_reason = recheck_blocked_reason(link, comment, issue, run)
    counts = dict(db.execute(
        select(CommentIssue.status, func.count()).where(
            CommentIssue.issue_id == issue.id, CommentIssue.superseded_at.is_(None),
        ).group_by(CommentIssue.status)
    ).all())
    issue_read = IssueRead.model_validate(issue).model_copy(update={
        "suggested_count": counts.get("suggested", 0),
        "accepted_count": counts.get("accepted", 0),
    })
    actions = db.execute(select(IssueAction).where(
        IssueAction.comment_issue_id == link.id,
    ).order_by(IssueAction.id.desc())).scalars().all() if history else []
    return ReviewRead(
        link=CommentIssueRead.model_validate(link), comment=CommentRead.model_validate(comment),
        issue=issue_read, review_version=link.review_version,
        token=review_token(link, comment, issue), can_decide=reason is None,
        can_revise=revision_reason is None, revision_blocked_reason=revision_reason,
        can_reassign=reassign_reason is None, reassign_blocked_reason=reassign_reason,
        needs_recheck=needs_recheck(link, comment, run), can_recheck=recheck_reason is None,
        recheck_blocked_reason=recheck_reason,
        evidence_body=evidence_body(db, link, run) if history else None,
        blocked_reason=reason, actions=[IssueActionRead.model_validate(a) for a in actions],
    )


def queue_query(status: str, product_id: str | None, category_id: str | None):
    query = context_query().where(CommentIssue.superseded_at.is_(None))
    if status == "pending":
        query = query.where(
            CommentIssue.status == "suggested", CommentIssue.decided_by.is_(None),
            CommentIssue.decided_at.is_(None),
            or_(and_(
                CommentIssue.origin == "human", CommentIssue.evidence_body_hash.is_not(None),
                Comment.analysis_status.in_(["analyzed", "failed"]),
            ), and_(
                Comment.analysis_status == "analyzed", AnalysisRun.status == "succeeded",
                Comment.current_analysis_run_id == CommentIssue.analysis_run_id,
            )), Issue.status.in_(["proposed", "confirmed"]),
            Issue.merged_into_id.is_(None),
        )
    elif status == "needs_recheck":
        query = query.where(or_(CommentIssue.status.in_(["accepted", "rejected"]),
                               CommentIssue.origin == "human",
                               CommentIssue.decided_by.is_not(None),
                               CommentIssue.decided_at.is_not(None)))
    else:
        query = query.where(CommentIssue.status.in_(["accepted", "rejected"]))
    if product_id:
        query = query.where(Comment.product_id == product_id)
    if category_id:
        query = query.where(Issue.category_id == category_id)
    return query


def list_queue(db: Session, status: str, product_id, category_id, limit: int, offset: int):
    query = queue_query(status, product_id, category_id)
    # Exact hashes are calculated in Python on both SQLite and PostgreSQL, using one rule.
    # Fetch only IDs/body/hash for eligibility before paginating the full detail objects.
    candidates = db.execute(query.with_only_columns(
        CommentIssue.id, Comment.body, case(
            (CommentIssue.origin == "human",
             func.coalesce(CommentIssue.evidence_body_hash, case(
                 (AnalysisRun.comment_id == Comment.id, AnalysisRun.input_hash), else_=None,
             ))),
            else_=case((AnalysisRun.comment_id == Comment.id, AnalysisRun.input_hash), else_=None),
        ),
    ).order_by(CommentIssue.created_at, CommentIssue.id)).all()
    ids = [link_id for link_id, body, saved_hash in candidates
           if (body_hash(body) != saved_hash if status == "needs_recheck"
               else status != "pending" or body_hash(body) == saved_hash)]
    page_ids = ids[offset:offset + limit]
    rows = db.execute(context_query().where(
        CommentIssue.id.in_(page_ids),
    ).order_by(CommentIssue.created_at, CommentIssue.id)).all() if page_ids else []
    return [as_review(db, row) for row in rows], len(ids)
