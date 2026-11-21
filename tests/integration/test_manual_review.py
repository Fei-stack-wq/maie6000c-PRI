"""Manual evidence works without AI suggestions, while preserving facts and prior intent."""
import uuid

import pytest
from sqlalchemy import event

from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction, Job


def path(item):
    return f"/review-comments/{item['comment']['id']}"


@pytest.mark.parametrize("body,verdict", [
    ("售后一直没有回复。", "no"), ("Warranty support never replied.", "unknown"),
    ("拉链卡住了。", "yes"),
])
def test_manual_creation_preserves_ai_and_records_evidence(
    client, session_factory, manual_candidate, manual_payload, body, verdict,
):
    item = manual_candidate(body=body)
    assert item["comment"]["has_issue"] == verdict and item["can_add"]
    payload = manual_payload(item)
    response = client.post(path(item) + "/manual-links", json=payload)
    assert response.status_code == 200, response.text
    receipt = response.json()
    link = client.get(f"/comment-issues/{receipt['link_id']}").json()
    assert link["link"]["origin"] == "human" and link["link"]["status"] == "accepted"
    assert link["link"]["analysis_run_id"] is None
    assert link["link"]["evidence_verified"] and link["link"]["evidence_body_hash"]
    assert link["can_revise"] and link["can_reassign"]
    assert link["issue"]["status"] == "proposed" and link["issue"]["created_by"] == "human"
    assert link["comment"] == item["comment"]
    action = link["actions"][0]
    assert action["payload_json"]["operation"] == "manual_add"
    assert action["payload_json"]["created_issue"]
    assert action["payload_json"]["snapshot"]["body"] == body
    assert action["payload_json"]["ai_verdict"] == verdict
    assert action["note"] == payload["note"]
    assert client.get("/stats/summary").json()["human_accepted_count"] == 1
    assert client.get("/review-queue?status=reviewed").json()["total"] == 1
    assert client.post(path(item) + "/manual-links", json=payload).json() == receipt
    with session_factory() as db:
        assert db.query(AnalysisRun).count() == 1
        assert db.query(IssueAction).count() == 1


def test_failed_analysis_needs_no_fabricated_ai_run(
    client, session_factory, new_job, manual_payload, review_payload,
):
    job_id, comment_id, _ = new_job(body="售后未回复")
    with session_factory() as db:
        db.get(Comment, comment_id).analysis_status = "failed"
        db.get(Job, job_id).status = "failed"
        db.commit()
    item = client.get(f"/review-comments/{comment_id}").json()
    response = client.post(path(item) + "/manual-links", json=manual_payload(item))
    assert response.status_code == 200
    url = f"/comment-issues/{response.json()['link_id']}"
    link = client.get(url).json()
    assert link["can_revise"] and link["can_reassign"]
    assert client.post(url + "/decisions", json={
        **review_payload(link, "reject"), "mode": "revise",
    }).status_code == 200
    with session_factory() as db:
        assert db.query(AnalysisRun).count() == 0
        assert db.get(Comment, comment_id).analysis_status == "failed"
        assert db.get(Job, job_id).status == "failed"


@pytest.mark.parametrize("status", ["received", "queued", "analyzing"])
def test_manual_submission_waits_for_analysis_to_finish(
    client, session_factory, manual_candidate, manual_payload, status,
):
    item = manual_candidate()
    with session_factory() as db:
        db.get(Comment, item["comment"]["id"]).analysis_status = status
        db.commit()
    item = client.get(path(item)).json()
    assert not item["can_add"]
    result = client.post(path(item) + "/manual-links", json=manual_payload(item))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "analysis_not_ready"
    assert client.get(path(item) + "/targets").status_code == 409


