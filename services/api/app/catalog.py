"""Complete scope catalogs and product-paged batch/category issue board."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, tuple_

from services.api.app.batches import visible_comment, visible_issue
from services.common.db import get_db
from services.common.models import Comment, CommentIssue, IngestionBatch, Issue
from services.common.schemas import BatchRead

router = APIRouter()
CATEGORIES = ("quality", "logistics", "mismatch", "usability", "other")


def parse_scope(batch_ids="", product_keys=""):
    batches = list(dict.fromkeys(value for value in batch_ids.split(",") if value))
    if len(batches) > 200 or any(len(value) > 36 for value in batches):
        raise HTTPException(422, detail={"code": "invalid_batch_selection"})
    try:
        products = json.loads(product_keys) if product_keys else []
        if not isinstance(products, list) or len(products) > 200:
            raise ValueError()
        if any(
            not isinstance(key, list)
            or len(key) != 3
            or any(not isinstance(value, str) or not value or len(value) > 128 for value in key)
            for key in products
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, detail={"code": "invalid_product_selection"}) from None
    return batches, products


def apply_scope(query, entity, batch_ids="", product_keys=""):
    batches, products = parse_scope(batch_ids, product_keys)
    if batches:
        query = query.where(entity.batch_id.in_(batches))
    if products:
        query = query.where(
            tuple_(entity.platform, entity.shop_id, entity.product_id).in_(products)
        )
    return query


@router.get("/catalog/batches")
def batch_options(
    limit: int = Query(200, ge=1, le=200), offset: int = Query(0, ge=0), db=Depends(get_db)
):
    query = select(IngestionBatch).where(IngestionBatch.deleted_at.is_(None))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.order_by(IngestionBatch.created_at.desc(), IngestionBatch.id)
        .offset(offset)
        .limit(limit)
    )
    return {"total": total, "items": [BatchRead.model_validate(row) for row in rows]}


@router.get("/catalog/products")
def product_options(
    batch_ids: str = Query("", max_length=8000),
    limit: int = Query(200, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    query = apply_scope(
        select(Comment.platform, Comment.shop_id, Comment.product_id)
        .where(visible_comment())
        .distinct(),
        Comment,
        batch_ids,
    )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(
        query.order_by(Comment.platform, Comment.shop_id, Comment.product_id)
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "total": total,
        "items": [
            {
                "platform": p,
                "shop_id": s,
                "product_id": product,
                "key": json.dumps([p, s, product], ensure_ascii=False, separators=(",", ":")),
            }
            for p, s, product in rows
        ],
    }


def category_rows(db, batch_id, platform, shop_id, product_id, category, status="all", query=""):
    from services.api.app.reviews.queries import context_query

    statement = context_query().where(
        Comment.batch_id == batch_id,
        Issue.batch_id == batch_id,
        Comment.platform == platform,
        Comment.shop_id == shop_id,
        Comment.product_id == product_id,
        Issue.category_id == category,
        Issue.merged_into_id.is_(None),
        CommentIssue.superseded_at.is_(None),
        CommentIssue.status.in_(["accepted", "suggested"]),
        Comment.analysis_status.in_(["analyzed", "failed"]),
    )
    if status != "all":
        statement = statement.where(Issue.status == status)
    if query.strip():
        from sqlalchemy import or_

        statement = statement.where(
            or_(
                Issue.title.icontains(query.strip(), autoescape=True),
                Comment.body.icontains(query.strip(), autoescape=True),
            )
        )
    rows = db.execute(
        statement.order_by(Issue.created_at, Issue.id, Comment.created_at, CommentIssue.id)
    ).all()
    from services.api.app.reviews.issue_workflow import evidence_reason

    accepted, pending = [], []
    for row in rows:
        (accepted if evidence_reason(row) is None else pending).append(row)
    return accepted, pending


def page_rows(db, rows, offset, limit):
    from services.api.app.reviews.queries import as_review

    page = rows[offset : offset + limit]
    categories = {}
    comment_ids = [row[1].id for row in page]
    if comment_ids:
        for comment_id, category in db.execute(
            select(CommentIssue.comment_id, Issue.category_id).join(Issue).where(
                CommentIssue.comment_id.in_(comment_ids),
                CommentIssue.superseded_at.is_(None),
                CommentIssue.status.in_(["accepted", "suggested"]),
                Issue.merged_into_id.is_(None), visible_issue(),
            ).distinct()
        ):
            categories.setdefault(comment_id, []).append(category)
    items = []
    for row in page:
        item = as_review(db, row)
        item.comment.issue_categories = sorted(categories.get(row[1].id, []))
        items.append(item)
    return {"total": len(rows), "items": items}


@router.get("/issue-board/entries")
def entries(
    batch_id: str,
    platform: str,
    shop_id: str,
    product_id: str,
    category_id: str,
    decision: str,
    status: str = "all",
    q: str = "",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    if category_id not in CATEGORIES or decision not in ("accepted", "pending"):
        raise HTTPException(422, detail={"code": "invalid_board_selection"})
    accepted, pending = category_rows(
        db, batch_id, platform, shop_id, product_id, category_id, status, q
    )
    return page_rows(db, accepted if decision == "accepted" else pending, offset, limit)


@router.get("/issue-board")
def board(
    batch_ids: str = Query("", max_length=8000),
    product_keys: str = Query("", max_length=80000),
    product_id: str | None = None,
    category_id: str = "",
    status: str = "all",
    q: str = Query("", max_length=200),
    limit: int = Query(5, ge=1, le=20),
    offset: int = Query(0, ge=0),
    db=Depends(get_db),
):
    query = (
        select(Comment.batch_id, Comment.platform, Comment.shop_id, Comment.product_id)
        .where(
            visible_comment(),
            Comment.analysis_status.in_(["analyzed", "failed"]),
            Comment.batch_id.is_not(None),
        )
        .distinct()
    )
    query = apply_scope(query, Comment, batch_ids, product_keys)
    if product_id:
        query = query.where(Comment.product_id == product_id)
    if category_id and category_id not in CATEGORIES:
        raise HTTPException(422, detail={"code": "invalid_category"})
    if category_id or status != "all" or q.strip():
        from sqlalchemy import or_

        matching = (
            select(CommentIssue.comment_id)
            .join(Issue)
            .where(
                visible_issue(),
                CommentIssue.superseded_at.is_(None),
                CommentIssue.status.in_(["accepted", "suggested"]),
                Issue.merged_into_id.is_(None),
            )
        )
        if category_id:
            matching = matching.where(Issue.category_id == category_id)
        if status != "all":
            matching = matching.where(Issue.status == status)
        if q.strip():
            matching = matching.join(Comment, Comment.id == CommentIssue.comment_id).where(
                or_(
                    Issue.title.icontains(q.strip(), autoescape=True),
                    Comment.body.icontains(q.strip(), autoescape=True),
                )
            )
        query = query.where(Comment.id.in_(matching))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    # Page whole products, never arbitrary cards halfway through a category.
    products = db.execute(
        query.join(IngestionBatch, IngestionBatch.id == Comment.batch_id)
        .add_columns(IngestionBatch.created_at)
        .order_by(
            IngestionBatch.created_at.desc(),
            Comment.batch_id,
            Comment.platform,
            Comment.shop_id,
            Comment.product_id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    batches = {}
    for batch_id, platform, shop_id, product_id, _ in products:
        if batch_id not in batches:
            batches[batch_id] = {
                "batch": BatchRead.model_validate(db.get(IngestionBatch, batch_id)),
                "products": [],
            }
        categories = []
        for category in CATEGORIES:
            if category_id and category != category_id:
                continue
            accepted, pending = category_rows(
                db, batch_id, platform, shop_id, product_id, category, status, q
            )
            if accepted or pending:
                categories.append(
                    {
                        "category_id": category,
                        "issue_count": len({row[2].id for row in accepted + pending}),
                        "accepted": page_rows(db, accepted, 0, 5),
                        "pending": page_rows(db, pending, 0, 5),
                    }
                )
        batches[batch_id]["products"].append(
            {
                "platform": platform,
                "shop_id": shop_id,
                "product_id": product_id,
                "categories": categories,
            }
        )
    return {
        "total_products": total,
        "limit": limit,
        "offset": offset,
        "batches": list(batches.values()),
    }
