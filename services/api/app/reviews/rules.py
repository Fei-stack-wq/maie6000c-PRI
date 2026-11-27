"""Review freshness is separate from the saved human decision."""
import hashlib
import json

from services.common.models import AnalysisRun, Comment, CommentIssue, Issue


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, default=str,
    ).encode()).hexdigest()


def body_hash(body: str) -> str:
    # Same exact-text hash as AnalysisInput; ingestion's whitespace-normalised hash differs.
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def review_token(link: CommentIssue, comment: Comment, issue: Issue) -> str:
    return digest({
        "link_id": link.id, "version": link.review_version, "run": link.analysis_run_id,
        "body_hash": body_hash(comment.body), "current_run": comment.current_analysis_run_id,
        "analysis_status": comment.analysis_status, "status": link.status,
        "superseded_at": link.superseded_at, "issue_version": issue.version,
        "issue_status": issue.status, "merged_into": issue.merged_into_id,
        "evidence": link.evidence_text, "start": link.evidence_start, "end": link.evidence_end,
        "evidence_body_hash": link.evidence_body_hash,
        "evidence_verified": link.evidence_verified, "origin": link.origin,
        "decided_by": link.decided_by, "decided_at": link.decided_at,
        "comment_scope": (comment.platform, comment.shop_id, comment.product_id),
        "issue_scope": (issue.platform, issue.shop_id, issue.product_id),
        "issue_title": issue.title, "category_id": issue.category_id,
    })


def evidence_hash(link, run):
    if link.origin == "human" and link.evidence_body_hash is not None:
        return link.evidence_body_hash
    return run.input_hash if run and run.comment_id == link.comment_id else None


def human_managed(link):
    return (link.status in ("accepted", "rejected") or link.origin == "human"
            or link.decided_by is not None or link.decided_at is not None)


def needs_recheck(link, comment, run):
    return bool(link.superseded_at is None and human_managed(link)
                and evidence_hash(link, run) != body_hash(comment.body))


def recheck_blocked_reason(link, comment, issue, run):
    if comment.batch_id != issue.batch_id:
        return "scope_mismatch"
    if (comment.platform, comment.shop_id, comment.product_id) != (
        issue.platform, issue.shop_id, issue.product_id,
    ):
        return "scope_mismatch"
    if link.superseded_at is not None:
        return "suggestion_superseded"
    if issue.merged_into_id or issue.status not in ("proposed", "confirmed"):
        return "issue_not_active"
    if not human_managed(link):
        return "not_human_managed"
    if run and run.comment_id != comment.id:
        return "analysis_changed"
    if manual_blocked_reason(comment):
        return "analysis_not_ready"
    if not needs_recheck(link, comment, run) and evidence_valid(link, comment):
        return "source_unchanged"
    return None


def blocked_reason(
    link: CommentIssue, comment: Comment, issue: Issue, run: AnalysisRun | None,
    *, revising: bool = False, check_issue_status: bool = True,
) -> str | None:
    if (comment.platform, comment.shop_id, comment.product_id) != (
        issue.platform, issue.shop_id, issue.product_id,
    ):
        return "scope_mismatch"
    if run is not None and run.comment_id != comment.id:
        return "analysis_changed"
    if link.superseded_at is not None:
        return "suggestion_superseded"
    human_snapshot = link.origin == "human" and link.evidence_body_hash is not None
    saved_hash = link.evidence_body_hash if human_snapshot else (run.input_hash if run else None)
    if saved_hash != body_hash(comment.body):
        return "source_changed"
    if revising:
        if link.status not in ("accepted", "rejected"):
            return "not_reviewed"
    elif link.status != "suggested" or link.decided_by is not None or link.decided_at is not None:
        return "already_reviewed"
    if human_snapshot:
        if manual_blocked_reason(comment):
            return "analysis_not_ready"
    elif comment.analysis_status != "analyzed":
        return "analysis_not_ready"
    if not human_snapshot and run.status != "succeeded":
        return "analysis_changed"
    # Worker deliberately preserves reviewed links, including their original run/evidence.
    # A later run on unchanged text must not permanently lock out an explicit correction.
    if not human_snapshot and not revising and run.id != comment.current_analysis_run_id:
        return "analysis_changed"
    if check_issue_status and (
        issue.merged_into_id or issue.status not in ("proposed", "confirmed")
    ):
        return "issue_not_active"
    return None


def manual_blocked_reason(comment: Comment) -> str | None:
    return None if comment.analysis_status in ("analyzed", "failed") else "analysis_not_ready"


def manual_token(comment: Comment, links) -> str:
    return digest({
        "comment_id": comment.id, "body_hash": body_hash(comment.body),
        "scope": (comment.platform, comment.shop_id, comment.product_id),
        "analysis_status": comment.analysis_status, "current_run": comment.current_analysis_run_id,
        "links": [(link.id, link.review_version, link.status, link.superseded_at,
                   link.decided_by, link.decided_at, link.origin) for link in links],
    })


def evidence_valid(link: CommentIssue, comment: Comment) -> bool:
    return bool(
        link.evidence_verified and link.evidence_text
        and link.evidence_start is not None and link.evidence_end is not None
        and 0 <= link.evidence_start < link.evidence_end <= len(comment.body)
        and comment.body[link.evidence_start:link.evidence_end] == link.evidence_text
    )


def reassign_blocked_reason(link, comment, issue, run) -> str | None:
    if link.status not in ("suggested", "accepted"):
        return "source_not_assignable"
    reason = blocked_reason(link, comment, issue, run, revising=link.status == "accepted")
    if reason:
        return reason
    return None if evidence_valid(link, comment) else "invalid_evidence"


def target_blocked_reason(issue: Issue, link: CommentIssue | None) -> str | None:
    if issue.merged_into_id or issue.status not in ("proposed", "confirmed"):
        return "issue_not_active"
    if link is not None and (
        link.status != "suggested" or link.origin == "human"
        or link.decided_by is not None or link.decided_at is not None
    ):
        return "target_already_reviewed"
    return None


def target_token(issue: Issue, link: CommentIssue | None, comment: Comment) -> str:
    return digest({
        "issue_id": issue.id, "version": issue.version, "status": issue.status,
        "title": issue.title, "category_id": issue.category_id,
        "scope": (issue.platform, issue.shop_id, issue.product_id),
        "merged_into": issue.merged_into_id,
        "existing_link": review_token(link, comment, issue) if link else None,
        "origin": link.origin if link else None,
        "decided_by": link.decided_by if link else None,
        "decided_at": link.decided_at if link else None,
    })
