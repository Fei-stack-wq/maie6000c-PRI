"""Read contracts used by the live product comment and issue pages."""

from services.common.models import Comment, utcnow


def test_comment_search_filters_total_and_paging_keep_array_contract(
    client, new_job, session_factory
):
    ids = [
        new_job(body=body, product=product)[1]
        for body, product in [
            ("拉链卡住了 A", "bag-a"),
            ("拉链卡住了 B", "bag-a"),
            ("拉链卡住了 C", "bag-b"),
            ("没有匹配词", "bag-a"),
        ]
    ]
    with session_factory() as db:
        for index, comment_id in enumerate(ids):
            comment = db.get(Comment, comment_id)
            comment.analysis_status = "analyzed" if index < 3 else "queued"
            comment.has_issue = "yes" if index < 3 else None
        db.commit()
    query = {
        "product_id": "bag-a",
        "analysis_status": "analyzed",
        "has_issue": "yes",
        "q": " 拉链卡住 ",
        "limit": 1,
    }
    first = client.get("/comments", params=query)
    second = client.get("/comments", params={**query, "offset": 1})
    assert first.status_code == 200
    assert first.headers["x-total-count"] == second.headers["x-total-count"] == "2"
    assert isinstance(first.json(), list) and len(first.json()) == 1
    assert {first.json()[0]["id"], second.json()[0]["id"]} == set(ids[:2])
    assert first.headers["cache-control"] == "no-store"
    empty = client.get("/comments", params={**query, "offset": 2})
    assert empty.json() == [] and empty.headers["x-total-count"] == "2"


def test_comment_search_treats_sql_wildcards_literally(client, new_job):
    literal = new_job(body="Exactly 50%_off\\ now.")[1]
    new_job(body="Exactly 500xoffX now.")
    result = client.get("/comments", params={"q": "50%_off\\"})
    assert [row["id"] for row in result.json()] == [literal]
    assert result.headers["x-total-count"] == "1"
    assert client.get("/comments", params={"q": "' OR 1=1 --"}).json() == []


def test_comment_pagination_is_stable_for_matching_timestamps(client, new_job, session_factory):
    ids = [new_job()[1] for _ in range(3)]
    with session_factory() as db:
        timestamp = utcnow()
        for comment in db.query(Comment):
            comment.created_at = timestamp
        db.commit()
    received = [
        client.get("/comments", params={"limit": 1, "offset": i}).json()[0]["id"] for i in range(3)
    ]
    assert received == sorted(ids)
    assert client.get("/comments", params={"q": "x" * 201}).status_code == 422


def test_comment_and_issue_pages_reflect_saved_review_and_group_action(
    client,
    review_candidate,
    review_payload,
):
    import uuid

    item = review_candidate()
    comment_id, issue_id, link_id = item["comment"]["id"], item["issue"]["id"], item["link"]["id"]
    assert (
        client.post(f"/comment-issues/{link_id}/decisions", json=review_payload(item)).status_code
        == 200
    )
    comment = client.get(f"/review-comments/{comment_id}").json()
    assert comment["links"][0]["link"]["status"] == "accepted"
    assert comment["links"][0]["issue"]["id"] == issue_id
    issue = client.get(f"/review-issues/{issue_id}").json()
    assert issue["valid_accepted_count"] == 1 and issue["issue"]["status"] == "proposed"
    result = client.post(
        f"/issues/{issue_id}/actions",
        json={
            "request_id": str(uuid.uuid4()),
            "expected_token": issue["token"],
            "action": "confirm",
            "note": "联调验收：当前证据足够确认问题",
        },
    )
    assert result.status_code == 200
    listing = client.get("/review-issues", params={"status": "confirmed"}).json()
    assert listing["total"] == 1 and listing["items"][0]["issue"]["id"] == issue_id
    assert listing["items"][0]["valid_accepted_count"] == 1
    evidence = client.get(f"/review-issues/{issue_id}/evidence").json()["items"][0]
    assert evidence["usable"] and evidence["review"]["comment"]["id"] == comment_id
    assert client.get(f"/review-issues/{issue_id}").json()["actions"][0]["action"] == "confirm"


def test_comment_detail_marks_changed_source_instead_of_presenting_old_evidence_as_current(
    client,
    recheck_case,
):
    _, item = recheck_case()
    detail = client.get(f"/review-comments/{item['comment']['id']}").json()
    link = next(r for r in detail["links"] if r["link"]["id"] == item["link"]["id"])
    assert link["needs_recheck"]
    issue = client.get(f"/review-issues/{link['issue']['id']}").json()
    assert issue["issue"]["accepted_count"] == 1
    assert issue["valid_accepted_count"] == 0 and issue["invalid_accepted_count"] == 1
