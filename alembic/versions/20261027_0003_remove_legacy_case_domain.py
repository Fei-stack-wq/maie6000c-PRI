"""remove legacy case/triage domain and finalise jobs

Revision ID: 20261027_0003
Revises: 20261027_0002
Create Date: 2026-10-27

The review-management system replaces the starter case/triage domain.  This
migration deletes the legacy jobs (they have no comment), drops ``cases`` and
``jobs.case_id``, makes ``jobs.comment_id`` required and narrows the job type
check to ``extract_issues``.

Upgrading from an empty database therefore ends with exactly the schema in
``docs/architecture.md`` §6 (no legacy tables).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261027_0003"
down_revision = "20261027_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Legacy jobs cannot be represented in the new domain: remove them first.
    op.execute(sa.text("DELETE FROM jobs WHERE comment_id IS NULL"))

    op.drop_index("ix_jobs_case_id", table_name="jobs")
    op.drop_constraint("jobs_case_id_fkey", "jobs", type_="foreignkey")
    op.drop_constraint("ck_jobs_target", "jobs", type_="check")
    op.drop_constraint("ck_jobs_type_target", "jobs", type_="check")
    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")

    op.alter_column(
        "jobs", "comment_id", existing_type=sa.String(length=36), nullable=False
    )
    op.drop_column("jobs", "case_id")

    op.create_check_constraint("ck_jobs_job_type", "jobs", "job_type IN ('extract_issues')")
    op.drop_table("cases")


def downgrade() -> None:
    # Recreate the legacy case table (same shape as migration 0001).
    op.create_table(
        "cases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("ai_label", sa.String(length=50), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cases_status", "cases", ["status"], unique=False)

    op.drop_constraint("ck_jobs_job_type", "jobs", type_="check")
    op.create_check_constraint(
        "ck_jobs_job_type", "jobs", "job_type IN ('extract_issues', 'triage_case')"
    )
    op.add_column("jobs", sa.Column("case_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "jobs_case_id_fkey", "jobs", "cases", ["case_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_jobs_case_id", "jobs", ["case_id"], unique=False)
    op.alter_column(
        "jobs", "comment_id", existing_type=sa.String(length=36), nullable=True
    )
    op.create_check_constraint(
        "ck_jobs_target", "jobs", "case_id IS NOT NULL OR comment_id IS NOT NULL"
    )
    op.create_check_constraint(
        "ck_jobs_type_target",
        "jobs",
        "(job_type = 'extract_issues' AND comment_id IS NOT NULL)"
        " OR (job_type = 'triage_case' AND case_id IS NOT NULL)",
    )
