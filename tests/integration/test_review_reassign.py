"""Regrouping is atomic, evidence-preserving, scoped, and never overwrites human intent."""
import uuid

import pytest
from sqlalchemy import event

from services.common.models import Comment, CommentIssue, Issue, IssueAction, Job, utcnow


def path(item):
    return f"/comment-issues/{item['link']['id']}"


@pytest.mark.parametrize("accepted", [False, True])
def test_reassign_records_both_sides_and_preserves_initial_history(
    client, review_candidate, review_payload, reassign_target, reassign_payload, accepted,
):
    item = review_candidate()
    if accepted:
        assert client.post(path(item) + "/decisions", json=review_payload(item)).status_code == 200
        item = client.get(path(item)).json()
    target_id = reassign_target(item)
    payload = reassign_payload(item, target_id)
    response = client.post(path(item) + "/reassign", json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    source = client.get(path(item)).json()
    target = client.get(f"/comment-issues/{receipt['target_link_id']}").json()
    assert source["link"]["status"] == "rejected"
    assert source["link"]["issue_id"] == item["issue"]["id"]
    assert source["link"]["origin"] == "ai"
    assert source["actions"][1:] == item["actions"]
    assert target["link"]["status"] == "accepted" and target["link"]["origin"] == "human"
    assert target["can_revise"] and target["can_reassign"]
    assert target["issue"]["id"] == target_id and target["issue"]["status"] == "proposed"
    assert target["link"]["evidence_text"] == item["link"]["evidence_text"]
    assert target["link"]["analysis_run_id"] == item["link"]["analysis_run_id"]
    assert source["issue"]["accepted_count"] == source["issue"]["suggested_count"] == 0
    assert target["issue"]["accepted_count"] == 1
    assert client.get("/review-queue").json()["total"] == 0
    assert client.get("/review-queue?status=reviewed").json()["total"] == 2
    assert client.get("/stats/summary").json()["human_accepted_count"] == 1
    for entry, operation in [(source, "reassign_out"), (target, "reassign_in")]:
        audit = entry["actions"][0]
        assert audit["action"] == "change" and audit["note"] == payload["note"]
        assert audit["payload_json"]["operation"] == operation
        assert audit["payload_json"]["operation_id"] == payload["request_id"]
        assert audit["payload_json"]["snapshot"]["body"] == item["comment"]["body"]
        assert audit["payload_json"]["source_link_id"] == item["link"]["id"]
        assert audit["payload_json"]["target_link_id"] == target["link"]["id"]
    assert target["actions"][0]["payload_json"]["before"] is None
    # Replaying this receipt must not undo a later explicit target revision.
    assert client.post(path(target) + "/decisions", json={
        **review_payload(target, "reject"), "mode": "revise",
    }).status_code == 200
    assert client.post(path(item) + "/reassign", json=payload).json() == receipt
    assert client.get(path(target)).json()["link"]["status"] == "rejected"
    collision = client.post(path(item) + "/reassign", json={**payload, "note": "另一原因"})
    assert collision.status_code == 409
    assert collision.json()["detail"]["code"] == "idempotency_conflict"
    collision = client.post(path(item) + "/decisions", json={
        **review_payload(item), "request_id": payload["request_id"],
    })
    assert collision.status_code == 409


@pytest.mark.parametrize("superseded", [False, True])
def test_reuses_only_unreviewed_target_and_keeps_its_old_evidence(
    client, session_factory, review_candidate, reassign_target, reassign_payload, superseded,
):
    item = review_candidate()
    target_id = reassign_target(item)
    with session_factory() as db:
        link = CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id,
                            evidence_text="拉链", evidence_start=0, evidence_end=2,
                            evidence_verified=True, review_version=7,
                            superseded_at=utcnow() if superseded else None)
        db.add(link)
        db.commit()
        target_link_id = link.id
    response = client.post(path(item) + "/reassign", json=reassign_payload(item, target_id))
    assert response.status_code == 200, response.text
    assert response.json()["target_link_id"] == target_link_id
    target = client.get(f"/comment-issues/{target_link_id}").json()
    assert target["review_version"] == 8
    assert target["link"]["superseded_at"] is None
    assert target["actions"][0]["payload_json"]["before"]["evidence_text"] == "拉链"
    assert target["link"]["evidence_text"] == item["link"]["evidence_text"]
    with session_factory() as db:
        assert db.query(CommentIssue).count() == 2


