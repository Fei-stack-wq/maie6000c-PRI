"""Move supporting evidence between existing issue groups without deleting history."""
from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.reviews.commands import conflict, receipt
from services.api.app.reviews.queries import context_query
from services.api.app.reviews.rules import (
    body_hash, digest, reassign_blocked_reason, review_token,
    target_blocked_reason, target_token,
)
from services.common.locking import lock_issue_groups
from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction, utcnow
from services.common.schemas import (
    IssueRead, ReassignRead, ReassignRequest, ReassignTargetRead, ReassignTargetsRead,
)


def list_targets(db: Session, link_id: int, query: str, limit: int, offset: int):
    row = db.execute(context_query().where(CommentIssue.id == link_id)).one_or_none()
    if row is None:
        raise HTTPException(404, detail={"code": "link_not_found"})
    source, comment, issue, run = row
    reason = reassign_blocked_reason(source, comment, issue, run)
    if reason:
        conflict(reason)
    return issue_targets(db, comment, query, limit, offset, exclude_id=issue.id)


def issue_targets(db, comment, query, limit, offset, exclude_id=None):
    """Same scope, paging and protection rules for regrouping and manual additions."""
    stmt = select(Issue, CommentIssue).outerjoin(CommentIssue, and_(
        CommentIssue.issue_id == Issue.id, CommentIssue.comment_id == comment.id,
    )).where(
        Issue.platform == comment.platform,
        Issue.shop_id == comment.shop_id, Issue.product_id == comment.product_id,
        Issue.status.in_(["proposed", "confirmed"]), Issue.merged_into_id.is_(None),
    )
    if exclude_id:
        stmt = stmt.where(Issue.id != exclude_id)
    if query.strip():
        stmt = stmt.where(Issue.title.icontains(query.strip(), autoescape=True))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(Issue.title, Issue.id).limit(limit).offset(offset)).all()
    counts = {}
    if rows:
        for issue_id, status, count in db.execute(select(
            CommentIssue.issue_id, CommentIssue.status, func.count(),
        ).where(
            CommentIssue.issue_id.in_([target.id for target, _ in rows]),
            CommentIssue.superseded_at.is_(None),
        ).group_by(CommentIssue.issue_id, CommentIssue.status)):
            counts.setdefault(issue_id, {})[status] = count
    items = []
    for target, link in rows:
        blocked = target_blocked_reason(target, link)
        data = IssueRead.model_validate(target).model_copy(update={
            "accepted_count": counts.get(target.id, {}).get("accepted", 0),
            "suggested_count": counts.get(target.id, {}).get("suggested", 0),
        })
        items.append(ReassignTargetRead(
            issue=data, token=target_token(target, link, comment),
            existing_link_id=link.id if link else None,
            existing_link_status=link.status if link else None,
            selectable=blocked is None, blocked_reason=blocked,
        ))
    return ReassignTargetsRead(items=items, total=total, limit=limit, offset=offset)


def snapshot(link: CommentIssue, comment: Comment, issue: Issue) -> dict:
    return {
        "comment_id": comment.id, "body": comment.body, "body_hash": body_hash(comment.body),
        "comment_version": link.comment_version, "analysis_run_id": link.analysis_run_id,
        "issue_id": issue.id, "issue_version": issue.version, "issue_title": issue.title,
        "category_id": issue.category_id, "evidence_text": link.evidence_text,
        "evidence_start": link.evidence_start, "evidence_end": link.evidence_end,
        "evidence_body_hash": link.evidence_body_hash,
        "evidence_verified": link.evidence_verified,
        "superseded_at": link.superseded_at.isoformat() if link.superseded_at else None,
        "origin": link.origin, "status": link.status, "review_version": link.review_version,
        "decided_by": link.decided_by,
        "decided_at": link.decided_at.isoformat() if link.decided_at else None,
    }


