"""Record automatic grouping separately from human decisions."""
import sqlalchemy as sa
from alembic import op

revision = '20261126_0009'
down_revision = '20261126_0008'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('comment_issues', sa.Column('auto_confirmed', sa.Boolean(),
                                             nullable=False, server_default=sa.false()))


def downgrade():
    if op.get_bind().execute(sa.text(
        'SELECT 1 FROM comment_issues WHERE auto_confirmed = true LIMIT 1'
    )).first():
        raise RuntimeError('Automatic decisions exist; restore a backup to revert.')
    op.drop_column('comment_issues', 'auto_confirmed')
