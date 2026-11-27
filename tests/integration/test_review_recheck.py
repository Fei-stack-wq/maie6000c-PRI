"""Fresh human evidence after source edits, preserving the original decision and body."""

import uuid

import pytest
from sqlalchemy import event

from services.api.app.reviews.rules import body_hash
from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, IssueAction, Job


def path(item):
    return f"/comment-issues/{item['link']['id']}"


def fresh(client, item):
    return client.get(path(item)).json()


def test_changed_original_reaccepts_with_unicode_evidence_and_resets_group(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
):
    old, item = recheck_case()
    assert item["needs_recheck"] and item["can_recheck"] and not item["can_revise"]
    assert item["evidence_body"] == old["comment"]["body"]
    assert item["link"] == old["link"] and item["actions"] == old["actions"]
    assert client.get("/review-queue?status=needs_recheck").json()["total"] == 1
    quote = "拉链又卡住了。"
    start = item["comment"]["body"].rindex(quote)
    payload = recheck_payload(
        item, evidence=quote, evidence_start=start, evidence_end=start + len(quote)
    )
    with session_factory() as db:
        run_count = db.query(AnalysisRun).count()
        jobs = [(j.id, j.status, j.attempts) for j in db.query(Job).all()]
    result = client.post(path(item) + "/recheck", json=payload)
    assert result.status_code == 200, result.text
    new = fresh(client, item)
    assert new["link"]["id"] == old["link"]["id"]
    assert new["link"]["status"] == "accepted" and new["link"]["origin"] == "human"
    assert new["link"]["evidence_start"] == start and new["link"]["evidence_end"] == start + len(
        quote
    )
    assert new["link"]["evidence_body_hash"] == body_hash(item["comment"]["body"])
    assert new["link"]["analysis_run_id"] is None and new["link"]["comment_version"] == 2
    assert new["review_version"] == old["review_version"] + 1
    assert new["comment"] == item["comment"]  # AI verdict/current run/source remain unchanged.
    assert not new["needs_recheck"] and not new["can_recheck"] and new["can_revise"]
    assert new["issue"]["status"] == "proposed"
    assert new["issue"]["version"] == item["issue"]["version"] + 1
    assert new["actions"][1:] == old["actions"]
    audit = new["actions"][0]["payload_json"]
    assert audit["operation"] == "recheck_evidence"
    assert audit["before"]["body"] == old["comment"]["body"]
    assert audit["before"]["evidence_text"] == old["link"]["evidence_text"]
    assert (
        audit["after"]["body"] == item["comment"]["body"]
        and audit["after"]["evidence_text"] == quote
    )
    assert audit["previous_action_id"] == old["actions"][0]["id"]
    group = client.get(f"/review-issues/{new['issue']['id']}").json()
    assert group["valid_accepted_count"] == 1 and "confirm" in group["allowed_actions"]
    assert group["actions"][0]["payload_json"]["link_action_id"] == result.json()["action_id"]
    assert group["actions"][1]["action"] == "confirm"
    assert client.get("/review-queue?status=needs_recheck").json()["total"] == 0
    with session_factory() as db:
        assert db.query(AnalysisRun).count() == run_count
        assert [(j.id, j.status, j.attempts) for j in db.query(Job).all()] == jobs


def test_no_longer_supported_can_be_rejected_without_quote_then_explicitly_reassessed(
    client,
    recheck_case,
    recheck_payload,
    review_payload,
):
    old, item = recheck_case(body="补充说明：拉链已恢复正常，目前没有问题。")
    result = client.post(path(item) + "/recheck", json=recheck_payload(item, "reject"))
    assert result.status_code == 200
    new = fresh(client, item)
    assert new["link"]["status"] == "rejected" and not new["needs_recheck"]
    assert new["link"]["evidence_text"] is None and new["link"]["evidence_start"] is None
    assert new["link"]["evidence_end"] is None and not new["link"]["evidence_verified"]
    assert (
        new["actions"][0]["payload_json"]["before"]["evidence_text"] == old["link"]["evidence_text"]
    )
    assert client.get("/review-queue?status=needs_recheck").json()["total"] == 0
    # A later correction must supply evidence; ordinary accept cannot recycle the old quote.
    rejected = client.post(
        path(item) + "/decisions", json={**review_payload(new), "mode": "revise"}
    )
    assert rejected.status_code == 409 and rejected.json()["detail"]["code"] == "invalid_evidence"
    assert new["can_recheck"]
    noop = client.post(path(item) + "/recheck", json=recheck_payload(new, "reject"))
    assert noop.status_code == 409 and noop.json()["detail"]["code"] == "recheck_unchanged"
    corrected = client.post(
        path(item) + "/recheck", json=recheck_payload(new, evidence="拉链已恢复正常")
    )
    assert corrected.status_code == 200
    assert len(fresh(client, item)["actions"]) == len(old["actions"]) + 2


