"""Group lifecycle, fresh supporting evidence, immutable notes, and Worker integration."""
import uuid

import pytest
from sqlalchemy import event

from services.common.models import Comment, CommentIssue, Issue, IssueAction


def path(item):
    return f"/issues/{item['issue']['id']}/actions"


def fresh(client, item):
    return client.get(f"/review-issues/{item['issue']['id']}").json()


def test_complete_lifecycle_keeps_link_decisions_and_records_followups(
    client, issue_candidate, issue_payload,
):
    link, item = issue_candidate()
    initial_version = item["issue"]["version"]
    assert item["issue"]["status"] == "proposed"
    assert item["valid_accepted_count"] == 1 and item["actions"] == []
    previous_actions = []
    reopen_count = 0
    for index, (action, status) in enumerate([
        ("confirm", "confirmed"), ("follow_up", "confirmed"), ("resolve", "resolved"),
        ("reopen", "proposed"), ("confirm", "confirmed"), ("dismiss", "dismissed"),
        ("reopen", "proposed"),
    ], 1):
        result = client.post(path(item), json=issue_payload(item, action, "记录：" + action))
        assert result.status_code == 200, result.text
        item = fresh(client, item)
        assert item["issue"]["status"] == status
        assert item["issue"]["version"] == initial_version + index
        reopen_count += action == "reopen"
        assert item["issue"]["reopen_count"] == reopen_count
        assert bool(item["issue"]["resolved_at"]) == (status == "resolved")
        assert item["actions"][1:] == previous_actions
        audit = item["actions"][0]
        assert audit["comment_issue_id"] is None and audit["action"] == action
        assert audit["payload_json"]["previous_action_id"] == (
            previous_actions[0]["id"] if previous_actions else None
        )
        assert audit["payload_json"]["accepted_evidence"][0]["body"] == link["comment"]["body"]
        assert audit["payload_json"]["valid_accepted_count"] == 1
        previous_actions = item["actions"]
        current = client.get(f"/comment-issues/{link['link']['id']}").json()
        assert current["link"] == link["link"] and current["actions"] == link["actions"]
        assert current["comment"] == link["comment"]
        assert client.get("/stats/summary").json()["human_accepted_count"] == 1


def test_ai_suggestion_alone_cannot_confirm_but_can_be_dismissed(
    client, issue_candidate, issue_payload,
):
    _, item = issue_candidate(accepted=False)
    assert item["allowed_actions"] == ["dismiss"]
    result = client.post(path(item), json=issue_payload(item))
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "no_valid_accepted_evidence"
    assert client.post(path(item), json=issue_payload(item, "dismiss")).status_code == 200
    assert fresh(client, item)["issue"]["suggested_count"] == 1


@pytest.mark.parametrize("change,reason", [
    ("body", "source_changed"), ("evidence", "invalid_evidence"),
    ("queued", "analysis_not_ready"), ("scope", "scope_mismatch"),
    ("superseded", "suggestion_superseded"),
])
def test_confirmation_requires_current_valid_accepted_evidence(
    client, session_factory, issue_candidate, issue_payload, change, reason,
):
    from services.common.models import utcnow

    link, item = issue_candidate()
    with session_factory() as db:
        if change == "body":
            db.get(Comment, link["comment"]["id"]).body = "更新后的原文"
        elif change == "evidence":
            db.get(CommentIssue, link["link"]["id"]).evidence_verified = False
        elif change == "queued":
            db.get(Comment, link["comment"]["id"]).analysis_status = "queued"
        elif change == "scope":
            db.get(Comment, link["comment"]["id"]).shop_id = "different-shop"
        else:
            db.get(CommentIssue, link["link"]["id"]).superseded_at = utcnow()
        db.commit()
    # Both a stale page and a freshly fetched ineligible page are refused.
    result = client.post(path(item), json=issue_payload(item))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "issue_changed"
    item = fresh(client, item)
    assert item["valid_accepted_count"] == 0 and item["invalid_accepted_count"] == 1
    evidence = client.get(f"/review-issues/{item['issue']['id']}/evidence").json()
    assert evidence["items"][0]["blocked_reason"] == reason
    result = client.post(path(item), json=issue_payload(item))
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "no_valid_accepted_evidence"


