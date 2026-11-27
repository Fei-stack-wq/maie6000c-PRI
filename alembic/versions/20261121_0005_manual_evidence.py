"""Anchor manual evidence to exact source text independently of AI analysis."""
import sqlalchemy as sa
from alembic import op

revision = "20261121_0005"
down_revision = "20261121_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("comment_issues", sa.Column("evidence_body_hash", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("comment_issues", "evidence_body_hash")
