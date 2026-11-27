"""Keep upload snapshots and issue memberships independent across batches."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "20261126_0007"
down_revision = "20261121_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ingestion_batches",
        sa.Column("legacy_incomplete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("issues", sa.Column("batch_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_issues_batch", "issues", "ingestion_batches", ["batch_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_issues_batch_id", "issues", ["batch_id"])
    op.drop_constraint("uq_comments_source", "comments", type_="unique")
    op.create_unique_constraint(
        "uq_comments_source",
        "comments",
        ["batch_id", "platform", "shop_id", "product_id", "source_review_id"],
    )
    conn = op.get_bind()
    meta = sa.MetaData()
    groups = sa.Table("issues", meta, autoload_with=conn)
    links = sa.Table("comment_issues", meta, autoload_with=conn)
    comments = sa.Table("comments", meta, autoload_with=conn)
    actions = sa.Table("issue_actions", meta, autoload_with=conn)
    batches = sa.Table("ingestion_batches", meta, autoload_with=conn)
    # Earlier import deduplication did not retain every batch occurrence. Do not
    # invent historical text or results for those uploads.
    conn.execute(
        batches.update().where(batches.c.duplicate_rows > 0).values(legacy_incomplete=True)
    )
    originals = list(conn.execute(sa.select(groups)).mappings())
    partitions = {}
    for group in originals:
        ids = list(
            conn.execute(
                sa.select(comments.c.batch_id)
                .join(links, links.c.comment_id == comments.c.id)
                .where(links.c.issue_id == group["id"])
                .distinct()
            ).scalars()
        )
        ids = sorted(ids, key=lambda value: value or "")
        for index, batch_id in enumerate(ids):
            identity = group["id"] if index == 0 else str(uuid.uuid4())
            partitions[(group["id"], batch_id)] = identity
            if index == 0:
                conn.execute(
                    groups.update().where(groups.c.id == identity).values(batch_id=batch_id)
                )
            else:
                data = dict(
                    group,
                    id=identity,
                    batch_id=batch_id,
                    status="proposed",
                    merged_into_id=None,
                    split_from_id=None,
                    resolved_at=None,
                )
                conn.execute(groups.insert().values(**data))
            moved = list(
                conn.execute(
                    sa.select(links.c.id)
                    .join(comments, comments.c.id == links.c.comment_id)
                    .where(links.c.issue_id == group["id"], comments.c.batch_id == batch_id)
                ).scalars()
            )
            if moved:
                conn.execute(links.update().where(links.c.id.in_(moved)).values(issue_id=identity))
                conn.execute(
                    actions.update()
                    .where(actions.c.comment_issue_id.in_(moved))
                    .values(issue_id=identity)
                )
            if len(ids) > 1 and batch_id:
                conn.execute(
                    batches.update().where(batches.c.id == batch_id).values(legacy_incomplete=True)
                )
    for group in originals:
        for (old_id, batch_id), new_id in partitions.items():
            if old_id != group["id"]:
                continue
            conn.execute(
                groups.update()
                .where(groups.c.id == new_id)
                .values(
                    merged_into_id=partitions.get((group["merged_into_id"], batch_id)),
                    split_from_id=partitions.get((group["split_from_id"], batch_id)),
                )
            )


def downgrade():
    conn = op.get_bind()
    duplicate = conn.execute(sa.text("""
        SELECT 1 FROM comments GROUP BY platform, shop_id, product_id, source_review_id
        HAVING COUNT(*) > 1 LIMIT 1
    """)).first()
    if duplicate:
        raise RuntimeError('Independent batch snapshots exist; restore a backup to revert.')
    op.drop_constraint('uq_comments_source', 'comments', type_='unique')
    op.create_unique_constraint('uq_comments_source', 'comments',
                                ['platform', 'shop_id', 'product_id', 'source_review_id'])
    op.drop_index('ix_issues_batch_id', table_name='issues')
    op.drop_constraint('fk_issues_batch', 'issues', type_='foreignkey')
    op.drop_column('issues', 'batch_id')
    op.drop_column('ingestion_batches', 'legacy_incomplete')