def reassign(db: Session, link_id: int, payload: ReassignRequest, operator: str):
    fingerprint = digest({"operation": "reassign", "link_id": link_id,
                          "operator": operator, **payload.model_dump(mode="json")})
    saved = receipt(db, payload.request_id, fingerprint, ReassignRead)
    if saved:
        return saved
    comment_id = db.execute(select(CommentIssue.comment_id).where(
        CommentIssue.id == link_id,
    )).scalar_one_or_none()
    if comment_id is None:
        raise HTTPException(404, detail={"code": "link_not_found"})
    comment = db.execute(select(Comment).where(
        Comment.id == comment_id,
    ).with_for_update()).scalar_one()
    saved = receipt(db, payload.request_id, fingerprint, ReassignRead)
    if saved:
        return saved
    source = db.execute(select(CommentIssue).where(
        CommentIssue.id == link_id,
    ).with_for_update()).scalar_one()
    if source.issue_id == payload.target_issue_id:
        conflict("same_issue")
    # Inspect metadata before taking group locks; recheck it under row locks below.
    groups = db.execute(select(
        Issue.id, Issue.platform, Issue.shop_id, Issue.product_id, Issue.category_id,
    ).where(Issue.id.in_([source.issue_id, payload.target_issue_id]))).all()
    if len(groups) != 2:
        raise HTTPException(404, detail={"code": "target_issue_not_found"})
    scope = (comment.platform, comment.shop_id, comment.product_id)
    if any((group.platform, group.shop_id, group.product_id) != scope for group in groups):
        conflict("scope_mismatch")
    categories = {group.id: group.category_id for group in groups}
    # Same ordered advisory locks as Worker, before holding more than one Issue row.
    lock_issue_groups(db, *scope, categories.values())
    locked = db.execute(select(Issue).where(Issue.id.in_(categories)).order_by(
        Issue.id,
    ).with_for_update()).scalars().all()
    if len(locked) != 2:
        conflict("target_changed")
    for issue in locked:
        if ((issue.platform, issue.shop_id, issue.product_id) != scope
                or issue.category_id != categories[issue.id]):
            conflict("target_changed")
    issue_map = {issue.id: issue for issue in locked}
    old_issue, new_issue = issue_map[source.issue_id], issue_map[payload.target_issue_id]
    target = db.execute(select(CommentIssue).where(
        CommentIssue.comment_id == comment.id, CommentIssue.issue_id == new_issue.id,
    ).with_for_update()).scalar_one_or_none()
    run = db.get(AnalysisRun, source.analysis_run_id) if source.analysis_run_id else None
    if payload.expected_token != review_token(source, comment, old_issue):
        conflict("review_changed")
    reason = reassign_blocked_reason(source, comment, old_issue, run)
    if reason:
        conflict(reason)
    if payload.expected_target_token != target_token(new_issue, target, comment):
        conflict("target_changed")
    reason = target_blocked_reason(new_issue, target)
    if reason:
        conflict(reason)
    before_source = snapshot(source, comment, old_issue)
    before_target = snapshot(target, comment, new_issue) if target else None
    now = utcnow()
    try:
        source.status, source.decided_by, source.decided_at = "rejected", operator, now
        source.review_version += 1
        if target is None:
            target = CommentIssue(comment_id=comment.id, issue_id=new_issue.id)
            db.add(target)
        # Only an unreviewed suggestion can be reused. Prior target evidence is kept in audit.
        target.status, target.origin = "accepted", "human"
        target.evidence_text = source.evidence_text
        target.evidence_start, target.evidence_end = source.evidence_start, source.evidence_end
        target.evidence_verified = True
        target.evidence_body_hash = source.evidence_body_hash
        target.analysis_run_id = source.analysis_run_id
        target.comment_version = source.comment_version
        target.similarity, target.superseded_at = None, None
        target.decided_by, target.decided_at = operator, now
        target.review_version = (target.review_version or 0) + 1
        db.flush()
        common = {
            "operation_id": payload.request_id,
            "source_link_id": source.id, "target_link_id": target.id,
            "source_issue_id": old_issue.id, "target_issue_id": new_issue.id,
            "source_issue_title": old_issue.title, "target_issue_title": new_issue.title,
        }
        actions = []
        for link, issue, before, operation in (
            (source, old_issue, before_source, "reassign_out"),
            (target, new_issue, before_target, "reassign_in"),
        ):
            previous = db.execute(select(IssueAction.id).where(
                IssueAction.comment_issue_id == link.id,
            ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
            after = snapshot(link, comment, issue)
            action = IssueAction(
                issue_id=issue.id, comment_issue_id=link.id, action="change",
                from_status=before["status"] if before else None, to_status=link.status,
                operator=operator, note=payload.note,
                payload_json={**common, "operation": operation,
                              "previous_action_id": previous, "before": before,
                              "after": after, "snapshot": after},
            )
            db.add(action)
            actions.append(action)
        actions[0].request_id, actions[0].request_hash = payload.request_id, fingerprint
        db.flush()
        result = ReassignRead(
            request_id=payload.request_id, source_link_id=source.id, target_link_id=target.id,
            source_issue_id=old_issue.id, target_issue_id=new_issue.id,
            source_action_id=actions[0].id, target_action_id=actions[1].id,
            operator=operator, decided_at=now,
        )
        actions[0].result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        saved = receipt(db, payload.request_id, fingerprint, ReassignRead)
        if saved:
            return saved
        raise
    except Exception:
        db.rollback()
        raise
