"""Human evidence starts with a comment, including comments without AI suggestions."""
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api.app.reviews.commands import conflict, receipt
from services.api.app.reviews.queries import as_review, context_query
from services.api.app.reviews.reassign import issue_targets, snapshot
from services.api.app.reviews.rules import (
    body_hash, digest, manual_blocked_reason, manual_token, target_blocked_reason, target_token,
)
from services.common.locking import lock_issue_groups
from services.common.models import (
    Comment, CommentIssue, CommentRevision, Issue, IssueAction, utcnow,
)
from services.common.schemas import (
    CommentRead, ManualCommentQueueRead, ManualCommentRead, ManualLinkRead, ManualLinkRequest,
)


def get_comment(db, comment_id, *, lock=False):
    query = select(Comment).where(Comment.id == comment_id)
    comment = db.execute(query.with_for_update() if lock else query).scalar_one_or_none()
    if comment is None:
        raise HTTPException(404, detail={"code": "comment_not_found"})
    return comment


def comment_links(db, comment_id):
    return db.execute(select(CommentIssue).where(
        CommentIssue.comment_id == comment_id,
    ).order_by(CommentIssue.id)).scalars().all()


def list_comments(db, verdict, product_id, query, limit, offset, operator):
    stmt = select(Comment)
    if verdict == "attention":
        stmt = stmt.where(or_(Comment.has_issue.in_(["no", "unknown"]),
                              Comment.analysis_status == "failed"))
    elif verdict == "failed":
        stmt = stmt.where(Comment.analysis_status == "failed")
    elif verdict != "all":
        stmt = stmt.where(Comment.has_issue == verdict)
    if product_id:
        stmt = stmt.where(Comment.product_id == product_id)
    if query.strip():
        stmt = stmt.where(Comment.body.icontains(query.strip(), autoescape=True))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    comments = db.execute(stmt.order_by(Comment.created_at.desc(), Comment.id).limit(
        limit,
    ).offset(offset)).scalars().all()
    return ManualCommentQueueRead(items=[CommentRead.model_validate(c) for c in comments],
                                  total=total, limit=limit, offset=offset, operator=operator)


def detail(db, comment_id):
    comment = get_comment(db, comment_id)
    rows = db.execute(context_query().where(CommentIssue.comment_id == comment_id).order_by(
        CommentIssue.id,
    )).all()
    reason = manual_blocked_reason(comment)
    return ManualCommentRead(
        comment=CommentRead.model_validate(comment), can_add=reason is None, blocked_reason=reason,
        token=manual_token(comment, [row[0] for row in rows]),
        links=[as_review(db, row) for row in rows],
    )


def targets(db, comment_id, query, limit, offset):
    comment = get_comment(db, comment_id)
    if reason := manual_blocked_reason(comment):
        conflict(reason)
    return issue_targets(db, comment, query, limit, offset)


def normalize_title(value):
    return " ".join(value.split()).casefold()


def add_link(db: Session, comment_id: str, payload: ManualLinkRequest, operator: str):
    fingerprint = digest({"operation": "manual_add", "comment_id": comment_id,
                          "operator": operator, **payload.model_dump(mode="json")})
    if saved := receipt(db, payload.request_id, fingerprint, ManualLinkRead):
        return saved
    comment = get_comment(db, comment_id, lock=True)
    if saved := receipt(db, payload.request_id, fingerprint, ManualLinkRead):
        return saved
    links = comment_links(db, comment_id)
    if payload.expected_token != manual_token(comment, links):
        conflict("comment_changed")
    if reason := manual_blocked_reason(comment):
        conflict(reason)
    if (payload.evidence_end > len(comment.body)
            or comment.body[payload.evidence_start:payload.evidence_end] != payload.evidence_text):
        conflict("invalid_evidence")
    scope = (comment.platform, comment.shop_id, comment.product_id)
    created_issue = payload.new_issue is not None
    link = None
    before = None
    try:
        if created_issue:
            category = payload.new_issue.category_id
            lock_issue_groups(db, *scope, [category])
            candidates = db.execute(select(Issue).where(
                Issue.platform == comment.platform, Issue.shop_id == comment.shop_id,
                Issue.product_id == comment.product_id, Issue.category_id == category,
                Issue.status.in_(["proposed", "confirmed"]), Issue.merged_into_id.is_(None),
            )).scalars().all()
            if any(normalize_title(i.title) == normalize_title(payload.new_issue.title)
                   for i in candidates):
                conflict("duplicate_issue")
            issue = Issue(
                platform=comment.platform, shop_id=comment.shop_id, product_id=comment.product_id,
                category_id=category, title=" ".join(payload.new_issue.title.split()),
                status="proposed", created_by="human",
            )
            db.add(issue)
            db.flush()
        else:
            metadata = db.execute(select(
                Issue.platform, Issue.shop_id, Issue.product_id, Issue.category_id,
            ).where(Issue.id == payload.target_issue_id)).one_or_none()
            if metadata is None:
                raise HTTPException(404, detail={"code": "target_issue_not_found"})
            if tuple(metadata[:3]) != scope:
                conflict("scope_mismatch")
            lock_issue_groups(db, *scope, [metadata.category_id])
            issue = db.execute(select(Issue).where(
                Issue.id == payload.target_issue_id,
            ).with_for_update()).scalar_one_or_none()
            if (issue is None or (issue.platform, issue.shop_id, issue.product_id) != scope
                    or issue.category_id != metadata.category_id):
                conflict("target_changed")
            # The parent comment lock serializes all writes to its links, including Worker.
            link = next((link for link in links if link.issue_id == issue.id), None)
            if payload.expected_target_token != target_token(issue, link, comment):
                conflict("target_changed")
            if reason := target_blocked_reason(issue, link):
                conflict(reason)
            before = snapshot(link, comment, issue) if link else None
        previous_id = db.execute(select(IssueAction.id).where(
            IssueAction.comment_issue_id == link.id,
        ).order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none() if link else None
        if link is None:
            link = CommentIssue(comment_id=comment_id, issue_id=issue.id)
            db.add(link)
        now = utcnow()
        link.status, link.origin = "accepted", "human"
        link.evidence_text = payload.evidence_text
        link.evidence_start, link.evidence_end = payload.evidence_start, payload.evidence_end
        link.evidence_verified, link.evidence_body_hash = True, body_hash(comment.body)
        link.analysis_run_id, link.similarity, link.superseded_at = None, None, None
        link.comment_version = db.execute(select(func.max(CommentRevision.version)).where(
            CommentRevision.comment_id == comment_id,
        )).scalar_one() or 1
        link.review_version = (link.review_version or 0) + 1
        link.decided_by, link.decided_at = operator, now
        db.flush()
        after = snapshot(link, comment, issue)
        action = IssueAction(
            issue_id=issue.id, comment_issue_id=link.id, action="accept",
            from_status=before["status"] if before else None, to_status="accepted",
            operator=operator, note=payload.note, request_id=payload.request_id,
            request_hash=fingerprint,
            payload_json={"operation": "manual_add", "created_issue": created_issue,
                          "previous_action_id": previous_id, "before": before, "after": after,
                          "snapshot": after, "ai_verdict": comment.has_issue,
                          "analysis_status": comment.analysis_status},
        )
        db.add(action)
        db.flush()
        result = ManualLinkRead(
            request_id=payload.request_id, link_id=link.id, issue_id=issue.id,
            action_id=action.id, created_issue=created_issue, operator=operator, decided_at=now,
        )
        action.result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        if saved := receipt(db, payload.request_id, fingerprint, ManualLinkRead):
            return saved
        raise
    except Exception:
        db.rollback()
        raise