@pytest.mark.parametrize("existing", [False, True])
def test_manual_evidence_links_existing_issue_or_reuses_unreviewed_suggestion(
    client, session_factory, manual_candidate, manual_payload, reassign_target, existing,
):
    item = manual_candidate()
    target_id = reassign_target(item)
    old_id = None
    if existing:
        with session_factory() as db:
            old = CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id,
                               evidence_text="旧建议", review_version=5)
            db.add(old)
            db.commit()
            old_id = old.id
        item = client.get(path(item)).json()
    target = client.get(path(item) + "/targets").json()["items"][0]
    payload = manual_payload(item, new_issue=None, target_issue_id=target_id,
                             expected_target_token=target["token"])
    result = client.post(path(item) + "/manual-links", json=payload)
    assert result.status_code == 200, result.text
    assert not result.json()["created_issue"]
    link = client.get(f"/comment-issues/{result.json()['link_id']}").json()
    if existing:
        assert result.json()["link_id"] == old_id and link["review_version"] == 6
        assert link["actions"][0]["payload_json"]["before"]["evidence_text"] == "旧建议"
    with session_factory() as db:
        assert db.query(Issue).count() == db.query(CommentIssue).count() == 1


def test_manual_input_preserves_repeated_unicode_evidence_position(
    client, manual_candidate, manual_payload,
):
    body = "😀 售后未回复。再次联系：售后未回复。"
    item = manual_candidate(body=body)
    text = "售后未回复。"
    start = body.rindex(text)
    response = client.post(path(item) + "/manual-links", json=manual_payload(
        item, text, evidence_start=start, evidence_end=start + len(text),
    ))
    assert response.status_code == 200
    link = client.get(f"/comment-issues/{response.json()['link_id']}").json()["link"]
    assert link["evidence_start"] == start
    assert link["evidence_text"] == body[link["evidence_start"]:link["evidence_end"]]


@pytest.mark.parametrize("changes,status", [
    ({"note": " \n "}, 422), ({"note": "字" * 501}, 422), ({"operator": "forged"}, 422),
    ({"evidence_text": "编造证据"}, 409), ({"evidence_start": 1}, 409),
    ({"evidence_end": 1999}, 409), ({"evidence_start": True}, 422),
    ({"evidence_text": " "}, 422),
    ({"new_issue": {"title": " ", "category_id": "other"}}, 422),
    ({"new_issue": {"title": "标题", "category_id": "invalid"}}, 422),
    ({"new_issue": None}, 422), ({"target_issue_id": "extra-target"}, 422),
])
def test_invalid_manual_inputs_do_not_create_groups(
    client, session_factory, manual_candidate, manual_payload, changes, status,
):
    item = manual_candidate()
    result = client.post(path(item) + "/manual-links", json=manual_payload(item, **changes))
    assert result.status_code == status, result.text
    with session_factory() as db:
        assert db.query(Issue).count() == db.query(IssueAction).count() == 0


def test_comment_changes_and_duplicate_requests_are_safe(
    client, session_factory, manual_candidate, manual_payload, review_payload,
):
    item = manual_candidate()
    payload = manual_payload(item)
    saved = client.post(path(item) + "/manual-links", json=payload).json()
    link_url = f"/comment-issues/{saved['link_id']}"
    link = client.get(link_url).json()
    assert client.post(link_url + "/decisions", json={
        **review_payload(link, "reject"), "mode": "revise",
    }).status_code == 200
    assert client.post(path(item) + "/manual-links", json=payload).json() == saved
    assert client.get(link_url).json()["link"]["status"] == "rejected"
    result = client.post(path(item) + "/manual-links", json={**payload, "note": "不同原因"})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "idempotency_conflict"
    result = client.post(path(item) + "/manual-links", json={
        **payload, "request_id": str(uuid.uuid4()),
    })
    assert result.status_code == 409 and result.json()["detail"]["code"] == "comment_changed"
    fresh = client.get(path(item)).json()
    with session_factory() as db:
        db.get(Comment, item["comment"]["id"]).body += "新内容"
        db.commit()
    result = client.post(path(item) + "/manual-links", json=manual_payload(fresh))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "comment_changed"
    changed = client.get(link_url).json()
    assert not changed["can_revise"] and changed["revision_blocked_reason"] == "source_changed"
    assert changed["actions"][-1]["payload_json"]["snapshot"]["body"] == item["comment"]["body"]


