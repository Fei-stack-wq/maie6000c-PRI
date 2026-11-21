"""Explicit reversal of a saved decision, never a silent overwrite or reclassification."""
import pytest
from sqlalchemy import event

from services.common.models import Comment, CommentIssue, IssueAction, Job


def path(item):
    return f"/comment-issues/{item['link']['id']}"


def initial(client, review_candidate, review_payload, decision="accept"):
    item = review_candidate()
    request = review_payload(item, decision)
    result = client.post(path(item) + "/decisions", json=request)
    assert result.status_code == 200
    return client.get(path(item)).json(), request, result.json()


@pytest.mark.parametrize("old,new", [("accept", "reject"), ("reject", "accept")])
def test_revision_appends_history_and_updates_counts(
    client, session_factory, review_candidate, review_payload, old, new,
):
    item, _, first_receipt = initial(client, review_candidate, review_payload, old)
    first_action = item["actions"][0]
    assert item["can_revise"] and not item["can_decide"]
    payload = {**review_payload(item, new, "再次核对原文，纠正先前判断"), "mode": "revise"}
    result = client.post(path(item) + "/decisions", json=payload)
    assert result.status_code == 200, result.text
    current = client.get(path(item)).json()
    assert current["review_version"] == item["review_version"] + 1
    assert current["link"]["status"] == ("accepted" if new == "accept" else "rejected")
    latest, original = current["actions"]
    assert original == first_action
    assert latest["action"] == "change"
    assert latest["from_status"] == item["link"]["status"]
    assert latest["to_status"] == current["link"]["status"]
    assert latest["payload_json"]["previous_action_id"] == first_receipt["action_id"]
    assert latest["payload_json"]["before"]["decided_by"] == first_action["operator"]
    assert latest["payload_json"]["snapshot"]["body"] == item["comment"]["body"]
    assert current["comment"]["has_issue"] == item["comment"]["has_issue"]
    assert current["issue"]["status"] == item["issue"]["status"]
    assert client.get("/review-queue").json()["total"] == 0
    assert client.get("/review-queue?status=reviewed").json()["total"] == 1
    assert client.get("/stats/summary").json()["human_accepted_count"] == (new == "accept")
    with session_factory() as db:
        assert db.get(CommentIssue, item["link"]["id"]).origin == "ai"


def test_replay_of_initial_or_revision_receipt_never_undoes_later_decision(
    client, review_candidate, review_payload,
):
    item, first_request, first_receipt = initial(client, review_candidate, review_payload)
    request = {**review_payload(item, "reject"), "mode": "revise"}
    revised = client.post(path(item) + "/decisions", json=request)
    assert revised.status_code == 200
    for payload, expected in [(request, revised.json()), (first_request, first_receipt)]:
        response = client.post(path(item) + "/decisions", json=payload)
        assert response.status_code == 200
        assert response.json() == expected
    current = client.get(path(item)).json()
    assert current["link"]["status"] == "rejected"
    assert len(current["actions"]) == 2


def test_initial_receipt_hash_is_compatible_with_first_stage(
    client, session_factory, review_candidate, review_payload,
):
    from services.api.app.reviews.rules import digest

    item, request, receipt = initial(client, review_candidate, review_payload)
    # The original first-stage request had no mode field. This is its exact hash contract.
    with session_factory() as db:
        action = db.get(IssueAction, receipt["action_id"])
        assert action.request_hash == digest({
            "link_id": item["link"]["id"], "operator": "demo-reviewer", **request,
        })
    response = client.post(path(item) + "/decisions", json={**request, "mode": "initial"})
    assert response.status_code == 200 and response.json() == receipt


@pytest.mark.parametrize("old,new", [("accept", "reject"), ("reject", "accept")])
def test_revision_requires_reason_in_both_directions(
    client, review_candidate, review_payload, old, new,
):
    item, _, _ = initial(client, review_candidate, review_payload, old)
    payload = {**review_payload(item, new, " \n "), "mode": "revise"}
    assert client.post(path(item) + "/decisions", json=payload).status_code == 422
    assert len(client.get(path(item)).json()["actions"]) == 1


def test_modes_and_noop_are_not_interchangeable(client, review_candidate, review_payload):
    item = review_candidate()
    result = client.post(path(item) + "/decisions", json={
        **review_payload(item), "mode": "revise",
    })
    assert result.status_code == 409 and result.json()["detail"]["code"] == "not_reviewed"
    assert client.post(path(item) + "/decisions", json=review_payload(item)).status_code == 200
    item = client.get(path(item)).json()
    result = client.post(path(item) + "/decisions", json=review_payload(item, "reject"))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "already_reviewed"
    result = client.post(path(item) + "/decisions", json={
        **review_payload(item), "mode": "revise",
    })
    assert result.status_code == 409 and result.json()["detail"]["code"] == "decision_unchanged"
    assert len(client.get(path(item)).json()["actions"]) == 1


def test_old_revision_token_and_reused_key_are_rejected(client, review_candidate, review_payload):
    item, _, _ = initial(client, review_candidate, review_payload)
    request = {**review_payload(item, "reject"), "mode": "revise"}
    assert client.post(path(item) + "/decisions", json=request).status_code == 200
    stale = {**review_payload(item, "reject"), "mode": "revise"}
    assert client.post(path(item) + "/decisions", json=stale).status_code == 409
    changed = {**request, "note": "使用同一编号但改变内容"}
    result = client.post(path(item) + "/decisions", json=changed)
    assert result.json()["detail"]["code"] == "idempotency_conflict"
    assert len(client.get(path(item)).json()["actions"]) == 2


def test_changed_body_blocks_even_a_fresh_revision_page(
    client, session_factory, review_candidate, review_payload,
):
    item, _, _ = initial(client, review_candidate, review_payload)
    with session_factory() as db:
        db.get(Comment, item["comment"]["id"]).body = "评论的内容已改变"
        db.commit()
    current = client.get(path(item)).json()
    assert not current["can_revise"]
    assert current["revision_blocked_reason"] == "source_changed"
    result = client.post(path(item) + "/decisions", json={
        **review_payload(current, "reject"), "mode": "revise",
    })
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "source_changed"


def test_revision_remains_possible_after_worker_reanalysis_and_is_preserved(
    client, session_factory, review_candidate, review_payload, worker_setup,
):
    item, _, _ = initial(client, review_candidate, review_payload)
    def rerun():
        with session_factory() as db:
            db.add(Job(comment_id=item["comment"]["id"]))
            db.commit()
            claim = worker_setup.claim_next_pending_job(db)
        assert worker_setup.process_job(claim) == "completed"
    rerun()
    current = client.get(path(item)).json()
    assert current["can_revise"]
    assert current["link"]["analysis_run_id"] == item["link"]["analysis_run_id"]
    assert client.post(path(item) + "/decisions", json={
        **review_payload(current, "reject"), "mode": "revise",
    }).status_code == 200
    rerun()
    current = client.get(path(item)).json()
    assert current["link"]["status"] == "rejected"
    assert len(current["actions"]) == 2
    assert current["can_revise"]


def test_revision_rollback_keeps_original_decision_and_history(
    client, engine, session_factory, review_candidate, review_payload,
):
    item, _, _ = initial(client, review_candidate, review_payload)
    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO issue_actions"):
            raise RuntimeError("revision audit failure")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="revision audit failure"):
            client.post(path(item) + "/decisions", json={
                **review_payload(item, "reject"), "mode": "revise",
            })
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert client.get(path(item)).json() == item
