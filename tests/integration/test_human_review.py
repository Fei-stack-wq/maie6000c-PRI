import uuid

import pytest
from sqlalchemy import event

from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction, Job


def endpoint(item):
    return f"/comment-issues/{item['link']['id']}/decisions"


@pytest.mark.parametrize("decision,status", [("accept", "accepted"), ("reject", "rejected")])
def test_decision_persists_snapshot_and_separate_ai_and_issue_state(
    client, session_factory, review_candidate, review_payload, decision, status,
):
    item = review_candidate()
    response = client.post(endpoint(item), json=review_payload(item, decision))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == status
    detail = client.get(f"/comment-issues/{item['link']['id']}").json()
    assert detail["link"]["status"] == status
    assert detail["link"]["origin"] == "ai"
    assert not detail["can_decide"]
    assert detail["issue"]["status"] == "proposed"
    assert detail["comment"]["has_issue"] == "yes"
    assert detail["review_version"] == item["review_version"] + 1
    assert len(detail["actions"]) == 1
    snapshot = detail["actions"][0]["payload_json"]["snapshot"]
    assert snapshot["body"] == item["comment"]["body"]
    assert snapshot["evidence_text"] == item["link"]["evidence_text"]
    assert client.get("/review-queue").json()["total"] == 0
    assert client.get("/review-queue?status=reviewed").json()["total"] == 1
    assert client.get("/stats/summary").json()["human_accepted_count"] == (status == "accepted")
    with session_factory() as db:
        assert db.query(IssueAction).one().operator == "demo-reviewer"


def test_repeat_request_returns_same_receipt_even_after_source_changes(
    client, session_factory, review_candidate, review_payload,
):
    item = review_candidate()
    payload = review_payload(item)
    first = client.post(endpoint(item), json=payload)
    with session_factory() as db:
        db.get(Comment, item["comment"]["id"]).body = "更新了评论"
        db.commit()
    second = client.post(endpoint(item), json=payload)
    assert second.status_code == 200
    assert first.json() == second.json()
    assert len(client.get(f"/comment-issues/{item['link']['id']}").json()["actions"]) == 1
    payload["note"] = "不同内容"
    conflict = client.post(endpoint(item), json=payload)
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"


def test_same_key_cannot_be_used_for_another_link(
    client, review_candidate, review_payload,
):
    a, b = review_candidate(), review_candidate()
    payload = review_payload(a)
    assert client.post(endpoint(a), json=payload).status_code == 200
    payload["expected_token"] = b["token"]
    assert client.post(endpoint(b), json=payload).status_code == 409
    assert client.get(f"/comment-issues/{b['link']['id']}").json()["can_decide"]


@pytest.mark.parametrize("change", ["body", "issue", "link", "superseded", "run"])
def test_stale_snapshot_is_rejected_without_audit(
    client, session_factory, review_candidate, review_payload, change,
):
    item = review_candidate()
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        if change == "body":
            db.get(Comment, link.comment_id).body += " 内容改变"
        elif change == "issue":
            db.get(Issue, link.issue_id).version += 1
        elif change == "link":
            link.review_version += 1
        elif change == "superseded":
            from services.common.models import utcnow
            link.superseded_at = utcnow()
        else:
            db.get(Comment, link.comment_id).current_analysis_run_id = None
        db.commit()
    assert client.post(endpoint(item), json=review_payload(item)).status_code == 409
    with session_factory() as db:
        assert db.query(IssueAction).count() == 0
        assert db.get(CommentIssue, item["link"]["id"]).status == "suggested"


def test_reanalysis_reuses_id_but_invalidates_old_page(
    client, session_factory, worker_setup, review_candidate, review_payload,
):
    item = review_candidate()
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    refreshed = client.get(f"/comment-issues/{item['link']['id']}").json()
    assert refreshed["can_decide"]
    assert refreshed["token"] != item["token"]
    assert client.post(endpoint(item), json=review_payload(item)).status_code == 409
    assert client.post(endpoint(refreshed), json=review_payload(refreshed)).status_code == 200


def test_worker_preserves_decision_and_audit(
    client, session_factory, worker_setup, review_candidate, review_payload,
):
    item = review_candidate()
    assert client.post(endpoint(item), json=review_payload(item, "reject")).status_code == 200
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        version = link.review_version
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        assert link.status == "rejected" and link.review_version == version
        assert link.superseded_at is None
        assert db.query(IssueAction).count() == 1
        assert db.query(AnalysisRun).count() == 2