@pytest.mark.parametrize("changes", [
    {"status": "accepted"}, {"status": "rejected"}, {"origin": "human"},
    {"decided_by": "another-reviewer"}, {"decided_at": utcnow()},
])
def test_existing_target_human_intent_is_never_overwritten(
    client, session_factory, review_candidate, reassign_target, reassign_payload, changes,
):
    item = review_candidate()
    target_id = reassign_target(item)
    with session_factory() as db:
        db.add(CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id, **changes))
        db.commit()
    target = client.get(path(item) + "/reassign-targets").json()["items"][0]
    assert not target["selectable"] and target["blocked_reason"] == "target_already_reviewed"
    response = client.post(path(item) + "/reassign", json=reassign_payload(item, target_id))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "target_already_reviewed"
    assert client.get(path(item)).json() == item
    with session_factory() as db:
        assert db.query(IssueAction).count() == 0


@pytest.mark.parametrize("changes,code", [
    ({"platform": "different"}, "scope_mismatch"),
    ({"shop_id": "different"}, "scope_mismatch"),
    ({"product_id": "different"}, "scope_mismatch"),
    ({"status": "resolved"}, "target_changed"),
    ({"merged_into_id": "source"}, "target_changed"),
    ({"title": "改名了"}, "target_changed"),
    ({"category_id": "quality"}, "target_changed"),
])
def test_target_change_after_selection_is_rechecked(
    client, session_factory, review_candidate, reassign_target, reassign_payload, changes, code,
):
    item = review_candidate()
    target_id = reassign_target(item)
    payload = reassign_payload(item, target_id)
    with session_factory() as db:
        target = db.get(Issue, target_id)
        for key, value in changes.items():
            setattr(target, key, item["issue"]["id"] if value == "source" else value)
        db.commit()
    response = client.post(path(item) + "/reassign", json=payload)
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    with session_factory() as db:
        assert db.query(IssueAction).count() == 0


def test_new_target_link_invalidates_selection_token(
    client, session_factory, review_candidate, reassign_target, reassign_payload,
):
    item = review_candidate()
    target_id = reassign_target(item)
    payload = reassign_payload(item, target_id)
    with session_factory() as db:
        db.add(CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id))
        db.commit()
    response = client.post(path(item) + "/reassign", json=payload)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "target_changed"


@pytest.mark.parametrize("change", ["body", "decision", "evidence", "analysis"])
def test_source_changes_cannot_be_reassigned_from_stale_page(
    client, session_factory, review_candidate, review_payload, reassign_target, reassign_payload,
    change,
):
    item = review_candidate()
    target_id = reassign_target(item)
    payload = reassign_payload(item, target_id)
    if change == "decision":
        client.post(path(item) + "/decisions", json=review_payload(item, "reject"))
    else:
        with session_factory() as db:
            if change == "body":
                db.get(Comment, item["comment"]["id"]).body = "已更改原文"
            elif change == "evidence":
                db.get(CommentIssue, item["link"]["id"]).evidence_text = "不同的证据"
            else:
                db.get(Comment, item["comment"]["id"]).analysis_status = "queued"
            db.commit()
    response = client.post(path(item) + "/reassign", json=payload)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "review_changed"


