"""Group lifecycle is separate from accepting a comment's evidence."""
from collections import Counter

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from services.api.app.reviews.commands import conflict, receipt
from services.api.app.reviews.queries import as_review, context_query
from services.api.app.reviews.reassign import snapshot as link_snapshot
from services.api.app.reviews.rules import blocked_reason, digest, evidence_valid, review_token
from services.common.locking import lock_issue_groups
from services.common.models import Comment, CommentIssue, Issue, IssueAction, utcnow
from services.common.schemas import (
    IssueActionRead, IssueEvidencePage, IssueEvidenceRead, IssueRead, IssueWorkflowActionRead,
    IssueWorkflowQueueRead, IssueWorkflowRead, IssueWorkflowRequest,
)

ACTIONS = ("confirm", "follow_up", "resolve", "dismiss", "reopen")
TRANSITIONS = {
    "proposed": {"confirm": "confirmed", "dismiss": "dismissed"},
    "confirmed": {"follow_up": "confirmed", "resolve": "resolved", "dismiss": "dismissed"},
    "resolved": {"reopen": "proposed"},
    "dismissed": {"reopen": "proposed"},
}


def issue_snapshot(issue):
    return {"id": issue.id, "title": issue.title, "description": issue.description,
            "category_id": issue.category_id, "platform": issue.platform,
            "shop_id": issue.shop_id, "product_id": issue.product_id,
            "status": issue.status, "version": issue.version,
            "merged_into_id": issue.merged_into_id, "split_from_id": issue.split_from_id,
            "reopen_count": issue.reopen_count,
            "resolved_at": issue.resolved_at.isoformat() if issue.resolved_at else None}


def evidence_reason(row):
    link, comment, issue, run = row
    if link.status != "accepted":
        return "not_accepted"
    reason = blocked_reason(link, comment, issue, run, revising=True, check_issue_status=False)
    if reason:
        return reason
    return None if evidence_valid(link, comment) else "invalid_evidence"


def evidence_rows(db, issue_id):
    return db.execute(context_query().where(CommentIssue.issue_id == issue_id).order_by(
        CommentIssue.id,
    )).all()


def issue_token(issue, rows):
    return digest({"issue": issue_snapshot(issue), "evidence": [
        {"id": link.id, "token": review_token(link, comment, issue),
         "reason": evidence_reason(row), "decided_by": link.decided_by,
         "decided_at": link.decided_at, "origin": link.origin}
        for row in rows for link, comment, _, _ in [row]
    ]})


def action_blocked_reason(issue, action, valid_count):
    if issue.merged_into_id:
        return "issue_merged"
    if action not in TRANSITIONS.get(issue.status, {}):
        return "invalid_issue_transition"
    if action == "confirm" and not valid_count:
        return "no_valid_accepted_evidence"
    return None


def get_issue(db, issue_id):
    issue = db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(404, detail={"code": "issue_not_found"})
    return issue


def as_workflow(db, issue, *, history=False):
    rows = evidence_rows(db, issue.id)
    counts = Counter(link.status for link, _, _, _ in rows if link.superseded_at is None)
    valid = sum(evidence_reason(row) is None for row in rows)
    invalid = sum(row[0].status == "accepted" and evidence_reason(row) is not None for row in rows)
    reasons = {a: action_blocked_reason(issue, a, valid) for a in ACTIONS}
    actions = db.execute(select(IssueAction).where(
        IssueAction.issue_id == issue.id, IssueAction.comment_issue_id.is_(None),
    ).order_by(IssueAction.id.desc())).scalars().all() if history else []
    return IssueWorkflowRead(
        issue=IssueRead.model_validate(issue).model_copy(update={
            "accepted_count": counts["accepted"], "suggested_count": counts["suggested"],
        }), token=issue_token(issue, rows), valid_accepted_count=valid,
        invalid_accepted_count=invalid, evidence_total=len(rows),
        allowed_actions=[a for a, reason in reasons.items() if reason is None],
        blocked_actions={a: reason for a, reason in reasons.items() if reason is not None},
        actions=[IssueActionRead.model_validate(a) for a in actions],
        active_link_count=sum(counts.values()),
        can_restructure=bool(sum(counts.values()) and not issue.merged_into_id
                             and issue.status in ("proposed", "confirmed")),
    )


