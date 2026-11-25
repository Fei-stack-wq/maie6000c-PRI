"""Membership restructuring preserves decisions, anchors, history and concurrency tokens."""
import uuid

import pytest
from sqlalchemy import event

from services.common.models import (
    AnalysisRun, Comment, CommentIssue, Issue, IssueAction, Job, utcnow,
)


def detail(client, item):
    return client.get(f"/review-issues/{item['issue']['id']}").json()


def path(item, operation):
    return f"/issues/{item['issue']['id']}/{operation}"


def evidence(client, item):
    return client.get(f"/review-issues/{item['issue']['id']}/evidence").json()["items"]


def test_merge_preserves_all_decisions_and_both_histories(
    client, structure_case, structure_payload, issue_payload,
):
    links, source, target = structure_case()
    assert client.post(f"/issues/{source['issue']['id']}/actions",
                       json=issue_payload(source)).status_code == 200
    source = detail(client, source)
    old_history = source["actions"]
    reply = client.post(path(source, "merge"), json=structure_payload(source, target))
    assert reply.status_code == 200, reply.text
    assert reply.json()["copied_count"] == 3 and reply.json()["deduplicated_count"] == 0
    source_now, target_now = detail(client, source), detail(client, target)
    assert source_now["issue"]["merged_into_id"] == target["issue"]["id"]
    assert source_now["issue"]["status"] == "dismissed" and not source_now["can_restructure"]
    assert source_now["active_link_count"] == 0 and source_now["allowed_actions"] == []
    assert source_now["actions"][1:] == old_history
    merged = client.get("/review-issues", params={"status": "merged"}).json()
    assert merged["total"] == 1 and merged["items"][0]["issue"]["id"] == source["issue"]["id"]
    assert client.get("/review-issues", params={"status": "dismissed"}).json()["total"] == 0
    assert target_now["issue"]["status"] == "proposed" and target_now["active_link_count"] == 3
    assert target_now["valid_accepted_count"] == 1
    audit = source_now["actions"][0]["payload_json"]
    assert len(audit["transfers"]) == 3
    assert target_now["actions"][0]["payload_json"]["operation"] == "merge_in"
    by_comment = {i["review"]["comment"]["id"]: i["review"] for i in evidence(client, target)}
    for original in links:
        old = client.get(f"/comment-issues/{original['link']['id']}").json()
        new = by_comment[original["comment"]["id"]]
        assert new["comment"] == original["comment"] == old["comment"]
        for key in ("status", "decided_by", "decided_at", "evidence_text", "evidence_start",
                    "evidence_end", "analysis_run_id"):
            assert new["link"][key] == original["link"][key] == old["link"][key]
        assert old["link"]["superseded_at"] and not old["can_decide"] and not old["can_revise"]
        assert old["actions"][1:] == original["actions"]
        assert old["actions"][0]["payload_json"]["target_link_id"] == new["link"]["id"]
    pending = client.get("/review-queue").json()
    assert pending["total"] == 1 and pending["items"][0]["issue"]["id"] == target["issue"]["id"]


def test_split_moves_selected_members_and_resets_both_groups(
    client, structure_case, structure_payload, issue_payload,
):
    links, source, _ = structure_case()
    assert client.post(f"/issues/{source['issue']['id']}/actions",
                       json=issue_payload(source)).status_code == 200
    source = detail(client, source)
    reply = client.post(path(source, "split"), json=structure_payload(
        source, ids=[links[0]["link"]["id"], links[2]["link"]["id"]],
    ))
    assert reply.status_code == 200, reply.text
    target = client.get(f"/review-issues/{reply.json()['target_issue_id']}").json()
    assert target["issue"]["split_from_id"] == source["issue"]["id"]
    assert target["issue"]["created_by"] == "human" and target["issue"]["status"] == "proposed"
    assert sorted(i["review"]["link"]["status"] for i in evidence(client, target)) == [
        "accepted", "rejected",
    ]
    current = detail(client, source)
    assert current["issue"]["status"] == "proposed" and current["active_link_count"] == 1
    assert current["issue"]["suggested_count"] == 1 and current["issue"]["accepted_count"] == 0
    assert len(evidence(client, source)) == 3  # Archived records remain accessible.
    assert current["actions"][0]["payload_json"]["operation"] == "split_out"