def test_rejected_old_decision_can_be_reaccepted_on_changed_source(
    client,
    review_candidate,
    review_payload,
    update_review_source,
    recheck_payload,
):
    item = review_candidate()
    assert (
        client.post(path(item) + "/decisions", json=review_payload(item, "reject")).status_code
        == 200
    )
    item = update_review_source(item)
    assert item["needs_recheck"]
    assert client.post(path(item) + "/recheck", json=recheck_payload(item)).status_code == 200
    current = fresh(client, item)
    assert [a["to_status"] for a in current["actions"]] == ["accepted", "rejected"]


@pytest.mark.parametrize("decision", ["accept", "reject"])
def test_recheck_allows_failed_reanalysis_without_fabricating_ai(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
    decision,
):
    _, item = recheck_case(finish=False)
    with session_factory() as db:
        comment = db.get(Comment, item["comment"]["id"])
        comment.analysis_status, comment.analysis_error = "failed", "AI unavailable"
        for job in db.query(Job).filter(Job.status == "pending"):
            job.status = "failed"
        db.commit()
    item = fresh(client, item)
    assert item["can_recheck"]
    assert (
        client.post(path(item) + "/recheck", json=recheck_payload(item, decision)).status_code
        == 200
    )
    new = fresh(client, item)
    assert new["comment"] == item["comment"] and new["link"]["analysis_run_id"] is None
    assert new["can_revise"]


def test_manual_evidence_without_original_ai_run_can_be_refreshed(
    client,
    manual_candidate,
    manual_payload,
    update_review_source,
    recheck_payload,
):
    comment = manual_candidate()
    response = client.post(
        f"/review-comments/{comment['comment']['id']}/manual-links", json=manual_payload(comment)
    )
    old = client.get(f"/comment-issues/{response.json()['link_id']}").json()
    item = update_review_source(old, body="售后第二周仍未回复。")
    assert item["evidence_body"] == old["comment"]["body"]
    assert client.post(path(item) + "/recheck", json=recheck_payload(item)).status_code == 200
    new = fresh(client, item)
    assert new["actions"][0]["payload_json"]["before"]["analysis_run_id"] is None
    assert new["actions"][1] == old["actions"][0]


@pytest.mark.parametrize(
    "state",
    ["received", "queued", "analyzing", "closed", "merged", "archived", "scope", "wrong_run"],
)
def test_invalid_context_cannot_be_rechecked_even_with_current_token(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
    state,
):
    _, item = recheck_case()
    with session_factory() as db:
        comment = db.get(Comment, item["comment"]["id"])
        issue = db.get(Issue, item["issue"]["id"])
        link = db.get(CommentIssue, item["link"]["id"])
        if state in ("received", "queued", "analyzing"):
            comment.analysis_status = state
        elif state == "closed":
            issue.status = "resolved"
        elif state == "merged":
            issue.merged_into_id = issue.id
        elif state == "archived":
            from services.common.models import utcnow

            link.superseded_at = utcnow()
        elif state == "scope":
            comment.shop_id = "other"
        else:
            other = Comment(
                platform="demo",
                shop_id="shop",
                product_id="other",
                source_review_id="other",
                body="其他原文",
                content_hash="1" * 64,
            )
            db.add(other)
            db.flush()
            db.get(AnalysisRun, link.analysis_run_id).comment_id = other.id
        db.commit()
    item = fresh(client, item)
    assert not item["can_recheck"]
    result = client.post(path(item) + "/recheck", json=recheck_payload(item))
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == item["recheck_blocked_reason"]
    assert len(fresh(client, item)["actions"]) == len(item["actions"])


def test_closed_issue_must_be_reopened_before_recheck(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
    issue_payload,
):
    _, item = recheck_case()
    with session_factory() as db:
        db.get(Issue, item["issue"]["id"]).status = "resolved"
        db.commit()
    group = client.get(f"/review-issues/{item['issue']['id']}").json()
    assert (
        client.post(
            f"/issues/{item['issue']['id']}/actions", json=issue_payload(group, "reopen")
        ).status_code
        == 200
    )
    item = fresh(client, item)
    assert item["can_recheck"]
    assert client.post(path(item) + "/recheck", json=recheck_payload(item)).status_code == 200


