"""Merge/split memberships without deleting decisions, evidence or their audit history."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from services.api.app.reviews.commands import conflict, receipt
from services.api.app.reviews.issue_workflow import (
    as_workflow, evidence_rows, get_issue, issue_snapshot, issue_token,
)
from services.api.app.reviews.manual import normalize_title
from services.api.app.reviews.reassign import snapshot
from services.api.app.reviews.rules import digest
from services.common.locking import lock_issue_groups
from services.common.models import Comment, CommentIssue, Issue, IssueAction, utcnow
from services.common.schemas import (
    IssueMergeConflict, IssueMergeTargetRead, IssueMergeTargetsRead, IssueStructureRead,
)


def require_active(issue):
    if issue.merged_into_id or issue.status not in ("proposed", "confirmed"):
        conflict("issue_not_active")


def active_rows(rows):
    return [row for row in rows if row[0].superseded_at is None]


def saved_evidence(row):
    link, _, _, run = row
    # Preserve the original anchor, never bless changed text with a fresh body hash.
    anchor = link.evidence_body_hash or (run.input_hash if run else None)
    return (link.status, anchor, link.evidence_text, link.evidence_start,
            link.evidence_end, link.evidence_verified)


def transfer_anchor(row):
    link, _, _, run = row
    if link.origin == "human" and link.evidence_body_hash is not None:
        return link.evidence_body_hash
    # A failed/mismatched AI run must not become valid just because membership is human-edited.
    if run and run.status == "succeeded" and run.comment_id == link.comment_id:
        return run.input_hash
    return None


def merge_plan(source_rows, target_rows):
    targets = {row[0].comment_id: row for row in target_rows}
    pairs, conflicts = [], []
    for row in active_rows(source_rows):
        other = targets.get(row[0].comment_id)
        if other and saved_evidence(row) != saved_evidence(other):
            conflicts.append(IssueMergeConflict(
                source_link_id=row[0].id, target_link_id=other[0].id,
                comment_id=row[0].comment_id,
                reason="duplicate_link_conflict",
            ))
        pairs.append((row, other))
    return pairs, conflicts


def targets(db, source_id, query, limit, offset):
    source = get_issue(db, source_id)
    require_active(source)
    rows = evidence_rows(db, source.id)
    if not active_rows(rows):
        conflict("no_active_links")
    stmt = select(Issue).where(
        Issue.id != source.id, Issue.platform == source.platform, Issue.shop_id == source.shop_id,
        Issue.product_id == source.product_id, Issue.batch_id == source.batch_id,
        Issue.merged_into_id.is_(None),
        Issue.status.in_(["proposed", "confirmed"]),
    )
    if query.strip():
        stmt = stmt.where(Issue.title.icontains(query.strip(), autoescape=True))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = []
    candidates = db.execute(
        stmt.order_by(Issue.title, Issue.id).limit(limit).offset(offset),
    ).scalars()
    for target in candidates:
        pairs, conflicts = merge_plan(rows, evidence_rows(db, target.id))
        duplicates = [(row, other) for row, other in pairs
                      if other is not None and saved_evidence(row) == saved_evidence(other)]
        items.append(IssueMergeTargetRead(
            target=as_workflow(db, target), conflicts=conflicts, selectable=not conflicts,
            copied_count=sum(other is None for _, other in pairs),
            deduplicated_count=len(duplicates),
            reactivated_count=sum(bool(other[0].superseded_at) for _, other in duplicates),
        ))
    return IssueMergeTargetsRead(items=items, total=total, limit=limit, offset=offset)


def lock_groups(db, ids, extra_categories=()):
    # Metadata is scalar-only, so later locked ORM reads cannot return stale cached instances.
    metadata = db.execute(select(
        Issue.id, Issue.platform, Issue.shop_id, Issue.product_id, Issue.category_id,
    ).where(Issue.id.in_(ids))).all()
    if len(metadata) != len(ids):
        raise HTTPException(404, detail={"code": "issue_not_found"})
    scope = tuple(metadata[0][1:4])
    if any(tuple(m[1:4]) != scope for m in metadata):
        conflict("scope_mismatch")
    comment_ids = set(db.execute(select(CommentIssue.comment_id).where(
        CommentIssue.issue_id.in_(ids),
    )).scalars())
    locked_ids = set(db.execute(select(Comment.id).where(Comment.id.in_(comment_ids)).order_by(
        Comment.id,
    ).with_for_update()).scalars())
    lock_issue_groups(db, *scope, [m.category_id for m in metadata] + list(extra_categories))
    issues = db.execute(select(Issue).where(Issue.id.in_(ids)).order_by(
        Issue.id,
    ).with_for_update()).scalars().all()
    categories = {m.id: m.category_id for m in metadata}
    if any((i.platform, i.shop_id, i.product_id) != scope or i.category_id != categories[i.id]
           for i in issues):
        conflict("issue_changed")
    rows = {i.id: evidence_rows(db, i.id) for i in issues}
    return {i.id: i for i in issues}, rows, locked_ids


def audit(db, issue, link, operation, before, after, common, operator, note, action):
    stmt = select(IssueAction.id).where(IssueAction.issue_id == issue.id)
    stmt = stmt.where(IssueAction.comment_issue_id == link.id if link is not None
                      else IssueAction.comment_issue_id.is_(None))
    previous = db.execute(stmt.order_by(IssueAction.id.desc()).limit(1)).scalar_one_or_none()
    entry = IssueAction(
        issue_id=issue.id, comment_issue_id=link.id if link is not None else None,
        action=action, from_status=before["status"] if before else None,
        to_status=after["status"], operator=operator, note=note,
        payload_json={**common, "operation": operation, "previous_action_id": previous,
                      "before": before, "after": after, "snapshot": after},
    )
    db.add(entry)
    return entry


def restructure(db, source_id, payload, operator, operation):
    fingerprint = digest({"operation": operation, "source_issue_id": source_id,
                          "operator": operator, **payload.model_dump(mode="json")})
    if saved := receipt(db, payload.request_id, fingerprint, IssueStructureRead):
        return saved
    merging = operation == "merge"
    if merging and source_id == payload.target_issue_id:
        conflict("same_issue")
    ids = [source_id, payload.target_issue_id] if merging else [source_id]
    groups, rows_by_id, locked_ids = lock_groups(
        db, ids, [] if merging else [payload.new_issue.category_id],
    )
    if saved := receipt(db, payload.request_id, fingerprint, IssueStructureRead):
        return saved
    if {row[1].id for rows in rows_by_id.values() for row in rows} != locked_ids:
        conflict("issue_changed")
    source, rows = groups[source_id], rows_by_id[source_id]
    if payload.expected_token != issue_token(source, rows):
        conflict("issue_changed")
    require_active(source)
    active = active_rows(rows)
    if not active:
        conflict("no_active_links")
    scope = (source.platform, source.shop_id, source.product_id)
    if any((row[1].platform, row[1].shop_id, row[1].product_id) != scope
           for group_rows in rows_by_id.values() for row in group_rows):
        conflict("scope_mismatch")
    if merging:
        target = groups[payload.target_issue_id]
        if target.batch_id != source.batch_id:
            conflict("scope_mismatch")
        target_rows = rows_by_id[target.id]
        if payload.expected_target_token != issue_token(target, target_rows):
            conflict("target_changed")
        require_active(target)
        pairs, conflicts = merge_plan(rows, target_rows)
        if conflicts:
            raise HTTPException(409, detail={"code": "duplicate_link_conflict",
                                            "conflicts": [c.model_dump() for c in conflicts]})
    else:
        selected = set(payload.comment_issue_ids)
        if not selected < {row[0].id for row in active}:
            conflict("split_requires_subset")
        candidates = db.execute(select(Issue).where(
            Issue.platform == source.platform, Issue.shop_id == source.shop_id,
            Issue.product_id == source.product_id, Issue.batch_id == source.batch_id,
            Issue.category_id == payload.new_issue.category_id,
            Issue.status.in_(["proposed", "confirmed"]), Issue.merged_into_id.is_(None),
        )).scalars().all()
        if any(normalize_title(i.title) == normalize_title(payload.new_issue.title)
               for i in candidates):
            conflict("duplicate_issue")
        target = Issue(
            platform=source.platform, shop_id=source.shop_id, product_id=source.product_id,
            batch_id=source.batch_id, category_id=payload.new_issue.category_id,
            title=" ".join(payload.new_issue.title.split()),
            status="proposed", created_by="human", split_from_id=source.id,
        )
        pairs = [(row, None) for row in active if row[0].id in selected]
    before_source = issue_snapshot(source)
    before_target = issue_snapshot(target) if merging else None
    now = utcnow()
    try:
        if not merging:
            db.add(target)
            db.flush()
        target.status, target.resolved_at, target.updated_at = "proposed", None, now
        if merging:
            target.version += 1
        source.status = "dismissed" if merging else "proposed"
        source.merged_into_id = target.id if merging else None
        source.resolved_at, source.updated_at = None, now
        source.version += 1
        common = {
            "operation_id": payload.request_id, "source_issue_id": source.id,
            "target_issue_id": target.id, "source_issue_title": source.title,
            "target_issue_title": target.title,
        }
        transfers = []
        reactivated_count = sum(bool(other and other[0].superseded_at) for _, other in pairs)
        for row, other in pairs:
            link, comment, _, _ = row
            before_link = snapshot(link, comment, source)
            before_link["issue_version"] = before_source["version"]
            destination = other[0] if other else None
            before_destination = snapshot(destination, comment, target) if other else None
            if before_destination:
                before_destination["issue_version"] = before_target["version"]
            if destination is None:
                destination = CommentIssue(
                    comment_id=comment.id, issue_id=target.id, origin="human", status=link.status,
                    evidence_text=link.evidence_text, evidence_start=link.evidence_start,
                    evidence_end=link.evidence_end, evidence_verified=link.evidence_verified,
                    evidence_body_hash=transfer_anchor(row),
                    analysis_run_id=link.analysis_run_id, comment_version=link.comment_version,
                    decided_by=link.decided_by, decided_at=link.decided_at,
                )
                db.add(destination)
            else:
                # Even a pending duplicate now has a human grouping choice; Worker must retain it.
                destination.evidence_body_hash = transfer_anchor(other)
                destination.origin = "human"
                destination.superseded_at = None
                destination.review_version += 1
            # Archive membership, not the decision. Keep immutable original audits.
            link.superseded_at, link.origin = now, "human"
            link.review_version += 1
            db.flush()
            pair_info = {**common, "source_link_id": link.id, "target_link_id": destination.id,
                         "deduplicated": other is not None}
            for record, issue, before, direction in (
                (link, source, before_link, "out"),
                (destination, target, before_destination, "in"),
            ):
                audit(db, issue, record, operation + "_" + direction, before,
                      snapshot(record, comment, issue), pair_info, operator, payload.note, "change")
            transfers.append({**pair_info, "before_source": before_link,
                              "before_target": before_destination,
                              "after_target": snapshot(destination, comment, target)})
        common.update(transfers=transfers, copied_count=sum(other is None for _, other in pairs),
                      deduplicated_count=sum(other is not None for _, other in pairs),
                      reactivated_count=reactivated_count)
        action_type = "merge_into" if merging else "split"
        first = audit(db, source, None, operation + "_out", before_source, issue_snapshot(source),
                      common, operator, payload.note, action_type)
        second = audit(db, target, None, operation + "_in", before_target, issue_snapshot(target),
                       common, operator, payload.note, action_type)
        first.request_id, first.request_hash = payload.request_id, fingerprint
        db.flush()
        result = IssueStructureRead(
            request_id=payload.request_id, operation=operation, source_issue_id=source.id,
            target_issue_id=target.id, source_action_id=first.id, target_action_id=second.id,
            copied_count=common["copied_count"], deduplicated_count=common["deduplicated_count"],
            reactivated_count=reactivated_count,
            operator=operator, created_at=now,
        )
        first.result_json = result.model_dump(mode="json")
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        if saved := receipt(db, payload.request_id, fingerprint, IssueStructureRead):
            return saved
        raise
    except Exception:
        db.rollback()
        raise