@pytest.mark.parametrize("difference", [None, "status", "evidence", "archived", "anchor"])
def test_duplicate_comment_preview_and_merge_never_overwrite_conflicting_evidence(
    client, session_factory, structure_case, structure_payload, difference,
):
    links, source, target = structure_case()
    original = links[0]["link"]
    with session_factory() as db:
        duplicate = CommentIssue(
            issue_id=target["issue"]["id"], comment_id=original["comment_id"], origin="ai",
            status="accepted", evidence_text=original["evidence_text"],
            evidence_start=original["evidence_start"], evidence_end=original["evidence_end"],
            evidence_verified=True, analysis_run_id=original["analysis_run_id"],
            decided_by="previous-reviewer", decided_at=utcnow(),
        )
        if difference == "status":
            duplicate.status = "rejected"
        elif difference == "evidence":
            duplicate.evidence_text = "不同引文"
        elif difference == "archived":
            duplicate.superseded_at = utcnow()
        elif difference == "anchor":
            duplicate.origin, duplicate.evidence_body_hash = "human", "0" * 64
        db.add(duplicate)
        db.commit()
        duplicate_id = duplicate.id
    old = client.get(f"/comment-issues/{duplicate_id}").json()
    preview = client.get(f"/review-issues/{source['issue']['id']}/merge-targets").json()["items"][0]
    compatible = difference in (None, "archived")
    assert preview["selectable"] == compatible
    assert len(preview["conflicts"]) == (0 if compatible else 1)
    assert preview["deduplicated_count"] == (1 if compatible else 0)
    target = detail(client, target)
    reply = client.post(path(source, "merge"), json=structure_payload(source, target))
    if not compatible:
        assert reply.status_code == 409
        assert reply.json()["detail"]["code"] == "duplicate_link_conflict"
        assert detail(client, source) == source
        assert client.get(f"/comment-issues/{duplicate_id}").json() == old
    else:
        assert reply.status_code == 200 and reply.json()["deduplicated_count"] == 1
        new = client.get(f"/comment-issues/{duplicate_id}").json()
        assert new["link"]["superseded_at"] is None
        assert reply.json()["reactivated_count"] == (1 if difference == "archived" else 0)
        for key in ("id", "status", "evidence_text", "decided_by", "decided_at"):
            assert new["link"][key] == old["link"][key]
        assert len(evidence(client, target)) == 3


@pytest.mark.parametrize("mode", ["merge", "split"])
@pytest.mark.parametrize("invalid", ["body", "failed_run"])
def test_structuring_stale_evidence_does_not_make_it_valid(
    client, session_factory, structure_case, structure_payload, mode, invalid,
):
    links, source, target = structure_case()
    with session_factory() as db:
        if invalid == "body":
            db.get(Comment, links[0]["comment"]["id"]).body = "全新的正文"
        else:
            db.get(AnalysisRun, links[0]["link"]["analysis_run_id"]).status = "failed"
        db.commit()
    old_payload = structure_payload(source, target) if mode == "merge" else structure_payload(
        source, ids=[links[0]["link"]["id"]],
    )
    assert client.post(path(source, mode), json=old_payload).status_code == 409
    source = detail(client, source)
    payload = structure_payload(source, target) if mode == "merge" else structure_payload(
        source, ids=[links[0]["link"]["id"]],
    )
    reply = client.post(path(source, mode), json=payload)
    assert reply.status_code == 200
    target = client.get(f"/review-issues/{reply.json()['target_issue_id']}").json()
    assert target["valid_accepted_count"] == 0 and target["invalid_accepted_count"] == 1
    assert "confirm" not in target["allowed_actions"]
    moved = next(e for e in evidence(client, target) if e["review"]["link"]["status"] == "accepted")
    expected = "source_changed" if invalid == "body" else "analysis_changed"
    assert moved["blocked_reason"] == expected
    assert moved["review"]["link"]["evidence_text"] == links[0]["link"]["evidence_text"]