def test_unchanged_valid_links_and_unreviewed_ai_use_their_existing_workflow(
    client,
    issue_candidate,
    update_review_source,
    recheck_payload,
):
    old, _ = issue_candidate()
    assert not old["can_recheck"]
    reply = client.post(path(old) + "/recheck", json=recheck_payload(old))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "source_unchanged"
    suggestion, _ = issue_candidate(accepted=False)
    reply = client.post(path(suggestion) + "/recheck", json=recheck_payload(suggestion))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "not_human_managed"


@pytest.mark.parametrize(
    "changes",
    [
        {"note": " \n "},
        {"note": "字" * 501},
        {"operator": "forged"},
        {"request_id": "-" * 36},
        {"expected_token": "wrong"},
        {"decision": "change"},
        {"evidence_text": None},
        {"evidence_start": None},
        {"evidence_start": True},
        {"evidence_start": "0"},
        {"evidence_end": 0},
        {"evidence_text": " "},
        {"evidence_start": 5, "evidence_end": 2},
    ],
)
def test_input_validation(client, recheck_case, recheck_payload, changes):
    _, item = recheck_case()
    reply = client.post(path(item) + "/recheck", json={**recheck_payload(item), **changes})
    assert reply.status_code == 422


def test_verbatim_quotes_and_rejection_optional_evidence_are_validated(
    client,
    recheck_case,
    recheck_payload,
):
    _, item = recheck_case()
    for decision in ("accept", "reject"):
        for changes in (
            {"evidence_text": "编造证据"},
            {"evidence_end": 1999},
            {"evidence_start": 1},
        ):
            payload = {
                **recheck_payload(item, decision, evidence=item["comment"]["body"]),
                **changes,
            }
            assert client.post(path(item) + "/recheck", json=payload).status_code == 409
    payload = recheck_payload(item, "accept")
    for key in ("evidence_text", "evidence_start", "evidence_end"):
        payload.pop(key)
    assert client.post(path(item) + "/recheck", json=payload).status_code == 422
    assert (
        client.post("/comment-issues/999999/recheck", json=recheck_payload(item)).status_code == 404
    )


def test_receipts_stale_versions_and_old_decision_replay(
    client,
    recheck_case,
    recheck_payload,
    review_payload,
    update_review_source,
):
    old, item = recheck_case()
    assert client.post(path(item) + "/recheck", json=recheck_payload(old)).status_code == 409
    payload = recheck_payload(item)
    reply = client.post(path(item) + "/recheck", json=payload)
    assert reply.status_code == 200
    current = fresh(client, item)
    assert (
        client.post(
            path(item) + "/decisions",
            json={
                **review_payload(current, "reject"),
                "mode": "revise",
            },
        ).status_code
        == 200
    )
    rejected = fresh(client, item)
    assert client.post(path(item) + "/recheck", json=payload).json() == reply.json()
    assert fresh(client, item) == rejected
    assert (
        client.post(path(item) + "/recheck", json={**payload, "note": "新内容"}).status_code == 409
    )
    assert (
        client.post(
            path(item) + "/recheck", json={**payload, "request_id": str(uuid.uuid4())}
        ).status_code
        == 409
    )
    changed = update_review_source(item, body="第三次更新：拉链有时仍然卡住。")
    assert changed["needs_recheck"]
    assert client.post(path(item) + "/recheck", json=recheck_payload(rejected)).status_code == 409
    assert client.post(path(item) + "/recheck", json=payload).json() == reply.json()


def test_group_audit_failure_rolls_back_evidence_decision_and_issue(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
):
    _, item = recheck_case()
    group_url = f"/review-issues/{item['issue']['id']}"
    group = client.get(group_url).json()
    with session_factory() as db:
        count = db.query(IssueAction).count()

    def fail(mapper, conn, row):
        if row.comment_issue_id is None:
            raise RuntimeError("group audit unavailable")

    event.listen(IssueAction, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="group audit unavailable"):
            client.post(path(item) + "/recheck", json=recheck_payload(item))
    finally:
        event.remove(IssueAction, "before_insert", fail)
    assert fresh(client, item) == item and client.get(group_url).json() == group
    with session_factory() as db:
        assert db.query(IssueAction).count() == count


