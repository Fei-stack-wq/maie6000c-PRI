"""Repair unreviewed legacy grouping using saved model output, without model calls.

Human decisions and groups with human audit history are left untouched.
"""

from sqlalchemy import select

from services.common.classification import facets, normalized_category
from services.common.models import AnalysisRun, CommentIssue, IngestionBatch, Issue, IssueAction


def repair(db, batch_id=None):
    targets = {}
    changed = 0
    legacy = list(db.scalars(select(IngestionBatch).where(
        IngestionBatch.grouping_policy_version == 0, IngestionBatch.deleted_at.is_(None),
        IngestionBatch.id == batch_id if batch_id else True)))
    legacy_ids = [batch.id for batch in legacy]
    groups = list(
        db.scalars(
            select(Issue)
            .where(
                Issue.batch_id.in_(
                    select(IngestionBatch.id).where(IngestionBatch.deleted_at.is_(None))
                ),
                Issue.batch_id.in_(legacy_ids),
                Issue.merged_into_id.is_(None),
                Issue.status == "proposed",
            )
            .order_by(Issue.created_at, Issue.id)
        )
    )
    for group in groups:
        links = list(
            db.scalars(
                select(CommentIssue).where(
                    CommentIssue.issue_id == group.id, CommentIssue.superseded_at.is_(None)
                )
            )
        )
        if not links or any(
            link.origin == "human"
            or link.decided_by
            or link.decided_at
            or link.status != "suggested"
            for link in links
        ):
            continue
        if db.scalar(select(IssueAction.id).where(IssueAction.issue_id == group.id).limit(1)):
            continue
        buckets = {}
        for link in links:
            run = db.get(AnalysisRun, link.analysis_run_id) if link.analysis_run_id else None
            raw = (run.output_json or {}).get("issues", []) if run else []
            extraction = next(
                (
                    item
                    for item in raw
                    if item.get("evidence_text") == link.evidence_text
                    and item.get("category_id") == group.category_id
                ),
                None,
            )
            if extraction is None:
                extraction = next(
                    (item for item in raw if item.get("evidence_text") == link.evidence_text), None
                )
            if extraction is None:
                buckets.setdefault((group.category_id, "legacy:" + group.id), []).append(
                    (link, group.title)
                )
                continue
            title = extraction.get("description") or group.title
            category = normalized_category(
                extraction["category_id"], title, link.evidence_text or ""
            )
            known = facets(title) or facets(link.evidence_text or "")
            specific = "|".join(sorted(known)) if known else "legacy:" + group.id
            buckets.setdefault((category, specific), []).append((link, title))
        used_original = False
        for (category, specific), rows in buckets.items():
            key = (
                group.batch_id,
                group.platform,
                group.shop_id,
                group.product_id,
                category,
                specific,
            )
            target = targets.get(key)
            if target is None:
                if not used_original:
                    target = group
                    used_original = True
                else:
                    target = Issue(
                        batch_id=group.batch_id,
                        platform=group.platform,
                        shop_id=group.shop_id,
                        product_id=group.product_id,
                        category_id=category,
                        title=rows[0][1][:200],
                        created_by="ai",
                    )
                    db.add(target)
                    db.flush()
                target.category_id = category
                target.title = rows[0][1][:200]
                targets[key] = target
            for link, _ in rows:
                if link.issue_id != target.id:
                    link.issue_id = target.id
                    link.review_version += 1
                    changed += 1
        if not used_original:
            target = targets[
                (
                    group.batch_id,
                    group.platform,
                    group.shop_id,
                    group.product_id,
                    next(iter(buckets))[0],
                    next(iter(buckets))[1],
                )
            ]
            group.merged_into_id, group.status = target.id, "dismissed"
        db.flush()
    for batch in legacy:
        batch.grouping_policy_version = 2
    db.commit()
    return changed


if __name__ == "__main__":
    from services.common.db import get_session_factory

    with get_session_factory()() as db:
        print("Legacy links regrouped:", repair(db))