@pytest.mark.parametrize("mode", ["merge", "split"])
def test_receipt_replay_and_invalid_payloads(client, structure_case, structure_payload, mode):
    links, source, target = structure_case()
    payload = structure_payload(source, target) if mode == "merge" else structure_payload(
        source, ids=[links[0]["link"]["id"]],
    )
    for changes in ({"operator": "forged"}, {"note": " \n "}, {"note": "字" * 501},
                    {"request_id": "-" * 36}, {"expected_token": "bad"}):
        assert client.post(path(source, mode), json={**payload, **changes}).status_code == 422
    response = client.post(path(source, mode), json=payload)
    assert response.status_code == 200
    assert client.post(path(source, mode), json=payload).json() == response.json()
    assert client.post(path(source, mode), json={**payload, "note": "改变请求"}).status_code == 409
    assert client.post(path(source, mode), json={**payload, "request_id": str(uuid.uuid4())}
                       ).status_code == 409
    for item in (source, target):
        assert len(detail(client, item)["actions"]) <= 1


@pytest.mark.parametrize("bad", [[], [True], ["1"], [0], [-1], [1, 1], list(range(1, 102))])
def test_split_ids_validation(client, structure_case, structure_payload, bad):
    _, source, _ = structure_case()
    assert client.post(path(source, "split"), json=structure_payload(source, ids=bad)
                       ).status_code == 422


def test_split_requires_proper_subset_and_new_distinct_title(
    client, structure_case, structure_payload,
):
    links, source, _ = structure_case()
    for ids in ([r["link"]["id"] for r in links], [999999]):
        response = client.post(path(source, "split"), json=structure_payload(source, ids=ids))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "split_requires_subset"
    for new_issue, status in [
        ({"title": " ", "category_id": "other"}, 422),
        ({"title": "测试", "category_id": "unsupported"}, 422),
        ({"title": source["issue"]["title"], "category_id": source["issue"]["category_id"]}, 409),
    ]:
        response = client.post(path(source, "split"), json=structure_payload(
            source, ids=[links[0]["link"]["id"]], new_issue=new_issue,
        ))
        assert response.status_code == status


@pytest.mark.parametrize("side,state", [("source", "resolved"), ("target", "dismissed"),
                                       ("source", "merged"), ("target", "merged")])
def test_closed_or_merged_groups_are_protected(
    client, session_factory, structure_case, structure_payload, side, state,
):
    _, source, target = structure_case()
    changed = source if side == "source" else target
    with session_factory() as db:
        group = db.get(Issue, changed["issue"]["id"])
        if state == "merged":
            group.merged_into_id = (target if side == "source" else source)["issue"]["id"]
        else:
            group.status = state
        db.commit()
    source, target = detail(client, source), detail(client, target)
    reply = client.post(path(source, "merge"), json=structure_payload(source, target))
    assert reply.status_code == 409 and reply.json()["detail"]["code"] == "issue_not_active"


def test_same_group_scope_missing_target_and_stale_target(
    client, session_factory, structure_case, structure_payload, issue_payload,
):
    _, source, target = structure_case()
    assert client.post(path(source, "merge"), json=structure_payload(source, source)
                       ).json()["detail"]["code"] == "same_issue"
    assert client.post(path(source, "merge"), json=structure_payload(
        source, target, target_issue_id=str(uuid.uuid4()),
    )).status_code == 404
    with session_factory() as db:
        group = db.get(Issue, target["issue"]["id"])
        group.shop_id = "other-shop"
        db.commit()
    assert client.post(path(source, "merge"), json=structure_payload(source, target)
                       ).json()["detail"]["code"] == "scope_mismatch"
    with session_factory() as db:
        db.get(Issue, target["issue"]["id"]).shop_id = source["issue"]["shop_id"]
        db.commit()
    assert client.post(f"/issues/{target['issue']['id']}/actions",
                       json=issue_payload(target, "dismiss")).status_code == 200
    assert client.post(path(source, "merge"), json=structure_payload(source, target)
                       ).json()["detail"]["code"] == "target_changed"


