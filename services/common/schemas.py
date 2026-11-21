"""Pydantic contracts shared by the API, Worker and AI service.

Contract rules (frozen before implementation):

* AI may only return ``has_issue`` + ``issues[...]`` with ``evidence_text``
  that must be a verbatim substring of the normalised comment body.
* Human decisions are never expressed by the AI contract; they use
  ``IssueActionRequest`` / ``LinkDecisionRequest``.
* ``suggested`` links are never counted as human-confirmed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.common.models import (
    AnalysisStatus,
    BatchStatus,
    HasIssue,
    IssueActionType,
    IssueStatus,
    JobStatus,
    JobType,
    LinkOrigin,
    LinkStatus,
    SourceType,
)


class HealthResponse(BaseModel):
    service: str
    status: str


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class QueryScope(BaseModel):
    """Every read/aggregate response carries the scope and the snapshot time."""

    product_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    date_basis: str = Field(default="review_date", description="review_date | received_at")
    as_of: datetime


# ---------------------------------------------------------------------------
# Ingestion contracts
# ---------------------------------------------------------------------------
class NormalizedComment(BaseModel):
    """One row after platform-specific parsing; the ingest layer writes it.

    ``source_review_id`` is required.  When the platform has no stable review id,
    the ingestion layer synthesises one (``synth:<sha1 of platform|shop|product|
    content_hash|review_date>``) and sets ``dedupe_mode=content_hash``; it must
    never invent a real-looking id.
    """

    platform: str = Field(min_length=1, max_length=32)
    shop_id: str = Field(min_length=1, max_length=64)
    product_id: str = Field(min_length=1, max_length=64)
    source_review_id: str = Field(min_length=1, max_length=128)
    rating: int | None = Field(default=None, ge=0, le=5)
    review_date: datetime | None = None
    body: str = Field(min_length=1, max_length=2000)


class BatchUploadRequest(BaseModel):
    """`POST /review-batches` body.

    The API currently accepts either inline ``comments`` or a ``csv_text``
    payload (the CSV content as a string) so it has no multipart dependency;
    a future multipart entry can post a file through the same validation path.

    Exactly one of ``comments`` / ``csv_text`` must be provided.  CSV columns:
    ``shop_id, product_id, body`` (required); ``source_review_id, review_date,
    rating`` (optional).  ``platform`` is taken from the request.
    """

    platform: str = Field(min_length=1, max_length=32)
    source_type: SourceType = SourceType.CSV
    filename: str | None = Field(default=None, max_length=255)
    idempotency_key: str | None = Field(default=None, max_length=128)
    csv_text: str | None = None
    comments: list[NormalizedComment] | None = None

    @field_validator("platform", "filename", "idempotency_key")
    @classmethod
    def _safe_upload_metadata(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\x00" in value):
            raise ValueError("upload metadata must be nonempty and contain no NUL characters")
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def _require_payload(self) -> "BatchUploadRequest":
        if bool(self.csv_text) == bool(self.comments):
            raise ValueError("provide exactly one of csv_text / comments")
        return self


class BatchCreateResponse(BaseModel):
    """202 response after validation/import; analysis runs asynchronously.

    A replay may omit ``job_count``; clients read the batch progress for current counts.
    """

    batch_id: str
    status: BatchStatus
    declared_rows: int | None = None
    accepted_rows: int = 0
    duplicate_rows: int = 0
    invalid_rows: int = 0
    job_count: int | None = None


class BatchRead(OrmModel):
    """Import-stage counters (validation / dedupe), not analysis progress."""

    id: str
    platform: str
    source_type: SourceType
    file_ref: str | None = None
    declared_rows: int | None = None
    accepted_rows: int = 0
    duplicate_rows: int = 0
    invalid_rows: int = 0
    status: BatchStatus
    created_at: datetime
    finished_at: datetime | None = None


class BatchProgressRead(BaseModel):
    """Batch progress for the UI: import counters + analysis counters (derived)."""

    batch_id: str
    batch: BatchRead
    status: BatchStatus
    job_count: int = 0
    analyzed_rows: int = 0
    failed_rows: int = 0
    pending_rows: int = 0
    processing_rows: int = 0
    current_rows: int = 0
    waiting_rows: int = 0
    failed_jobs: int = 0
    analysis_coverage: float | None = None
    scope: QueryScope


class BatchErrorRead(OrmModel):
    row_number: int
    column_name: str | None = None
    code: str
    message: str


# ---------------------------------------------------------------------------
# Comment contracts
# ---------------------------------------------------------------------------
class CommentIssueRead(OrmModel):
    id: int
    comment_id: str
    issue_id: str
    status: LinkStatus
    origin: LinkOrigin
    evidence_text: str | None = None
    evidence_start: int | None = None
    evidence_end: int | None = None
    evidence_verified: bool = False
    evidence_body_hash: str | None = None
    similarity: float | None = None
    analysis_run_id: int | None = None
    comment_version: int = 1
    superseded_at: datetime | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    # populated by the API layer when the link is returned inside a detail view
    comment_body: str | None = None


class CommentRevisionRead(OrmModel):
    id: int
    version: int
    body: str
    content_hash: str
    created_at: datetime


class AnalysisRunRead(OrmModel):
    id: int
    model_version: str
    prompt_version: str
    category_version: str
    status: str
    error_code: str | None = None
    latency_ms: int | None = None
    token_in: int | None = None
    token_out: int | None = None
    created_at: datetime


class CommentRead(OrmModel):
    id: str
    platform: str
    shop_id: str
    product_id: str
    source_review_id: str
    batch_id: str | None = None
    rating: int | None = None
    review_date: datetime | None = None
    body: str
    analysis_status: AnalysisStatus
    has_issue: HasIssue | None = None
    analysis_error: str | None = None
    created_at: datetime
    updated_at: datetime


class CommentDetailRead(CommentRead):
    issues: list[CommentIssueRead] = Field(default_factory=list)
    revisions: list[CommentRevisionRead] = Field(default_factory=list)
    latest_analysis_run: AnalysisRunRead | None = None


# ---------------------------------------------------------------------------
# Issue contracts
# ---------------------------------------------------------------------------
class IssueRead(OrmModel):
    id: str
    platform: str
    shop_id: str
    product_id: str
    category_id: str
    title: str
    status: IssueStatus
    created_by: str
    merged_into_id: str | None = None
    split_from_id: str | None = None
    version: int = 1
    reopen_count: int = 0
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # derived: accepted links are the only ones that count as problem evidence
    suggested_count: int = 0
    accepted_count: int = 0


class IssueActionRead(OrmModel):
    id: int
    issue_id: str
    comment_issue_id: int | None = None
    action: IssueActionType
    from_status: str | None = None
    to_status: str | None = None
    payload_json: dict | None = None
    operator: str | None = None
    note: str | None = None
    created_at: datetime


class IssueDetailRead(IssueRead):
    description: str | None = None
    version: int = 1
    links: list[CommentIssueRead] = Field(default_factory=list)
    actions: list[IssueActionRead] = Field(default_factory=list)


class IssueActionRequest(BaseModel):
    """All human review actions go through this immutable-audit endpoint."""

    action: IssueActionType
    expected_version: int | None = Field(
        default=None, description="optimistic lock; 409 on mismatch when provided"
    )
    comment_issue_id: int | None = None
    comment_issue_ids: list[int] | None = Field(
        default=None, description="split: links moved to the new issue(s)"
    )
    target_issue_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category_id: str | None = Field(default=None, min_length=1, max_length=40)
    payload: dict | None = None
    operator: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _require_action_fields(self) -> "IssueActionRequest":
        if self.action == IssueActionType.RENAME:
            if not self.title and not self.category_id:
                raise ValueError("rename requires title or category_id")
        if self.action == IssueActionType.MERGE_INTO and not self.target_issue_id:
            raise ValueError("merge_into requires target_issue_id")
        if self.action == IssueActionType.SPLIT and not self.comment_issue_ids:
            raise ValueError("split requires comment_issue_ids")
        if self.action in (
            IssueActionType.ACCEPT,
            IssueActionType.REJECT,
            IssueActionType.CHANGE,
        ) and not self.comment_issue_id:
            raise ValueError(f"{self.action.value} requires comment_issue_id")
        return self


class LinkDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    CHANGE = "change"


class LinkDecisionRequest(BaseModel):
    decision: LinkDecision
    operator: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)


# ---------------------------------------------------------------------------
# Job contracts
# ---------------------------------------------------------------------------
class AnalysisJobRead(OrmModel):
    id: int
    job_type: JobType
    status: JobStatus
    comment_id: str | None = None
    batch_id: str | None = None
    attempts: int
    max_attempts: int
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None
    error_code: str | None = None
    error: str | None = None
    created_at: datetime
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class StatsSummaryRead(BaseModel):
    """Counts for one product + date range; wording rules in architecture.md §11."""

    scope: QueryScope
    received_rows: int = 0
    analyzed_rows: int = 0
    failed_rows: int = 0
    processing_rows: int = 0
    issue_mention_count: int = 0
    ai_suggested_count: int = 0
    human_accepted_count: int = 0
    closed_issue_new_suggestions: int = 0
    analysis_coverage: float | None = None


# ---------------------------------------------------------------------------
# AI service contracts
# ---------------------------------------------------------------------------
class ExtractionRequest(BaseModel):
    comment_id: str
    body: str = Field(min_length=1, max_length=2000)
    product_id: str
    category_ids: list[str] = Field(default_factory=list)


class ExtractedIssue(BaseModel):
    category_id: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=500)
    evidence_text: str = Field(min_length=1, max_length=500)


class ExtractionResult(BaseModel):
    """Strict AI output.  The Worker re-validates evidence against the body."""

    comment_id: str
    has_issue: HasIssue
    issues: list[ExtractedIssue] = Field(default_factory=list)
    model_version: str = Field(min_length=1, max_length=64)
    prompt_version: str = Field(min_length=1, max_length=64)
    category_version: str = Field(default="v1", max_length=64)
    schema_version: str = Field(default="1", max_length=16)

    @model_validator(mode="after")
    def _check_issue_consistency(self) -> "ExtractionResult":
        if self.has_issue == HasIssue.NO and self.issues:
            raise ValueError("has_issue='no' requires issues=[]")
        if self.has_issue == HasIssue.YES and not self.issues:
            raise ValueError("has_issue='yes' requires at least one issue")
        for issue in self.issues:
            if not issue.evidence_text.strip():
                raise ValueError("evidence_text must not be blank")
        return self


class GroupingAction(StrEnum):
    LINK_EXISTING = "link_existing"
    CREATE_NEW = "create_new"


class GroupSuggestionRequest(BaseModel):
    """Same-product grouping hint; the Worker still applies it transactionally."""

    product_id: str
    category_id: str
    candidate_text: str = Field(min_length=1, max_length=500)
    existing_issue_ids: list[str] = Field(default_factory=list)


class GroupSuggestionResult(BaseModel):
    action: GroupingAction
    issue_id: str | None = None
    similar_issue_ids: list[str] = Field(default_factory=list)
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _check_action(self) -> "GroupSuggestionResult":
        if self.action == GroupingAction.LINK_EXISTING and not self.issue_id:
            raise ValueError("link_existing requires issue_id")
        return self


# Human decisions distinguish first review from an explicit revision of a prior decision.
class ReviewDecisionMode(StrEnum):
    INITIAL = "initial"
    REVISE = "revise"


class ReviewDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    decision: LinkDecision
    mode: ReviewDecisionMode = ReviewDecisionMode.INITIAL
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _validate_decision(self) -> "ReviewDecisionRequest":
        from uuid import UUID

        self.request_id = str(UUID(self.request_id))
        if self.decision == LinkDecision.CHANGE:
            raise ValueError("decision must specify accept or reject; use reassign for regrouping")
        if self.mode == ReviewDecisionMode.REVISE and not self.note:
            raise ValueError("revising a decision requires a reason")
        if self.decision == LinkDecision.REJECT and not self.note:
            raise ValueError("rejection requires a reason")
        return self


class ReviewRead(BaseModel):
    link: CommentIssueRead
    comment: CommentRead
    issue: IssueRead
    review_version: int
    token: str
    can_decide: bool
    can_revise: bool = False
    can_reassign: bool = False
    needs_recheck: bool = False
    can_recheck: bool = False
    recheck_blocked_reason: str | None = None
    evidence_body: str | None = None
    reassign_blocked_reason: str | None = None
    revision_blocked_reason: str | None = None
    blocked_reason: str | None = None
    actions: list[IssueActionRead] = Field(default_factory=list)


class ReviewQueueRead(BaseModel):
    items: list[ReviewRead]
    total: int
    limit: int
    offset: int
    operator: str
    identity_mode: str = "demo"


class ReviewDecisionRead(BaseModel):
    action_id: int
    request_id: str
    link_id: int
    status: LinkStatus
    review_version: int
    operator: str
    decided_at: datetime


class ReassignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_issue_id: str = Field(min_length=1, max_length=36)
    expected_target_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _normalize_request_id(self) -> "ReassignRequest":
        from uuid import UUID

        self.request_id = str(UUID(self.request_id))
        return self


class ReassignTargetRead(BaseModel):
    issue: IssueRead
    token: str
    existing_link_id: int | None = None
    existing_link_status: LinkStatus | None = None
    selectable: bool
    blocked_reason: str | None = None


class ReassignTargetsRead(BaseModel):
    items: list[ReassignTargetRead]
    total: int
    limit: int
    offset: int


class ReassignRead(BaseModel):
    request_id: str
    source_link_id: int
    target_link_id: int
    source_issue_id: str
    target_issue_id: str
    source_action_id: int
    target_action_id: int
    operator: str
    decided_at: datetime


class ManualIssueCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    category_id: str

    @field_validator("category_id")
    @classmethod
    def _category(cls, value):
        from services.common.categories import is_valid_category
        if not is_valid_category(value):
            raise ValueError("unknown category")
        return value


class ManualLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_issue_id: str | None = Field(default=None, min_length=1, max_length=36)
    expected_target_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    new_issue: ManualIssueCreate | None = None
    evidence_text: str = Field(min_length=1, max_length=2000)
    evidence_start: int = Field(ge=0, le=2000, strict=True)
    evidence_end: int = Field(gt=0, le=2000, strict=True)
    note: str = Field(min_length=1, max_length=500)

    @field_validator("note", mode="before")
    @classmethod
    def _strip_note(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate(self):
        from uuid import UUID
        self.request_id = str(UUID(self.request_id))
        if bool(self.target_issue_id) == bool(self.new_issue):
            raise ValueError("choose an existing issue or create one, exclusively")
        if bool(self.target_issue_id) != bool(self.expected_target_token):
            raise ValueError("existing target requires its token")
        if not self.evidence_text.strip() or self.evidence_start >= self.evidence_end:
            raise ValueError("provide a nonempty verbatim evidence span")
        return self


class ManualCommentRead(BaseModel):
    comment: CommentRead
    token: str
    can_add: bool
    blocked_reason: str | None = None
    links: list[ReviewRead]


class ManualCommentQueueRead(BaseModel):
    items: list[CommentRead]
    total: int
    limit: int
    offset: int
    operator: str


class ManualLinkRead(BaseModel):
    request_id: str
    link_id: int
    issue_id: str
    action_id: int
    created_issue: bool
    operator: str
    decided_at: datetime


class IssueWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    action: Literal["confirm", "follow_up", "resolve", "dismiss", "reopen"]
    note: str = Field(min_length=1, max_length=500)

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, value):
        from uuid import UUID
        return str(UUID(value))


class IssueWorkflowRead(BaseModel):
    issue: IssueRead
    token: str
    valid_accepted_count: int
    invalid_accepted_count: int
    evidence_total: int
    allowed_actions: list[str]
    blocked_actions: dict[str, str]
    actions: list[IssueActionRead] = Field(default_factory=list)
    active_link_count: int = 0
    can_restructure: bool = False


class IssueWorkflowQueueRead(BaseModel):
    items: list[IssueWorkflowRead]
    total: int
    limit: int
    offset: int
    operator: str


class IssueEvidenceRead(BaseModel):
    review: ReviewRead
    usable: bool
    blocked_reason: str | None = None


class IssueEvidencePage(BaseModel):
    items: list[IssueEvidenceRead]
    total: int
    limit: int
    offset: int


class IssueWorkflowActionRead(BaseModel):
    request_id: str
    issue_id: str
    action_id: int
    action: str
    status: IssueStatus
    version: int
    operator: str
    created_at: datetime


class IssueStructureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(min_length=1, max_length=500)

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, value):
        from uuid import UUID
        return str(UUID(value))


class IssueMergeRequest(IssueStructureRequest):
    target_issue_id: str = Field(min_length=1, max_length=36)
    expected_target_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class IssueSplitRequest(IssueStructureRequest):
    comment_issue_ids: list[int] = Field(min_length=1, max_length=100)
    new_issue: ManualIssueCreate

    @field_validator("comment_issue_ids", mode="before")
    @classmethod
    def _ids(cls, value):
        if not isinstance(value, list) or any(type(i) is not int or i < 1 for i in value):
            raise ValueError("positive integer link IDs required")
        if len(value) != len(set(value)):
            raise ValueError("duplicate link IDs")
        return sorted(value)


class IssueMergeConflict(BaseModel):
    source_link_id: int
    target_link_id: int
    comment_id: str
    reason: str


class IssueMergeTargetRead(BaseModel):
    target: IssueWorkflowRead
    copied_count: int
    deduplicated_count: int
    reactivated_count: int
    conflicts: list[IssueMergeConflict]
    selectable: bool


class IssueMergeTargetsRead(BaseModel):
    items: list[IssueMergeTargetRead]
    total: int
    limit: int
    offset: int


class IssueStructureRead(BaseModel):
    request_id: str
    operation: Literal["merge", "split"]
    source_issue_id: str
    target_issue_id: str
    source_action_id: int
    target_action_id: int
    copied_count: int
    deduplicated_count: int
    reactivated_count: int
    operator: str
    created_at: datetime


class ReviewRecheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    expected_token: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["accept", "reject"]
    note: str = Field(min_length=1, max_length=500)
    evidence_text: str | None = Field(default=None, min_length=1, max_length=2000)
    evidence_start: int | None = Field(default=None, ge=0, le=2000, strict=True)
    evidence_end: int | None = Field(default=None, gt=0, le=2000, strict=True)

    @field_validator("note", mode="before")
    @classmethod
    def _note(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _validate(self):
        from uuid import UUID
        self.request_id = str(UUID(self.request_id))
        parts = (self.evidence_text, self.evidence_start, self.evidence_end)
        if any(p is not None for p in parts):
            if any(p is None for p in parts):
                raise ValueError("provide the whole evidence span")
            if not self.evidence_text.strip() or self.evidence_start >= self.evidence_end:
                raise ValueError("nonempty evidence span required")
        elif self.decision == "accept":
            raise ValueError("acceptance requires current verbatim evidence")
        return self


class ReviewRecheckRead(ReviewDecisionRead):
    issue_id: str
    issue_action_id: int
    issue_status: IssueStatus
    issue_version: int
