"""Stop, recycle and purge batch-scoped work."""

import sqlalchemy as sa
from alembic import op

revision = "20261126_0008"
down_revision = "20261126_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ingestion_batches", sa.Column("stopped_at", sa.DateTime(timezone=True)))
    op.add_column("ingestion_batches", sa.Column("deleted_at", sa.DateTime(timezone=True)))
    op.create_index("ix_ingestion_batches_deleted_at", "ingestion_batches", ["deleted_at"])
    for table, name, column, values in [
        (
            "comments",
            "ck_comments_analysis_status",
            "analysis_status",
            ["received", "queued", "analyzing", "analyzed", "failed", "cancelled"],
        ),
        (
            "jobs",
            "ck_jobs_status",
            "status",
            ["pending", "claimed", "completed", "failed", "cancelled"],
        ),
        (
            "ingestion_batches",
            "ck_ingestion_batches_status",
            "status",
            [
                "received",
                "validating",
                "rejected",
                "imported",
                "completed",
                "partially_failed",
                "stopped",
            ],
        ),
    ]:
        op.drop_constraint(name, table, type_="check")
        expression = column + " IN (" + ",".join(repr(value) for value in values) + ")"
        op.create_check_constraint(name, table, expression)


def downgrade():
    conn = op.get_bind()
    if conn.execute(
        sa.text(
            "SELECT 1 FROM ingestion_batches WHERE stopped_at IS NOT NULL "
            "OR deleted_at IS NOT NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError("Batch lifecycle history exists; restore a backup to revert.")
    for table, name, column, values in [
        (
            "comments",
            "ck_comments_analysis_status",
            "analysis_status",
            ["received", "queued", "analyzing", "analyzed", "failed"],
        ),
        ("jobs", "ck_jobs_status", "status", ["pending", "claimed", "completed", "failed"]),
        (
            "ingestion_batches",
            "ck_ingestion_batches_status",
            "status",
            ["received", "validating", "rejected", "imported", "completed", "partially_failed"],
        ),
    ]:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(
            name, table, column + " IN (" + ",".join(map(repr, values)) + ")"
        )
    op.drop_index("ix_ingestion_batches_deleted_at", table_name="ingestion_batches")
    op.drop_column("ingestion_batches", "stopped_at")
    op.drop_column("ingestion_batches", "deleted_at")
