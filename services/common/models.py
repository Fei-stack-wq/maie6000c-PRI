"""SQLAlchemy ORM models for the review-management system.

The schema follows ``docs/architecture.md`` §6:

    ingestion_batches, batch_rows, comments, comment_revisions,
    jobs, analysis_runs, issues, comment_issues, issue_actions

``jobs`` is one analysis job per comment (``comment_id`` is required).
The legacy case/triage domain was removed by migration ``20261027_0003``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from services.common.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ``BIGINT`` primary keys break SQLite autoincrement (it only aliases
# ``INTEGER PRIMARY KEY``), while tests run on SQLite.  Use INTEGER there.
BigIntPK = BigInteger().with_variant(Integer, "sqlite")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class AnalysisStatus(StrEnum):
    """Lifecycle of one comment's analysis (mirrors ``jobs`` but per comment)."""

    RECEIVED = "received"
    QUEUED = "queued"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    FAILED = "failed"


class HasIssue(StrEnum):
    """AI verdict: concrete issue(s) found / none / cannot tell."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class IssueStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class LinkStatus(StrEnum):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class LinkOrigin(StrEnum):
    AI = "ai"
    HUMAN = "human"


class IssueActionType(StrEnum):
    CONFIRM = "confirm"
    DISMISS = "dismiss"
    REOPEN = "reopen"
    RENAME = "rename"
    MERGE_INTO = "merge_into"
    SPLIT = "split"
    FOLLOW_UP = "follow_up"
    RESOLVE = "resolve"
    ACCEPT = "accept"
    REJECT = "reject"
    CHANGE = "change"


class BatchStatus(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    REJECTED = "rejected"
    IMPORTED = "imported"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"


class JobStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(StrEnum):
    EXTRACT_ISSUES = "extract_issues"


class ErrorCode(StrEnum):
    AI_TIMEOUT = "ai_timeout"
    AI_ERROR = "ai_error"
    AI_INVALID_OUTPUT = "ai_invalid_output"
    DB_ERROR = "db_error"
    LEASE_EXPIRED = "lease_expired"
    COMMENT_NOT_FOUND = "comment_not_found"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    CSV = "csv"
    API = "api"


class DedupeMode(StrEnum):
    SOURCE_ID = "source_id"
    CONTENT_HASH = "content_hash"


def _check_in(column: str, values: tuple[str, ...], allow_null: bool = False) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    if allow_null:
        return f"{column} IS NULL OR {column} IN ({quoted})"
    return f"{column} IN ({quoted})"


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------
class IngestionBatch(Base):
    """One upload / pull request; errors and counters live here."""

    __tablename__ = "ingestion_batches"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_ingestion_batches_idempotency_key"),
        CheckConstraint(
            _check_in("source_type", tuple(s.value for s in SourceType)),
            name="ck_ingestion_batches_source_type",
        ),
        CheckConstraint(
            _check_in("status", tuple(s.value for s in BatchStatus)),
            name="ck_ingestion_batches_status",
        ),
        Index("ix_ingestion_batches_status_created_at", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default=SourceType.CSV.value
    )
    file_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invalid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=BatchStatus.RECEIVED.value
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resubmitted_from_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    rows: Mapped[list["BatchRow"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class BatchRow(Base):
    """One rejected CSV row: line number + field + machine code + message."""

    __tablename__ = "batch_rows"
    __table_args__ = (Index("ix_batch_rows_batch_row", "batch_id", "row_number"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    batch: Mapped[IngestionBatch] = relationship(back_populates="rows")


# ---------------------------------------------------------------------------
# Comments (facts)
# ---------------------------------------------------------------------------
class Comment(Base):
    """A source comment. Body/source are facts; analysis results are derived."""

    __tablename__ = "comments"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "shop_id",
            "product_id",
            "source_review_id",
            name="uq_comments_source",
        ),
        CheckConstraint(
            _check_in("analysis_status", tuple(s.value for s in AnalysisStatus)),
            name="ck_comments_analysis_status",
        ),
        CheckConstraint(
            _check_in("has_issue", tuple(s.value for s in HasIssue), allow_null=True),
            name="ck_comments_has_issue",
        ),
        CheckConstraint(
            _check_in("dedupe_mode", tuple(s.value for s in DedupeMode)),
            name="ck_comments_dedupe_mode",
        ),
        Index("ix_comments_product_review_date", "product_id", "review_date"),
        Index("ix_comments_analysis_status", "analysis_status"),
        Index("ix_comments_batch_id", "batch_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="SET NULL"), nullable=True
    )
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dedupe_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DedupeMode.SOURCE_ID.value
    )
    duplicate_of_id: Mapped[str | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    analysis_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AnalysisStatus.RECEIVED.value
    )
    has_issue: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # No FK: analysis_runs references comments, a FK back would be circular.
    current_analysis_run_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    analysis_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    revisions: Mapped[list["CommentRevision"]] = relationship(
        back_populates="comment", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="comment", passive_deletes=True)
    issue_links: Mapped[list["CommentIssue"]] = relationship(
        back_populates="comment", passive_deletes=True
    )

    @property
    def issues(self) -> list["CommentIssue"]:
        """Read alias used by ``CommentDetailRead`` (Pydantic from_attributes)."""
        return self.issue_links


class CommentRevision(Base):
    """Append-only history of the comment body (detects source edits)."""

    __tablename__ = "comment_revisions"
    __table_args__ = (
        UniqueConstraint("comment_id", "version", name="uq_comment_revisions_version"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    comment: Mapped[Comment] = relationship(back_populates="revisions")


# ---------------------------------------------------------------------------
# Analysis runs (reproducibility)
# ---------------------------------------------------------------------------
class AnalysisRun(Base):
    """One AI execution for one comment; keeps model / prompt / output."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            _check_in("status", ("succeeded", "failed")), name="ck_analysis_runs_status"
        ),
        Index("ix_analysis_runs_comment_created_at", "comment_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    category_version: Mapped[str] = mapped_column(String(64), nullable=False, default="v1")
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# ---------------------------------------------------------------------------
# Issues (derived, human-confirmed)
# ---------------------------------------------------------------------------
class Issue(Base):
    """A candidate problem group inside one product."""

    __tablename__ = "issues"
    __table_args__ = (
        CheckConstraint(
            _check_in("status", tuple(s.value for s in IssueStatus)),
            name="ck_issues_status",
        ),
        CheckConstraint(_check_in("created_by", ("ai", "human")), name="ck_issues_created_by"),
        Index("ix_issues_product_status", "product_id", "status"),
        Index("ix_issues_product_category", "product_id", "category_id"),
        Index("ix_issues_status_updated_at", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    shop_id: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False)
    category_id: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IssueStatus.PROPOSED.value
    )
    created_by: Mapped[str] = mapped_column(String(10), nullable=False, default="ai")
    merged_into_id: Mapped[str | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    split_from_id: Mapped[str | None] = mapped_column(
        ForeignKey("issues.id", ondelete="SET NULL"), nullable=True
    )
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    issue_links: Mapped[list["CommentIssue"]] = relationship(
        back_populates="issue", passive_deletes=True
    )
    actions: Mapped[list["IssueAction"]] = relationship(
        back_populates="issue", cascade="all, delete-orphan"
    )

    @property
    def links(self) -> list["CommentIssue"]:
        """Read alias used by ``IssueDetailRead`` (Pydantic from_attributes)."""
        return self.issue_links


class CommentIssue(Base):
    """Current link between one comment and one issue, with evidence."""

    __tablename__ = "comment_issues"
    __table_args__ = (
        UniqueConstraint("comment_id", "issue_id", name="uq_comment_issues_pair"),
        CheckConstraint(
            _check_in("status", tuple(s.value for s in LinkStatus)),
            name="ck_comment_issues_status",
        ),
        CheckConstraint(
            _check_in("origin", tuple(s.value for s in LinkOrigin)),
            name="ck_comment_issues_origin",
        ),
        Index("ix_comment_issues_issue_status", "issue_id", "status"),
        Index("ix_comment_issues_analysis_run_id", "analysis_run_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    issue_id: Mapped[str] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default=LinkStatus.SUGGESTED.value
    )
    origin: Mapped[str] = mapped_column(String(10), nullable=False, default=LinkOrigin.AI.value)
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True
    )
    comment_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    comment: Mapped[Comment] = relationship(back_populates="issue_links")
    issue: Mapped[Issue] = relationship(back_populates="issue_links")


class IssueAction(Base):
    """Append-only audit log of every human review action."""

    __tablename__ = "issue_actions"
    __table_args__ = (
        CheckConstraint(
            _check_in("action", tuple(a.value for a in IssueActionType)),
            name="ck_issue_actions_action",
        ),
        Index("ix_issue_actions_issue_created_at", "issue_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    issue_id: Mapped[str] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    comment_issue_id: Mapped[int | None] = mapped_column(
        ForeignKey("comment_issues.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    operator: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    issue: Mapped[Issue] = relationship(back_populates="actions")


# ---------------------------------------------------------------------------
# Jobs (extended in 0002: one job per comment, retry + lease fields)
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'claimed', 'completed', 'failed')", name="ck_jobs_status"
        ),
        CheckConstraint("job_type IN ('extract_issues')", name="ck_jobs_job_type"),
        Index("ix_jobs_status_next_attempt_at", "status", "next_attempt_at"),
        Index("ix_jobs_batch_id", "batch_id"),
        Index(
            "uq_jobs_active_comment",
            "comment_id",
            unique=True,
            postgresql_where=text("status IN ('pending', 'claimed')"),
            sqlite_where=text("status IN ('pending', 'claimed')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    comment_id: Mapped[str] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=False
    )
    batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("ingestion_batches.id", ondelete="SET NULL"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default=JobType.EXTRACT_ISSUES.value
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JobStatus.PENDING.value, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    comment: Mapped["Comment"] = relationship(back_populates="jobs")