def list_issues(db, status, product_id, category_id, query, limit, offset, operator):
    stmt = select(Issue)
    if status == "merged":
        stmt = stmt.where(Issue.merged_into_id.is_not(None))
    elif status != "all":
        stmt = stmt.where(Issue.status == status, Issue.merged_into_id.is_(None))
    if product_id:
        stmt = stmt.where(Issue.product_id == product_id)
    if category_id:
        stmt = stmt.where(Issue.category_id == category_id)
    if query.strip():
        stmt = stmt.where(Issue.title.icontains(query.strip(), autoescape=True))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    issues = db.execute(stmt.order_by(Issue.updated_at.desc(), Issue.id).limit(limit).offset(
        offset,
    )).scalars().all()
    return IssueWorkflowQueueRead(items=[as_workflow(db, i) for i in issues], total=total,
                                  limit=limit, offset=offset, operator=operator)


def evidence_page(db, issue_id, limit, offset):
    get_issue(db, issue_id)
    stmt = context_query().where(CommentIssue.issue_id == issue_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(CommentIssue.id).limit(limit).offset(offset)).all()
    return IssueEvidencePage(items=[IssueEvidenceRead(
        review=as_review(db, row), usable=evidence_reason(row) is None,
        blocked_reason=evidence_reason(row),
    ) for row in rows], total=total, limit=limit, offset=offset)


def lock_context(db, issue_id):
    # Never lock Issue and then wait for Comment: Worker/import/review use the opposite order.
    metadata = db.execute(select(
        Issue.platform, Issue.shop_id, Issue.product_id, Issue.category_id,
    ).where(Issue.id == issue_id)).one_or_none()
    if metadata is None:
        raise HTTPException(404, detail={"code": "issue_not_found"})
    ids = set(db.execute(select(CommentIssue.comment_id).where(
        CommentIssue.issue_id == issue_id,
    )).scalars())
    locked_ids = set(db.execute(select(Comment.id).where(Comment.id.in_(ids)).order_by(
        Comment.id,
    ).with_for_update()).scalars())
    lock_issue_groups(db, *metadata[:3], [metadata.category_id])
    issue = db.execute(select(Issue).where(Issue.id == issue_id).with_for_update()).scalar_one()
    if (issue.platform, issue.shop_id, issue.product_id, issue.category_id) != tuple(metadata):
        conflict("issue_changed")
    rows = evidence_rows(db, issue_id)
    return issue, rows, locked_ids


def act(db, issue_id: str, payload: IssueWorkflowRequest, operator: str):
    fingerprint = digest({"operation": "issue_lifecycle", "issue_id": issue_id,
                          "operator": operator, **payload.model_dump(mode="json")})
    if saved := receipt(db, payload.request_id, fingerprint, IssueWorkflowActionRead):
        return saved
    issue, rows, locked_ids = lock_context(db, issue_id)
    if saved := receipt(db, payload.request_id, fingerprint, IssueWorkflowActionRead):
        return saved
    if {row[1].id for row in rows} != locked_ids:
        # A different comment may have joined while we acquired the parent locks.
        conflict("issue_changed")
    if payload.expected_token != issue_token(issue, rows):
        conflict("issue_changed")
    valid_count = sum(evidence_reason(row) is None for row in rows)
    if reason := action_blocked_reason(issue, payload.action, valid_count):
        conflict(reason)
    before = issue_snapshot(issue)
    evidence = [{**link_snapshot(link, comment, issue), "link_id": link.id,
                 "usable": evidence_reason(row) is None, "blocked_reason": evidence_reason(row)}
                for row in rows for link, comment, _, _ in [row] if link.status == "accepted"]
    previous = db.execute(select(IssueAction.id).where(
        IssueAction.issue_id == issue_id, IssueAction.comment_issue_id.is_(None),
    ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
    now = utcnow()
    issue.status = TRANSITIONS[issue.status][payload.action]
    issue.version += 1
    issue.updated_at = now
    if payload.action == "resolve":
        issue.resolved_at = now
    elif payload.action == "reopen":
        issue.reopen_count += 1
        issue.resolved_at = None
    action = IssueAction(
        issue_id=issue_id, action=payload.action, from_status=before["status"],
        to_status=issue.status, operator=operator, note=payload.note,
        request_id=payload.request_id, request_hash=fingerprint,
        payload_json={"operation": "issue_lifecycle", "previous_action_id": previous,
                      "before": before, "after": issue_snapshot(issue),
                      "accepted_evidence": evidence, "valid_accepted_count": valid_count,
                      "evidence_total": len(rows)},
    )
    db.add(action)
    try:
        db.flush()
        result = IssueWorkflowActionRead(
            request_id=payload.request_id, issue_id=issue_id, action_id=action.id,
            action=payload.action, status=issue.status, version=issue.version,
            operator=operator, created_at=now,
        )
        action.result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        if saved := receipt(db, payload.request_id, fingerprint, IssueWorkflowActionRead):
            return saved
        raise
    except Exception:
        db.rollback()
        raise
