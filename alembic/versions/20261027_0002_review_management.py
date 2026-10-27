"""review management tables and job extension

Revision ID: 20261027_0002
Revises: 20260713_0001
Create Date: 2026-10-27

Adds the review-management domain from ``docs/architecture.md``:

* ``ingestion_batches`` / ``batch_rows`` — upload, validation and error report
* ``comments`` / ``comment_revisions`` — source comments and body history
* ``analysis_runs`` — one row per AI execution (model / prompt / raw output)
* ``issues`` / ``comment_issues`` / ``issue_actions`` — issue groups,
  per-comment links with evidence, append-only review audit
* ``jobs`` — one analysis job per comment, retry and lease bookkeeping

The legacy ``cases`` table is intentionally **not** dropped here; the API /
Worker still use it until the follow-up removal PR (migration 0003).  The FK
``jobs.case_id`` therefore stays, but becomes nullable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261027_0002"
down_revision = "20260713_0001"
branch_labels = None
depends_on = None


ANALYSIS_STATUSES = "'received', 'queued', 'analyzing', 'analyzed', 'failed'"
HAS_ISSUE_VALUES = "'yes', 'no', 'unknown'"
DEDUPE_MODES = "'source_id', 'content_hash'"
BATCH_STATUSES = "'received', 'validating', 'rejected', 'imported', 'completed', 'partially_failed'"
SOURCE_TYPES = "'csv', 'api'"
ISSUE_STATUSES = "'proposed', 'confirmed', 'resolved', 'dismissed'"
LINK_STATUSES = "'suggested', 'accepted', 'rejected'"
LINK_ORIGINS = "'ai', 'human'"
RUN_STATUSES = "'succeeded', 'failed'"
ISSUE_ACTIONS = (
    "'confirm', 'dismiss', 'reopen', 'rename', 'merge_into', 'split', "
    "'follow_up', 'resolve', 'accept', 'reject', 'change'"
)

# BIGINT primary keys are not rowid aliases on SQLite (only ``INTEGER PRIMARY
# KEY`` is), so tests that use ``Base.metadata.create_all`` need INTEGER there;
# PostgreSQL still gets BIGSERIAL.  Alembic migrations themselves target
# PostgreSQL (ALTER TABLE ... ADD CONSTRAINT is not supported by SQLite).
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    # ---------------------------------------------------------------- batches
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False, server_default="csv"),
        sa.Column("file_ref", sa.String(length=255), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("declared_rows", sa.Integer(), nullable=True),
        sa.Column("accepted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="received"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("resubmitted_from_batch_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["resubmitted_from_batch_id"], ["ingestion_batches.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_ingestion_batches_idempotency_key"),
        sa.CheckConstraint(
            f"source_type IN ({SOURCE_TYPES})", name="ck_ingestion_batches_source_type"
        ),
        sa.CheckConstraint(f"status IN ({BATCH_STATUSES})", name="ck_ingestion_batches_status"),
    )
    op.create_index(
        "ix_ingestion_batches_status_created_at", "ingestion_batches", ["status", "created_at"]
    )

    # --------------------------------------------------------------- comments
    op.create_table(
        "comments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.String(length=64), nullable=False),
        sa.Column("source_review_id", sa.String(length=128), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("dedupe_mode", sa.String(length=20), nullable=False, server_default="source_id"),
        sa.Column("duplicate_of_id", sa.String(length=36), nullable=True),
        sa.Column(
            "analysis_status", sa.String(length=20), nullable=False, server_default="received"
        ),
        sa.Column("has_issue", sa.String(length=10), nullable=True),
        sa.Column("current_analysis_run_id", sa.BigInteger(), nullable=True),
        sa.Column("analysis_error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ingestion_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["comments.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "platform", "shop_id", "product_id", "source_review_id", name="uq_comments_source"
        ),
        sa.CheckConstraint(
            f"analysis_status IN ({ANALYSIS_STATUSES})", name="ck_comments_analysis_status"
        ),
        sa.CheckConstraint(
            f"has_issue IS NULL OR has_issue IN ({HAS_ISSUE_VALUES})",
            name="ck_comments_has_issue",
        ),
        sa.CheckConstraint(f"dedupe_mode IN ({DEDUPE_MODES})", name="ck_comments_dedupe_mode"),
    )
    op.create_index("ix_comments_product_review_date", "comments", ["product_id", "review_date"])
    op.create_index("ix_comments_analysis_status", "comments", ["analysis_status"])
    op.create_index("ix_comments_batch_id", "comments", ["batch_id"])

    op.create_table(
        "comment_revisions",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("comment_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("comment_id", "version", name="uq_comment_revisions_version"),
    )

    # ------------------------------------------------------------- batch rows
    op.create_table(
        "batch_rows",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(length=64), nullable=True),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("message", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["ingestion_batches.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_batch_rows_batch_row", "batch_rows", ["batch_id", "row_number"])

    # ----------------------------------------------------------- analysis runs
    op.create_table(
        "analysis_runs",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("comment_id", sa.String(length=36), nullable=False),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("category_version", sa.String(length=64), nullable=False, server_default="v1"),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("output_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_in", sa.Integer(), nullable=True),
        sa.Column("token_out", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.CheckConstraint(f"status IN ({RUN_STATUSES})", name="ck_analysis_runs_status"),
    )
    op.create_index(
        "ix_analysis_runs_comment_created_at", "analysis_runs", ["comment_id", "created_at"]
    )

    # ---------------------------------------------------------------- issues
    op.create_table(
        "issues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("shop_id", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.String(length=64), nullable=False),
        sa.Column("category_id", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("created_by", sa.String(length=10), nullable=False, server_default="ai"),
        sa.Column("merged_into_id", sa.String(length=36), nullable=True),
        sa.Column("split_from_id", sa.String(length=36), nullable=True),
        sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["merged_into_id"], ["issues.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["split_from_id"], ["issues.id"], ondelete="SET NULL"),
        sa.CheckConstraint(f"status IN ({ISSUE_STATUSES})", name="ck_issues_status"),
        sa.CheckConstraint("created_by IN ('ai', 'human')", name="ck_issues_created_by"),
    )
    op.create_index("ix_issues_product_status", "issues", ["product_id", "status"])
    op.create_index("ix_issues_product_category", "issues", ["product_id", "category_id"])
    op.create_index("ix_issues_status_updated_at", "issues", ["status", "updated_at"])

    # --------------------------------------------------------- comment issues
    op.create_table(
        "comment_issues",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("comment_id", sa.String(length=36), nullable=False),
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="suggested"),
        sa.Column("origin", sa.String(length=10), nullable=False, server_default="ai"),
        sa.Column("evidence_text", sa.Text(), nullable=True),
        sa.Column("evidence_start", sa.Integer(), nullable=True),
        sa.Column("evidence_end", sa.Integer(), nullable=True),
        sa.Column("evidence_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("similarity", sa.Float(), nullable=True),
        sa.Column("analysis_run_id", sa.BigInteger(), nullable=True),
        sa.Column("comment_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["comments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_run_id"], ["analysis_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("comment_id", "issue_id", name="uq_comment_issues_pair"),
        sa.CheckConstraint(f"status IN ({LINK_STATUSES})", name="ck_comment_issues_status"),
        sa.CheckConstraint(f"origin IN ({LINK_ORIGINS})", name="ck_comment_issues_origin"),
    )
    op.create_index("ix_comment_issues_issue_status", "comment_issues", ["issue_id", "status"])
    op.create_index(
        "ix_comment_issues_analysis_run_id", "comment_issues", ["analysis_run_id"]
    )

    # --------------------------------------------------------- issue actions
    op.create_table(
        "issue_actions",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("comment_issue_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("operator", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["comment_issue_id"], ["comment_issues.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(f"action IN ({ISSUE_ACTIONS})", name="ck_issue_actions_action"),
    )
    op.create_index(
        "ix_issue_actions_issue_created_at", "issue_actions", ["issue_id", "created_at"]
    )

    # ------------------------------------------------------- jobs (extended)
    op.alter_column("jobs", "case_id", existing_type=sa.String(length=36), nullable=True)
    op.add_column("jobs", sa.Column("comment_id", sa.String(length=36), nullable=True))
    op.add_column("jobs", sa.Column("batch_id", sa.String(length=36), nullable=True))
    op.add_column(
        "jobs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column("jobs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("error_code", sa.String(length=40), nullable=True))
    op.create_foreign_key(
        "fk_jobs_comment_id", "jobs", "comments", ["comment_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_jobs_batch_id", "jobs", "ingestion_batches", ["batch_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_jobs_status_next_attempt_at", "jobs", ["status", "next_attempt_at"])
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])
    op.create_check_constraint(
        "ck_jobs_target", "jobs", "case_id IS NOT NULL OR comment_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_jobs_status", "jobs", "status IN ('pending', 'claimed', 'completed', 'failed')"
    )
    op.create_check_constraint(
        "ck_jobs_job_type", "jobs", "job_type IN ('extract_issues', 'triage_case')"
    )
    op.create_check_constraint(
        "ck_jobs_type_target",
        "jobs",
        "(job_type = 'extract_issues' AND comment_id IS NOT NULL)"
        " OR (job_type = 'triage_case' AND case_id IS NOT NULL)",
    )
    # At most one non-terminal job per comment (partial unique index).
    op.create_index(
        "uq_jobs_active_comment",
        "jobs",
        ["comment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'claimed')"),
        sqlite_where=sa.text("status IN ('pending', 'claimed')"),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_active_comment", table_name="jobs")
    op.drop_constraint("ck_jobs_type_target", "jobs", type_="check")
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.drop_constraint("ck_jobs_status", "jobs", type_="check")
    op.drop_constraint("ck_jobs_target", "jobs", type_="check")
    op.drop_index("ix_jobs_batch_id", table_name="jobs")
    op.drop_index("ix_jobs_status_next_attempt_at", table_name="jobs")
    op.drop_constraint("fk_jobs_batch_id", "jobs", type_="foreignkey")
    op.drop_constraint("fk_jobs_comment_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "error_code")
    op.drop_column("jobs", "lease_expires_at")
    op.drop_column("jobs", "next_attempt_at")
    op.drop_column("jobs", "max_attempts")
    op.drop_column("jobs", "batch_id")
    op.drop_column("jobs", "comment_id")

    # Comment jobs cannot be represented without comment_id: remove them, then
    # restore the legacy NOT NULL constraint on jobs.case_id.
    op.execute(sa.text("DELETE FROM jobs WHERE case_id IS NULL"))
    op.alter_column("jobs", "case_id", existing_type=sa.String(length=36), nullable=False)

    op.drop_index("ix_issue_actions_issue_created_at", table_name="issue_actions")
    op.drop_table("issue_actions")
    op.drop_index("ix_comment_issues_analysis_run_id", table_name="comment_issues")
    op.drop_index("ix_comment_issues_issue_status", table_name="comment_issues")
    op.drop_table("comment_issues")
    op.drop_index("ix_issues_status_updated_at", table_name="issues")
    op.drop_index("ix_issues_product_category", table_name="issues")
    op.drop_index("ix_issues_product_status", table_name="issues")
    op.drop_table("issues")
    op.drop_index("ix_analysis_runs_comment_created_at", table_name="analysis_runs")
    op.drop_table("analysis_runs")
    op.drop_index("ix_batch_rows_batch_row", table_name="batch_rows")
    op.drop_table("batch_rows")
    op.drop_table("comment_revisions")
    op.drop_index("ix_comments_batch_id", table_name="comments")
    op.drop_index("ix_comments_analysis_status", table_name="comments")
    op.drop_index("ix_comments_product_review_date", table_name="comments")
    op.drop_table("comments")
    op.drop_index(
        "ix_ingestion_batches_status_created_at", table_name="ingestion_batches"
    )
    op.drop_table("ingestion_batches")