def test_validation_and_identity_cannot_be_spoofed(client, review_candidate, review_payload):
    item = review_candidate()
    for update in ({"decision": "change"}, {"decision": "reject", "note": "  "},
                   {"operator": "admin"}, {"expected_token": ""}, {"note": "x" * 501}):
        response = client.post(endpoint(item), json={**review_payload(item), **update})
        assert response.status_code == 422
    assert client.get("/comment-issues/99999").status_code == 404
    assert client.get("/review-queue?status=invalid").status_code == 422


def test_decision_transaction_rolls_back_on_audit_failure(
    engine, client, session_factory, review_candidate, review_payload,
):
    item = review_candidate()
    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO issue_actions"):
            raise RuntimeError("simulated audit failure")
    event.listen(engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="simulated audit failure"):
            client.post(endpoint(item), json=review_payload(item))
    finally:
        event.remove(engine, "before_cursor_execute", fail_audit)
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        assert link.status == "suggested" and link.decided_at is None
        assert link.review_version == item["review_version"]
        assert db.query(IssueAction).count() == 0


def test_queue_filters_paginates_and_excludes_stale_items(
    client, session_factory, review_candidate,
):
    first = review_candidate(product="bag-a")
    review_candidate(product="bag-b")
    assert client.get("/review-queue?limit=1").json()["total"] == 2
    assert len(client.get("/review-queue?limit=1&offset=1").json()["items"]) == 1
    assert client.get("/review-queue?product_id=bag-a").json()["total"] == 1
    assert client.get("/review-queue?category_id=logistics").json()["total"] == 0
    with session_factory() as db:
        db.get(Comment, first["comment"]["id"]).body = "changed but status still analyzed"
        db.commit()
    assert client.get("/review-queue").json()["total"] == 1


def test_initial_and_changed_body_are_both_saved(client):
    from services.common.schemas import ReviewDecisionRequest
    payload = {"platform": "demo", "comments": [{
        "platform": "demo", "shop_id": "s", "product_id": "p", "source_review_id": "r",
        "body": "原始拉链问题",
    }]}
    client.post("/review-batches", json=payload)
    comment_id = client.get("/comments").json()[0]["id"]
    payload["comments"][0]["body"] = "修改后的评论"
    client.post("/review-batches", json=payload)
    revisions = client.get(f"/comments/{comment_id}").json()["revisions"]
    assert [(r["version"], r["body"]) for r in revisions] == [
        (1, "原始拉链问题"),
    ]
    with pytest.raises(ValueError):
        ReviewDecisionRequest(request_id=str(uuid.uuid4()), decision="reject",
                              expected_token="a" * 64, note="\n")


def test_same_source_changed_twice_in_one_csv_keeps_unique_versions(client):
    response = client.post("/review-batches", json={
        "platform": "demo", "csv_text": (
            "shop_id,product_id,source_review_id,body\n"
            "s,p,r,原始拉链问题\ns,p,r,修改后的评论\n"
        ),
    })
    assert response.status_code == 202, response.text
    assert response.json()["job_count"] == 1
    comment_id = client.get("/comments").json()[0]["id"]
    revisions = client.get(f"/comments/{comment_id}").json()["revisions"]
    assert [(r["version"], r["body"]) for r in revisions] == [
        (1, "原始拉链问题"), (2, "修改后的评论"),
    ]


def test_legacy_comment_snapshotted_before_first_edit(client, session_factory, new_job):
    _, comment_id, _ = new_job()
    with session_factory() as db:
        comment = db.get(Comment, comment_id)
        original = comment.body
        row = {"platform": comment.platform, "shop_id": comment.shop_id,
               "product_id": comment.product_id, "source_review_id": comment.source_review_id,
               "body": "这是修改后的原文"}
    from services.api.app.ingestion import ingest_comments, parse_normalized
    from services.common.models import IngestionBatch
    from services.common.schemas import NormalizedComment
    with session_factory() as db:
        batch = db.get(IngestionBatch, db.get(Comment, comment_id).batch_id)
        ingest_comments(db, batch, parse_normalized([NormalizedComment(**row)], "demo").comments)
        db.commit()
    revisions = client.get(f"/comments/{comment_id}").json()["revisions"]
    assert [(r["version"], r["body"]) for r in revisions] == [
        (1, original), (2, row["body"]),
    ]


def test_invalid_evidence_cannot_be_accepted_but_can_be_rejected(
    client, session_factory, review_candidate, review_payload,
):
    item = review_candidate()
    with session_factory() as db:
        db.get(CommentIssue, item["link"]["id"]).evidence_start = -10
        db.commit()
    item = client.get(f"/comment-issues/{item['link']['id']}").json()
    response = client.post(endpoint(item), json=review_payload(item))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "invalid_evidence"
    assert client.post(endpoint(item), json=review_payload(item, "reject")).status_code == 200
