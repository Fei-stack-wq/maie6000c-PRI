"""AI boundary: immutable input, bounded HTTP call, schema and evidence validation."""
import hashlib
from dataclasses import dataclass
from time import perf_counter

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from services.common.categories import CATEGORY_VERSION, is_valid_category
from services.common.models import Comment, CommentRevision, HasIssue
from services.common.schemas import ExtractedIssue, ExtractionResult
from services.worker.app.policy import CommentNotFound, InvalidAIOutput


@dataclass(frozen=True)
class AnalysisInput:
    comment_id: str
    platform: str
    shop_id: str
    product_id: str
    body: str
    input_hash: str
    revision_id: int
    comment_version: int


@dataclass(frozen=True)
class VerifiedIssue:
    issue: ExtractedIssue
    start: int
    end: int


@dataclass(frozen=True)
class VerifiedAnalysis:
    result: ExtractionResult
    issues: tuple[VerifiedIssue, ...]
    has_issue: str
    invalid_evidence_count: int


def load_analysis_input(db: Session, comment_id: str) -> AnalysisInput:
    comment = db.execute(
        select(Comment).where(Comment.id == comment_id).with_for_update()
    ).scalar_one_or_none()
    if comment is None:
        raise CommentNotFound(comment_id)
    revision_id, version = db.execute(
        select(func.max(CommentRevision.id), func.max(CommentRevision.version))
        .where(CommentRevision.comment_id == comment_id)
    ).one()
    return AnalysisInput(
        comment.id, comment.platform, comment.shop_id, comment.product_id, comment.body,
        hashlib.sha256(comment.body.encode("utf-8")).hexdigest(),
        revision_id or 0, version or 1,
    )


def call_ai_service(snapshot: AnalysisInput, url: str, timeout: float) -> tuple[object, int]:
    started = perf_counter()
    response = httpx.post(
        f"{url.rstrip('/')}/extract-issues",
        json={
            "comment_id": snapshot.comment_id, "product_id": snapshot.product_id,
            "body": snapshot.body,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    try:
        raw = response.json()
    except ValueError as exc:
        raise InvalidAIOutput("Expected JSON response") from exc
    return raw, max(0, round((perf_counter() - started) * 1000))


def validate_ai_result(raw: object, snapshot: AnalysisInput) -> ExtractionResult:
    try:
        result = ExtractionResult.model_validate(raw)
    except ValueError as exc:
        raise InvalidAIOutput("Schema validation failed") from exc
    if result.comment_id != snapshot.comment_id:
        raise InvalidAIOutput("Mismatched comment ID")
    if result.schema_version != "1" or result.category_version != CATEGORY_VERSION:
        raise InvalidAIOutput("Unsupported output version")
    if any(not is_valid_category(issue.category_id) for issue in result.issues):
        raise InvalidAIOutput("Unknown category")
    return result


def verify_evidence(result: ExtractionResult, snapshot: AnalysisInput) -> VerifiedAnalysis:
    verified = []
    invalid = 0
    for issue in result.issues:
        start = snapshot.body.find(issue.evidence_text)
        if start < 0:
            invalid += 1
        else:
            verified.append(VerifiedIssue(issue, start, start + len(issue.evidence_text)))
    has_issue = HasIssue.UNKNOWN.value if invalid else result.has_issue.value
    return VerifiedAnalysis(result, tuple(verified), has_issue, invalid)
