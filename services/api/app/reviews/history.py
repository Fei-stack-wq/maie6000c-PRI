"""Recover a genuine historical body by its exact anchor, never by a guessed revision number."""
from sqlalchemy import select

from services.api.app.reviews.rules import body_hash, evidence_hash
from services.common.models import CommentRevision, IssueAction


def evidence_body(db, link, run):
    anchor = evidence_hash(link, run)
    if anchor is None:
        return None
    payloads = db.execute(select(IssueAction.payload_json).where(
        IssueAction.comment_issue_id == link.id,
    ).order_by(IssueAction.id.desc())).scalars()
    for payload in payloads:
        for key in ("snapshot", "after", "before"):
            data = (payload or {}).get(key) or {}
            body = data.get("body")
            if isinstance(body, str) and body_hash(body) == anchor:
                return body
    bodies = db.execute(select(CommentRevision.body).where(
        CommentRevision.comment_id == link.comment_id,
    ).order_by(CommentRevision.version.desc())).scalars()
    return next((body for body in bodies if body_hash(body) == anchor), None)