@pytest.mark.parametrize("status,action", [
    ("proposed", "follow_up"), ("proposed", "resolve"), ("proposed", "reopen"),
    ("confirmed", "confirm"), ("confirmed", "reopen"),
    ("resolved", "confirm"), ("resolved", "follow_up"), ("resolved", "dismiss"),
    ("dismissed", "resolve"), ("dismissed", "follow_up"),
])
def test_illegal_transitions_are_rejected_even_with_fresh_token(
    client, session_factory, issue_candidate, issue_payload, status, action,
):
    _, item = issue_candidate()
    with session_factory() as db:
        db.get(Issue, item["issue"]["id"]).status = status
        db.commit()
    item = fresh(client, item)
    result = client.post(path(item), json=issue_payload(item, action))
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "invalid_issue_transition"
    assert fresh(client, item)["actions"] == []


@pytest.mark.parametrize("action", ["confirm", "follow_up", "resolve", "dismiss", "reopen"])
def test_all_issue_actions_require_reason(client, issue_candidate, issue_payload, action):
    _, item = issue_candidate()
    response = client.post(path(item), json=issue_payload(item, action, " \n "))
    assert response.status_code == 422


def test_input_identity_unsupported_actions_and_missing_group(
    client, issue_candidate, issue_payload,
):
    _, item = issue_candidate()
    payload = issue_payload(item)
    for changes in ({"operator": "forged"}, {"action": "merge_into"}, {"note": "字" * 501},
                    {"expected_token": ""}, {"request_id": "-" * 36}):
        assert client.post(path(item), json={**payload, **changes}).status_code == 422
    assert client.post(f"/issues/{uuid.uuid4()}/actions", json=payload).status_code == 404


def test_idempotency_and_stale_versions_do_not_undo_followup(
    client, issue_candidate, issue_payload,
):
    _, item = issue_candidate()
    first_payload = issue_payload(item)
    first = client.post(path(item), json=first_payload)
    assert first.status_code == 200
    old = item
    item = fresh(client, item)
    follow_payload = issue_payload(item, "follow_up", "已安排排查，等待反馈")
    follow = client.post(path(item), json=follow_payload)
    assert follow.status_code == 200
    saved = fresh(client, item)
    for payload, response in [(first_payload, first), (follow_payload, follow)]:
        assert client.post(path(item), json=payload).json() == response.json()
    assert fresh(client, item) == saved
    result = client.post(path(item), json=issue_payload(old, "dismiss"))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "issue_changed"
    result = client.post(path(item), json={**follow_payload, "note": "改写旧编号的内容"})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "idempotency_conflict"


def test_link_changes_invalidate_group_page_and_group_changes_invalidate_link_page(
    client, issue_candidate, issue_payload, review_payload,
):
    link, item = issue_candidate()
    url = f"/comment-issues/{link['link']['id']}"
    assert client.post(url + "/decisions", json={
        **review_payload(link, "reject"), "mode": "revise",
    }).status_code == 200
    result = client.post(path(item), json=issue_payload(item))
    assert result.status_code == 409 and result.json()["detail"]["code"] == "issue_changed"
    rejected = client.get(url).json()
    item = fresh(client, item)
    assert client.post(path(item), json=issue_payload(item, "dismiss")).status_code == 200
    response = client.post(url + "/decisions", json={
        **review_payload(rejected), "mode": "revise",
    })
    assert response.status_code == 409
    closed = client.get(url).json()
    assert not closed["can_revise"] and closed["revision_blocked_reason"] == "issue_not_active"
    item = fresh(client, item)
    assert client.post(path(item), json=issue_payload(item, "reopen")).status_code == 200
    assert client.get(url).json()["can_revise"]


