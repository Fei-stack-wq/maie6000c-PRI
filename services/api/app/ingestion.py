"""CSV / comment ingestion for the review-management API (R1 data layer).

Responsibilities (see ``docs/team-division.md`` → R1):

1. parse a batch payload (CSV text or already-normalised comments);
2. validate required fields, lengths and limits, collecting per-row errors;
3. synthesise a stable ``source_review_id`` when the platform has none;
4. upsert ``comments`` (dedupe by source key, body-change revisions) and
   create one analysis ``jobs`` row per comment, in the caller's transaction.

The module has no FastAPI dependency so the Worker / scripts can reuse it.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.common.models import (
    AnalysisStatus,
    Comment,
    CommentRevision,
    DedupeMode,
    IngestionBatch,
    Job,
    JobStatus,
    JobType,
)
from services.common.schemas import NormalizedComment

MAX_ROWS = 5_000
MAX_BODY_LENGTH = 2_000
REQUIRED_COLUMNS = ("shop_id", "product_id", "body")
OPTIONAL_COLUMNS = ("source_review_id", "review_date", "rating")
KNOWN_COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS


@dataclass
class RowError:
    row_number: int
    column_name: str | None
    code: str
    message: str


@dataclass
class ParsedComment:
    platform: str
    shop_id: str
    product_id: str
    source_review_id: str
    rating: int | None
    review_date: datetime | None
    body: str
    content_hash: str
    dedupe_mode: str


@dataclass
class ParseResult:
    comments: list[ParsedComment] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    declared_rows: int = 0
    fatal: bool = False


@dataclass
class IngestCounts:
    accepted_rows: int = 0
    duplicate_rows: int = 0
    job_count: int = 0


def normalize_body(body: str) -> str:
    """Trim + collapse whitespace so hashing and evidence matching agree."""
    return " ".join(body.split()).strip()


def content_hash(body: str) -> str:
    return hashlib.sha256(normalize_body(body).encode("utf-8")).hexdigest()


def synthetic_source_review_id(
    platform: str,
    shop_id: str,
    product_id: str,
    body_hash: str,
    review_date: datetime | None,
) -> str:
    """Stable placeholder id for platforms without a review id (never looks real)."""
    raw = "|".join(
        [platform, shop_id, product_id, body_hash, review_date.isoformat() if review_date else ""]
    )
    return "synth:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _parse_date(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("review_date must be ISO date/datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_rating(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        rating = int(value)
    except ValueError as exc:
        raise ValueError("rating must be an integer 0-5") from exc
    if not 0 <= rating <= 5:
        raise ValueError("rating must be an integer 0-5")
    return rating


def _build_comment(
    platform: str,
    row: dict[str, str],
    row_number: int,
    errors: list[RowError],
) -> ParsedComment | None:
    def add(column: str | None, code: str, message: str) -> None:
        errors.append(RowError(row_number, column, code, message))

    row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
    shop_id = row.get("shop_id", "")
    product_id = row.get("product_id", "")
    body = row.get("body", "")

    if not shop_id:
        add("shop_id", "required", "shop_id is required")
    if not product_id:
        add("product_id", "required", "product_id is required")
    if not body:
        add("body", "required", "body is required")
    if len(body) > MAX_BODY_LENGTH:
        add("body", "too_long", f"body exceeds {MAX_BODY_LENGTH} characters")
    if len(shop_id) > 64:
        add("shop_id", "too_long", "shop_id exceeds 64 characters")
    if len(product_id) > 64:
        add("product_id", "too_long", "product_id exceeds 64 characters")

    try:
        rating = _parse_rating(row.get("rating", ""))
    except ValueError as exc:
        add("rating", "invalid_rating", str(exc))
        rating = None
    try:
        review_date = _parse_date(row.get("review_date", ""))
    except ValueError as exc:
        add("review_date", "invalid_date", str(exc))
        review_date = None

    if any(err.row_number == row_number for err in errors):
        return None

    body_hash = content_hash(body)
    source_review_id = row.get("source_review_id", "")
    if source_review_id:
        dedupe_mode = DedupeMode.SOURCE_ID.value
    else:
        source_review_id = synthetic_source_review_id(
            platform, shop_id, product_id, body_hash, review_date
        )
        dedupe_mode = DedupeMode.CONTENT_HASH.value

    return ParsedComment(
        platform=platform,
        shop_id=shop_id,
        product_id=product_id,
        source_review_id=source_review_id,
        rating=rating,
        review_date=review_date,
        body=body,
        content_hash=body_hash,
        dedupe_mode=dedupe_mode,
    )


def parse_csv(text: str, platform: str) -> ParseResult:
    """Parse CSV text into normalised comments, collecting per-row errors."""
    result = ParseResult()
    cleaned = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(cleaned))
    headers = [h.strip() for h in (reader.fieldnames or []) if h]

    missing = [column for column in REQUIRED_COLUMNS if column not in headers]
    if missing:
        result.fatal = True
        result.errors.append(
            RowError(1, None, "missing_columns", "missing required columns: " + ", ".join(missing))
        )
        return result

    unknown = [column for column in headers if column not in KNOWN_COLUMNS]
    if unknown:
        # Unknown columns are tolerated but reported once, so uploads from other
        # platform exports can be imported without editing the file.
        result.errors.append(
            RowError(1, None, "unknown_columns", "ignored columns: " + ", ".join(unknown))
        )

    for offset, row in enumerate(reader, start=2):
        if result.declared_rows >= MAX_ROWS:
            result.fatal = True
            result.errors.append(
                RowError(offset, None, "too_many_rows", f"batch exceeds {MAX_ROWS} rows")
            )
            break
        if not any((value or "").strip() for value in row.values()):
            continue
        result.declared_rows += 1
        comment = _build_comment(platform, row, offset, result.errors)
        if comment is not None:
            result.comments.append(comment)
    return result


def parse_normalized(comments: list[NormalizedComment], platform: str) -> ParseResult:
    """Parse JSON comments (used by the UI / tests) through the same validation."""
    result = ParseResult()
    seen: set[tuple[str, str, str, str]] = set()
    for index, item in enumerate(comments, start=1):
        result.declared_rows += 1
        if item.platform != platform:
            result.errors.append(
                RowError(
                    index,
                    "platform",
                    "platform_mismatch",
                    "comment platform != batch platform",
                )
            )
            continue
        body = item.body.strip()
        body_hash = content_hash(body)
        comment = ParsedComment(
            platform=platform,
            shop_id=item.shop_id,
            product_id=item.product_id,
            source_review_id=item.source_review_id,
            rating=item.rating,
            review_date=item.review_date,
            body=body,
            content_hash=body_hash,
            dedupe_mode=DedupeMode.SOURCE_ID.value,
        )
        key = (comment.platform, comment.shop_id, comment.product_id, comment.source_review_id)
        if key in seen:
            result.errors.append(
                RowError(index, "source_review_id", "duplicate_row", "duplicate row inside batch")
            )
            continue
        seen.add(key)
        result.comments.append(comment)
    return result


def _active_job(db: Session, comment_id: str) -> Job | None:
    stmt = select(Job).where(
        Job.comment_id == comment_id,
        Job.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
    )
    return db.execute(stmt).scalars().first()


def _ensure_job(db: Session, comment: Comment, batch_id: str) -> bool:
    if _active_job(db, comment.id) is not None:
        return False
    db.add(
        Job(
            comment_id=comment.id,
            batch_id=batch_id,
            job_type=JobType.EXTRACT_ISSUES.value,
            status=JobStatus.PENDING.value,
        )
    )
    return True


def ingest_comments(
    db: Session,
    batch: IngestionBatch,
    comments: list[ParsedComment],
) -> IngestCounts:
    """Upsert comments and create one job per new / changed comment.

    The caller owns the transaction: the API commits batch + comments + jobs +
    error rows together.
    """
    counts = IngestCounts()
    for parsed in comments:
        stmt = select(Comment).where(
            Comment.platform == parsed.platform,
            Comment.shop_id == parsed.shop_id,
            Comment.product_id == parsed.product_id,
            Comment.source_review_id == parsed.source_review_id,
        )
        existing = db.execute(stmt).scalars().first()
        if existing is None:
            comment = Comment(
                platform=parsed.platform,
                shop_id=parsed.shop_id,
                product_id=parsed.product_id,
                source_review_id=parsed.source_review_id,
                batch_id=batch.id,
                rating=parsed.rating,
                review_date=parsed.review_date,
                body=parsed.body,
                content_hash=parsed.content_hash,
                dedupe_mode=parsed.dedupe_mode,
                analysis_status=AnalysisStatus.QUEUED.value,
            )
            db.add(comment)
            db.flush()
            _ensure_job(db, comment, batch.id)
            counts.accepted_rows += 1
            counts.job_count += 1
            continue

        counts.duplicate_rows += 1
        if existing.content_hash != parsed.content_hash:
            existing.body = parsed.body
            existing.content_hash = parsed.content_hash
            existing.rating = parsed.rating
            existing.review_date = parsed.review_date
            existing.analysis_status = AnalysisStatus.QUEUED.value
            existing.batch_id = batch.id
            last_version = db.execute(
                select(CommentRevision.version)
                .where(CommentRevision.comment_id == existing.id)
                .order_by(CommentRevision.version.desc())
                .limit(1)
            ).scalar()
            db.add(
                CommentRevision(
                    comment_id=existing.id,
                    version=(last_version or 0) + 1,
                    body=parsed.body,
                    content_hash=parsed.content_hash,
                )
            )
            if _ensure_job(db, existing, batch.id):
                counts.job_count += 1
    return counts
