"""Versioned human decisions and idempotent audit receipts.

Existing decisions and unavailable historical text are left unchanged.
"""
import sqlalchemy as sa
from alembic import op

revision = "20261121_0004"
down_revision = "20261027_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("comment_issues", sa.Column(
        "review_version", sa.Integer(), nullable=False, server_default="1",
    ))
    op.add_column("issue_actions", sa.Column("request_id", sa.String(36), nullable=True))
    op.add_column("issue_actions", sa.Column("request_hash", sa.String(64), nullable=True))
    op.add_column("issue_actions", sa.Column("result_json", sa.JSON(), nullable=True))
    op.create_unique_constraint("uq_issue_actions_request_id", "issue_actions", ["request_id"])


def downgrade():
    op.drop_constraint("uq_issue_actions_request_id", "issue_actions", type_="unique")
    for column in ("result_json", "request_hash", "request_id"):
        op.drop_column("issue_actions", column)
    op.drop_column("comment_issues", "review_version")