def test_merged_group_cannot_be_reopened(client, session_factory, issue_candidate, issue_payload):
    _, item = issue_candidate()
    _, target = issue_candidate(product="another-product")
    with session_factory() as db:
        issue = db.get(Issue, item["issue"]["id"])
        issue.status, issue.merged_into_id = "dismissed", target["issue"]["id"]
        db.commit()
    item = fresh(client, item)
    assert item["allowed_actions"] == []
    response = client.post(path(item), json=issue_payload(item, "reopen"))
    assert response.status_code == 409 and response.json()["detail"]["code"] == "issue_merged"


def test_issue_lists_evidence_pagination_and_group_history_are_separate(
    client, session_factory, issue_candidate, issue_payload,
):
    link, item = issue_candidate()
    second, same = issue_candidate()
    issue_candidate(product="different-product")
    with session_factory() as db:
        db.get(Issue, item["issue"]["id"]).title = "质量100%检查"
        db.commit()
    item = fresh(client, item)
    assert item["issue"]["id"] == same["issue"]["id"]
    assert item["valid_accepted_count"] == 2 and item["actions"] == []
    assert client.post(path(item), json=issue_payload(item)).status_code == 200
    listing = client.get("/review-issues", params={
        "status": "confirmed", "product_id": "bag-1", "category_id": "quality",
    }).json()
    assert listing["total"] == 1 and listing["items"][0]["actions"] == []
    assert client.get("/review-issues", params={"status": "all", "q": "%"}).json()["total"] == 1
    assert client.get("/review-issues?status=all&limit=1&offset=1").json()["total"] == 2
    evidence = client.get(f"/review-issues/{item['issue']['id']}/evidence?limit=1&offset=1").json()
    assert evidence["total"] == 2 and len(evidence["items"]) == 1
    assert evidence["items"][0]["review"]["link"]["id"] == second["link"]["id"]
    assert len(fresh(client, item)["actions"]) == 1
    assert len(client.get(f"/issues/{item['issue']['id']}").json()["actions"]) == 3


def test_followup_audit_failure_rolls_back_version_and_status(
    client, engine, issue_candidate, issue_payload,
):
    _, item = issue_candidate()
    assert client.post(path(item), json=issue_payload(item)).status_code == 200
    item = fresh(client, item)

    def fail(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith("INSERT INTO issue_actions"):
            raise RuntimeError("group audit failed")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="group audit failed"):
            client.post(path(item), json=issue_payload(item, "resolve"))
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert fresh(client, item) == item


def test_manual_evidence_can_confirm_without_ai_success(
    client, session_factory, manual_candidate, manual_payload, issue_payload,
):
    comment = manual_candidate()
    with session_factory() as db:
        db.get(Comment, comment["comment"]["id"]).analysis_status = "failed"
        db.commit()
    comment = client.get(f"/review-comments/{comment['comment']['id']}").json()
    result = client.post(f"/review-comments/{comment['comment']['id']}/manual-links",
                         json=manual_payload(comment))
    assert result.status_code == 200
    item = client.get(f"/review-issues/{result.json()['issue_id']}").json()
    assert item["valid_accepted_count"] == 1
    assert client.post(path(item), json=issue_payload(item)).status_code == 200


def test_closed_group_is_not_silently_reopened_by_worker(
    client, session_factory, issue_candidate, issue_payload, review_candidate,
):
    link, item = issue_candidate()
    for action in ("confirm", "resolve"):
        assert client.post(path(item), json=issue_payload(item, action)).status_code == 200
        item = fresh(client, item)
    saved_history = item["actions"]
    new = review_candidate()
    assert new["issue"]["id"] != item["issue"]["id"]
    assert new["issue"]["status"] == "proposed"
    current = fresh(client, item)
    assert current["issue"]["status"] == "resolved" and current["actions"] == saved_history
    with session_factory() as db:
        assert db.get(CommentIssue, link["link"]["id"]).status == "accepted"
        assert db.query(IssueAction).filter(IssueAction.comment_issue_id.is_(None)).count() == 2