def test_existing_human_decision_and_target_change_are_protected(
    client, session_factory, manual_candidate, manual_payload, reassign_target,
):
    item = manual_candidate()
    target_id = reassign_target(item)
    target = client.get(path(item) + "/targets").json()["items"][0]
    payload = manual_payload(item, new_issue=None, target_issue_id=target_id,
                             expected_target_token=target["token"])
    with session_factory() as db:
        db.get(Issue, target_id).title = "已更名"
        db.commit()
    result = client.post(path(item) + "/manual-links", json=payload)
    assert result.status_code == 409 and result.json()["detail"]["code"] == "target_changed"
    with session_factory() as db:
        db.add(CommentIssue(comment_id=item["comment"]["id"], issue_id=target_id,
                            status="rejected", origin="human"))
        db.commit()
    fresh = client.get(path(item)).json()
    target = client.get(path(item) + "/targets").json()["items"][0]
    assert not target["selectable"]
    result = client.post(path(item) + "/manual-links", json={
        **payload, "expected_token": fresh["token"], "expected_target_token": target["token"],
    })
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "target_already_reviewed"


@pytest.mark.parametrize("field", ["platform", "shop_id", "product_id"])
def test_manual_target_scope_is_enforced(
    client, manual_candidate, manual_payload, reassign_target, field,
):
    item = manual_candidate()
    target_id = reassign_target(item, **{field: "different"})
    assert client.get(path(item) + "/targets").json()["total"] == 0
    response = client.post(path(item) + "/manual-links", json=manual_payload(
        item, new_issue=None, target_issue_id=target_id, expected_target_token="a" * 64,
    ))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "scope_mismatch"


def test_duplicate_titles_require_explicit_selection_of_existing_group(
    client, manual_candidate, manual_payload, reassign_target,
):
    item = manual_candidate()
    reassign_target(item, title="Warranty   Service", category_id="other")
    result = client.post(path(item) + "/manual-links", json=manual_payload(
        item, new_issue={"title": "warranty service", "category_id": "other"},
    ))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "duplicate_issue"


def test_comment_list_includes_no_unknown_failed_and_filters_and_pages(
    client, session_factory, manual_candidate,
):
    no = manual_candidate(body="售后 100% 未回复。")
    manual_candidate(body="Warranty support never replied.")
    yes = manual_candidate(body="拉链卡住了。", product="bag-2")
    assert client.get("/review-comments").json()["total"] == 2
    assert client.get("/review-comments?verdict=all&limit=1&offset=1").json()["total"] == 3
    assert len(client.get("/review-comments?limit=1").json()["items"]) == 1
    filtered = client.get("/review-comments?verdict=yes&product_id=bag-2").json()
    assert filtered["items"][0]["id"] == yes["comment"]["id"]
    searched = client.get("/review-comments", params={"q": "%"}).json()
    assert searched["items"][0]["id"] == no["comment"]["id"]
    with session_factory() as db:
        db.get(Comment, yes["comment"]["id"]).analysis_status = "failed"
        db.commit()
    assert client.get("/review-comments?verdict=failed").json()["total"] == 1
    assert client.get("/review-comments").json()["total"] == 3


def test_manual_audit_failure_rolls_back_new_group_and_link(
    client, engine, session_factory, manual_candidate, manual_payload,
):
    item = manual_candidate()

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO issue_actions"):
            raise RuntimeError("manual audit failed")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="manual audit failed"):
            client.post(path(item) + "/manual-links", json=manual_payload(item))
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    with session_factory() as db:
        assert db.query(Issue).count() == db.query(CommentIssue).count() == 0
        assert db.query(IssueAction).count() == 0


def test_manual_link_survives_worker_and_supports_regrouping_and_revision(
    client, session_factory, manual_candidate, manual_payload, worker_setup,
    reassign_target, reassign_payload, review_payload,
):
    item = manual_candidate()
    saved = client.post(path(item) + "/manual-links", json=manual_payload(item)).json()
    url = f"/comment-issues/{saved['link_id']}"
    before = client.get(url).json()
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    current = client.get(url).json()
    assert current["link"] == before["link"] and current["actions"] == before["actions"]
    target_id = reassign_target(item)
    result = client.post(url + "/reassign", json=reassign_payload(current, target_id))
    assert result.status_code == 200, result.text
    target_url = f"/comment-issues/{result.json()['target_link_id']}"
    target = client.get(target_url).json()
    assert target["link"]["evidence_body_hash"] == before["link"]["evidence_body_hash"]
    assert target["link"]["analysis_run_id"] is None and target["can_revise"]
    assert client.post(target_url + "/decisions", json={
        **review_payload(target, "reject"), "mode": "revise",
    }).status_code == 200
