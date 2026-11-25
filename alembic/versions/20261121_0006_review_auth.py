"""Persist review accounts, revocable sessions and shared login throttles."""

import sqlalchemy as sa
from alembic import op

revision = "20261121_0006"
down_revision = "20261121_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('viewer', 'reviewer')", name="ck_review_users_role"),
    )
    op.create_table(
        "review_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("review_users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_review_sessions_user_id", "review_sessions", ["user_id"])
    op.create_index("ix_review_sessions_expires_at", "review_sessions", ["expires_at"])
    op.create_table(
        "review_login_throttles",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("review_login_throttles")
    op.drop_table("review_sessions")
    op.drop_table("review_users")
