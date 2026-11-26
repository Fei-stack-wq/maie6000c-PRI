"""Track one-time, local repair of unreviewed legacy groups."""
import sqlalchemy as sa
from alembic import op

revision = '20261126_0010'
down_revision = '20261126_0009'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('ingestion_batches', sa.Column('grouping_policy_version', sa.Integer(),
                                                nullable=False, server_default='0'))


def downgrade():
    op.drop_column('ingestion_batches', 'grouping_policy_version')