@pytest.mark.parametrize("mode", ["merge", "split"])
def test_audit_failure_rolls_back_every_membership_and_group(
    client, session_factory, structure_case, structure_payload, mode,
):
    links, source, target = structure_case()
    with session_factory() as db:
        counts = [db.query(model).count() for model in (Issue, CommentIssue, IssueAction)]

    def fail_group_audit(mapper, connection, item):
        if item.comment_issue_id is None:
            raise RuntimeError("audit unavailable")

    event.listen(IssueAction, "before_insert", fail_group_audit)
    try:
        payload = structure_payload(source, target) if mode == "merge" else structure_payload(
            source, ids=[links[0]["link"]["id"]],
        )
        with pytest.raises(RuntimeError, match="audit unavailable"):
            client.post(path(source, mode), json=payload)
    finally:
        event.remove(IssueAction, "before_insert", fail_group_audit)
    assert detail(client, source) == source and detail(client, target) == target
    with session_factory() as db:
        assert counts == [db.query(model).count() for model in (Issue, CommentIssue, IssueAction)]
    for item in links:
        assert client.get(f"/comment-issues/{item['link']['id']}").json() == item


@pytest.mark.parametrize("mode", ["merge", "split"])
def test_worker_rerun_preserves_grouping_and_pending_review(
    client, session_factory, structure_case, structure_payload, worker_setup, mode, review_payload,
):
    links, source, target = structure_case()
    pending = links[1]
    payload = structure_payload(source, target) if mode == "merge" else structure_payload(
        source, ids=[pending["link"]["id"]],
    )
    reply = client.post(path(source, mode), json=payload)
    assert reply.status_code == 200
    destination = client.get(f"/review-issues/{reply.json()['target_issue_id']}").json()
    moved = next(i["review"] for i in evidence(client, destination)
                 if i["review"]["comment"]["id"] == pending["comment"]["id"])
    before = client.get(f"/comment-issues/{moved['link']['id']}").json()
    with session_factory() as db:
        db.add(Job(comment_id=pending["comment"]["id"]))
        db.commit()
        claim = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(claim) == "completed"
    old = client.get(f"/comment-issues/{pending['link']['id']}").json()
    current = client.get(f"/comment-issues/{moved['link']['id']}").json()
    assert old["link"]["superseded_at"] and old["link"]["status"] == "suggested"
    assert current["link"] == before["link"] and current["actions"] == before["actions"]
    queue_ids = [i["link"]["id"] for i in client.get("/review-queue").json()["items"]]
    assert moved["link"]["id"] in queue_ids and pending["link"]["id"] not in queue_ids
    assert current["can_decide"]
    assert client.post(f"/comment-issues/{moved['link']['id']}/decisions",
                       json=review_payload(current)).status_code == 200


def test_merge_target_search_is_paged_and_does_not_include_other_products(
    client, structure_case, reassign_target,
):
    links, source, target = structure_case()
    reassign_target(links[0], title="第二个匹配目标")
    reassign_target(links[0], title="其他商品", product_id="other-product")
    url = f"/review-issues/{source['issue']['id']}/merge-targets"
    data = client.get(url, params={"limit": 1}).json()
    assert data["total"] == 2 and len(data["items"]) == 1
    second = client.get(url, params={"limit": 1, "offset": 1}).json()
    assert data["items"][0]["target"]["issue"]["id"] != second["items"][0]["target"]["issue"]["id"]
    assert client.get(url, params={"q": "第二个"}).json()["total"] == 1
    assert client.get(url, params={"q": "%"}).json()["total"] == 0


def test_split_can_be_merged_back_without_losing_decision_or_original_link_id(
    client, structure_case, structure_payload,
):
    links, source, _ = structure_case()
    first = client.post(path(source, "split"), json=structure_payload(
        source, ids=[links[0]["link"]["id"]],
    ))
    child = client.get(f"/review-issues/{first.json()['target_issue_id']}").json()
    source = detail(client, source)
    response = client.post(path(child, "merge"), json=structure_payload(child, source))
    assert response.status_code == 200, response.text
    assert response.json()["reactivated_count"] == 1
    restored = client.get(f"/comment-issues/{links[0]['link']['id']}").json()
    assert restored["link"]["superseded_at"] is None and restored["link"]["status"] == "accepted"
    assert restored["actions"][-1] == links[0]["actions"][-1]
    assert detail(client, source)["active_link_count"] == 3
