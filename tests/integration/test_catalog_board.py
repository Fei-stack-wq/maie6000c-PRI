import json

from sqlalchemy import select

from services.common.models import Comment, CommentIssue, IngestionBatch


def upload(client, platform, shop, product, body="拉链卡住了。"):
    result = client.post(
        "/review-batches",
        json={
            "platform": platform,
            "filename": product + ".csv",
            "comments": [
                {
                    "platform": platform,
                    "shop_id": shop,
                    "product_id": product,
                    "source_review_id": "r",
                    "body": body,
                }
            ],
        },
    )
    assert result.status_code == 202, result.text
    return result.json()["batch_id"]


def test_complete_catalogs_and_dependent_product_scope(client, session_factory):
    a = upload(client, "one", "shop-a", "same")
    b = upload(client, "two", "shop-b", "same")
    upload(client, "one", "shop-a", "different")
    # Force pagination: options must not come from only the first data page.
    assert client.get("/catalog/batches", params={"limit": 1}).json()["total"] == 3
    assert (
        len(client.get("/catalog/batches", params={"limit": 1, "offset": 2}).json()["items"]) == 1
    )
    one = client.get("/catalog/products", params={"batch_ids": a}).json()
    assert one["total"] == 1 and one["items"][0]["platform"] == "one"
    selected = client.get("/catalog/products", params={"batch_ids": a + "," + b, "limit": 1}).json()
    assert selected["total"] == 2
    key = json.dumps([["two", "shop-b", "same"]])
    records = client.get("/comments", params={"batch_ids": a + "," + b, "product_keys": key})
    assert records.status_code == 200 and records.headers["x-total-count"] == "1"
    assert records.json()[0]["batch_id"] == b
    assert client.get("/comments", params={"product_keys": "not-json"}).status_code == 422
    assert client.get("/comments", params={"product_keys": '[["incomplete"]]'}).status_code == 422


def test_board_paginates_whole_products_with_independent_batches(
    client, worker_setup, session_factory, ai_response
):
    a = upload(client, "one", "shop", "shoe")
    b = upload(client, "one", "shop", "shoe")
    worker_setup.run_once()
    worker_setup.run_once()
    with session_factory() as db:
        comment = db.scalar(select(Comment).where(Comment.batch_id == a))
        link = db.scalar(select(CommentIssue).where(CommentIssue.comment_id == comment.id))
        link.status, link.auto_confirmed = "accepted", True
        db.commit()
    first = client.get("/issue-board", params={"limit": 1}).json()
    assert first["total_products"] == 2
    assert len(first["batches"]) == len(first["batches"][0]["products"]) == 1
    all_rows = client.get("/issue-board", params={"batch_ids": a + "," + b}).json()
    assert {batch["batch"]["id"] for batch in all_rows["batches"]} == {a, b}
    for batch in all_rows["batches"]:
        category = batch["products"][0]["categories"][0]
        assert category["category_id"] == "quality"
        if batch["batch"]["id"] == a:
            assert category["accepted"]["total"] == 1 and category["pending"]["total"] == 0
        else:
            assert category["accepted"]["total"] == 0 and category["pending"]["total"] == 1
        for side in ("accepted", "pending"):
            assert all(
                row["comment"]["batch_id"] == batch["batch"]["id"]
                for row in category[side]["items"]
            )
    assert client.post(f"/review-batches/{a}/trash").status_code == 200
    assert client.get("/issue-board").json()["total_products"] == 1
    assert client.get("/catalog/batches").json()["total"] == 1


def test_catalog_is_complete_beyond_first_two_hundred_batches(client, session_factory):
    with session_factory() as db:
        db.add_all(IngestionBatch(platform="demo", status="imported") for _ in range(205))
        db.commit()
    one = client.get("/catalog/batches").json()
    two = client.get("/catalog/batches", params={"offset": 200}).json()
    assert one["total"] == two["total"] == 205
    assert len(one["items"]) == 200 and len(two["items"]) == 5
    assert len({row["id"] for row in one["items"] + two["items"]}) == 205


def test_multi_issue_review_keeps_all_category_badges_in_each_board_lane(
    client, worker_setup, ai_response,
):
    batch = upload(client, "demo", "shop", "bag", "拉链卡住了，而且快递太慢了。")
    assert worker_setup.run_once() == "completed"
    data = client.get("/issue-board", params={"batch_ids": batch}).json()
    categories = data["batches"][0]["products"][0]["categories"]
    assert {category["category_id"] for category in categories} == {"quality", "logistics"}
    for category in categories:
        item = category["pending"]["items"][0]
        assert item["comment"]["issue_categories"] == ["logistics", "quality"]