@pytest.mark.parametrize("change,code", [
    ("rejected", "source_not_assignable"), ("evidence", "invalid_evidence"),
])
def test_fresh_page_does_not_bypass_source_eligibility(
    client, session_factory, review_candidate, reassign_target, reassign_payload, change, code,
):
    item = review_candidate()
    payload = reassign_payload(item, reassign_target(item))
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        if change == "rejected":
            link.status = "rejected"
        else:
            link.evidence_verified = False
        db.commit()
    fresh = client.get(path(item)).json()
    assert not fresh["can_reassign"] and fresh["reassign_blocked_reason"] == code
    response = client.post(path(item) + "/reassign", json={
        **payload, "expected_token": fresh["token"],
    })
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert client.get(path(item) + "/reassign-targets").status_code == 409


def test_target_listing_is_scoped_searchable_and_paginated(
    client, review_candidate, reassign_target,
):
    item = review_candidate()
    allowed = [reassign_target(item, title=title) for title in ("A拉链", "B拉链", "C质量100%")]
    for changes in ({"platform": "other"}, {"shop_id": "other"}, {"product_id": "other"},
                    {"status": "resolved"}, {"merged_into_id": item["issue"]["id"]}):
        reassign_target(item, **changes)
    response = client.get(path(item) + "/reassign-targets?limit=1&offset=1").json()
    assert response["total"] == 3 and len(response["items"]) == 1
    assert response["items"][0]["issue"]["id"] == allowed[1]
    response = client.get(path(item) + "/reassign-targets", params={"q": "%"}).json()
    assert response["total"] == 1 and response["items"][0]["issue"]["id"] == allowed[2]
    assert client.get(path(item) + "/reassign-targets?limit=0").status_code == 422


def test_validation_missing_target_same_group_reason_and_identity(
    client, review_candidate, reassign_target, reassign_payload,
):
    item = review_candidate()
    payload = reassign_payload(item, reassign_target(item))
    for changes in ({"note": " \n "}, {"note": "字" * 501}, {"operator": "forged"}):
        assert client.post(path(item) + "/reassign", json={**payload, **changes}).status_code == 422
    response = client.post(path(item) + "/reassign", json={
        **payload, "target_issue_id": item["issue"]["id"],
    })
    assert response.status_code == 409 and response.json()["detail"]["code"] == "same_issue"
    assert client.post(path(item) + "/reassign", json={
        **payload, "target_issue_id": str(uuid.uuid4()),
    }).status_code == 404
    assert client.post("/comment-issues/99999/reassign", json=payload).status_code == 404
    assert client.get(path(item)).json() == item


@pytest.mark.parametrize("existing", [False, True])
def test_second_audit_failure_rolls_back_both_links_and_first_audit(
    client, engine, session_factory, review_candidate, reassign_target, reassign_payload, existing,
):
    item = review_candidate()
    target_id = reassign_target(item)
    if existing:
        with session_factory() as db:
            db.add(CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id))
            db.commit()
    payload = reassign_payload(item, target_id)
    inserts = 0

    def fail(conn, cursor, statement, parameters, context, executemany):
        nonlocal inserts
        if statement.lstrip().startswith("INSERT INTO issue_actions"):
            inserts += 1
            if inserts == 2:
                raise RuntimeError("second audit failed")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="second audit failed"):
            client.post(path(item) + "/reassign", json=payload)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert client.get(path(item)).json() == item
    with session_factory() as db:
        assert db.query(IssueAction).count() == 0
        assert db.query(CommentIssue).count() == (2 if existing else 1)
        if existing:
            assert db.query(CommentIssue).filter_by(issue_id=target_id).one().status == "suggested"


def test_worker_rerun_preserves_both_sides_of_regrouping(
    client, session_factory, review_candidate, reassign_target, reassign_payload, worker_setup,
):
    item = review_candidate()
    response = client.post(path(item) + "/reassign", json=reassign_payload(
        item, reassign_target(item),
    ))
    assert response.status_code == 200
    target_path = f"/comment-issues/{response.json()['target_link_id']}"
    original = client.get(path(item)).json()
    target = client.get(target_path).json()
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    for url, before in [(path(item), original), (target_path, target)]:
        after = client.get(url).json()
        assert after["link"] == before["link"]
        assert after["actions"] == before["actions"]
        assert after["can_revise"]