def test_missing_historical_body_is_explicit_not_fabricated(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
):
    _, item = recheck_case()
    with session_factory() as db:
        link = db.get(CommentIssue, item["link"]["id"])
        link.origin, link.evidence_body_hash = "human", "0" * 64
        db.commit()
    item = fresh(client, item)
    assert item["evidence_body"] is None and item["can_recheck"]
    assert client.post(path(item) + "/recheck", json=recheck_payload(item)).status_code == 200
    before = fresh(client, item)["actions"][0]["payload_json"]["before"]
    assert (
        before["body"] is None and not before["body_available"] and before["body_hash"] == "0" * 64
    )


def test_historical_body_falls_back_to_exact_revision_hash_not_stored_number(
    client,
    session_factory,
    recheck_case,
):
    old, item = recheck_case()
    with session_factory() as db:
        # A legacy audit with a mismatched body must not be presented as the old source.
        action = db.get(IssueAction, old["actions"][0]["id"])
        data = action.payload_json
        action.payload_json = {
            **data,
            "snapshot": {
                **data["snapshot"],
                "body": item["comment"]["body"],
            },
        }
        db.get(CommentIssue, item["link"]["id"]).comment_version = 999
        db.commit()
    assert fresh(client, item)["evidence_body"] == old["comment"]["body"]


def test_changed_queue_filters_before_pagination_and_includes_waiting_and_closed(
    client,
    session_factory,
    issue_candidate,
    update_review_source,
):
    first, _ = issue_candidate(product="one")
    second, _ = issue_candidate(product="two")
    issue_candidate(product="fresh")
    update_review_source(first)
    second = update_review_source(second, finish=False)
    with session_factory() as db:
        db.get(Issue, second["issue"]["id"]).status = "resolved"
        db.commit()
    data = client.get("/review-queue", params={"status": "needs_recheck", "limit": 1}).json()
    assert data["total"] == 2 and len(data["items"]) == 1
    other = client.get("/review-queue", params={"status": "needs_recheck", "offset": 1}).json()
    assert other["items"][0]["link"]["id"] != data["items"][0]["link"]["id"]
    filtered = client.get(
        "/review-queue",
        params={
            "status": "needs_recheck",
            "product_id": "two",
            "category_id": "quality",
        },
    ).json()
    assert filtered["total"] == 1 and not filtered["items"][0]["can_recheck"]
    assert (
        client.get(
            "/review-queue", params={"status": "needs_recheck", "category_id": "other"}
        ).json()["total"]
        == 0
    )


def test_worker_rerun_and_later_regroup_keep_refreshed_human_evidence(
    client,
    session_factory,
    recheck_case,
    recheck_payload,
    worker_setup,
    reassign_target,
    reassign_payload,
):
    _, item = recheck_case()
    assert client.post(path(item) + "/recheck", json=recheck_payload(item)).status_code == 200
    saved = fresh(client, item)
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    current = fresh(client, item)
    assert current["link"] == saved["link"] and current["actions"] == saved["actions"]
    target = reassign_target(current)
    result = client.post(path(item) + "/reassign", json=reassign_payload(current, target))
    assert result.status_code == 200
    moved = client.get(f"/comment-issues/{result.json()['target_link_id']}").json()
    assert moved["can_revise"] and not moved["needs_recheck"]
    assert moved["link"]["evidence_body_hash"] == saved["link"]["evidence_body_hash"]


def test_human_grouped_pending_suggestion_can_be_rechecked_after_source_edit(
    client,
    structure_case,
    structure_payload,
    update_review_source,
    recheck_payload,
):
    links, source, _ = structure_case()
    result = client.post(
        f"/issues/{source['issue']['id']}/split",
        json=structure_payload(
            source,
            ids=[links[1]["link"]["id"]],
        ),
    )
    child = client.get(f"/review-issues/{result.json()['target_issue_id']}/evidence").json()[
        "items"
    ][0]
    current = update_review_source(child["review"])
    assert current["link"]["status"] == "suggested" and current["can_recheck"]
    queue = client.get("/review-queue?status=needs_recheck").json()
    assert queue["total"] == 1 and queue["items"][0]["link"]["id"] == current["link"]["id"]
    assert client.post(path(current) + "/recheck", json=recheck_payload(current)).status_code == 200
    archived = fresh(client, links[1])
    assert not archived["needs_recheck"] and not archived["can_recheck"]
