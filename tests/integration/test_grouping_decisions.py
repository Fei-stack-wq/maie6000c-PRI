import httpx
import pytest
from sqlalchemy import select

from services.common.classification import incompatible, normalized_category
from services.common.models import Comment, CommentIssue, Issue


@pytest.mark.parametrize(
    "text,expected",
    [
        ("too big", "mismatch"),
        ("Size is too large", "mismatch"),
        ("太窄了", "mismatch"),
        ("偏小", "mismatch"),
        ("too expensive", "other"),
        ("太贵了", "other"),
        ("鞋底开裂", "quality"),
    ],
)
def test_stable_five_categories(text, expected):
    assert normalized_category("quality", text, text) == expected


def test_different_specific_problems_do_not_merge():
    assert incompatible("too expensive", "too big")
    assert incompatible("too big", "too small")
    assert not incompatible("too big", "尺码偏大")


@pytest.mark.parametrize(
    "confidence,source,expected",
    [
        (0.98, "llm", "accepted"),
        (0.7, "llm", "suggested"),
        (None, "llm", "suggested"),
        (0.99, "heuristic", "suggested"),
    ],
)
def test_clear_and_uncertain_links_keep_distinct_decision_sources(
    new_job,
    session_factory,
    worker_setup,
    monkeypatch,
    ai_response,
    confidence,
    source,
    expected,
):
    _, comment_id, _ = new_job(body="The zipper gets stuck.")
    _, reply, _ = ai_response

    def model(url, json, timeout=None):
        response = reply(url, json, timeout)
        if url.endswith("extract-issues"):
            response.payload["source"] = source
            response.payload["issues"][0]["confidence"] = confidence
        return response

    monkeypatch.setattr(httpx, "post", model)
    assert worker_setup.run_once() == "completed"
    with session_factory() as db:
        link = db.scalar(select(CommentIssue).where(CommentIssue.comment_id == comment_id))
        assert link.status == expected
        assert link.auto_confirmed == (expected == "accepted")
        assert link.decided_by is None and link.decided_at is None
        assert db.get(Issue, link.issue_id).status == "proposed"


def test_human_can_correct_automatic_grouping_and_worker_preserves_it(
    client,
    new_job,
    session_factory,
    worker_setup,
    monkeypatch,
    ai_response,
    review_payload,
):
    _, comment_id, _ = new_job(body="The zipper gets stuck.")
    _, reply, _ = ai_response

    def model(url, json, timeout=None):
        response = reply(url, json, timeout)
        if url.endswith("extract-issues"):
            response.payload["source"] = "llm"
            response.payload["issues"][0]["confidence"] = 0.98
        return response

    monkeypatch.setattr(httpx, "post", model)
    assert worker_setup.run_once() == "completed"
    with session_factory() as db:
        link_id = db.scalar(select(CommentIssue.id).where(CommentIssue.comment_id == comment_id))
    item = client.get(f"/comment-issues/{link_id}").json()
    assert item["link"]["auto_confirmed"] and item["can_revise"]
    request = {
        **review_payload(item, "reject", "The automatic grouping is incorrect"),
        "mode": "revise",
    }
    assert client.post(f"/comment-issues/{link_id}/decisions", json=request).status_code == 200
    current = client.get(f"/comment-issues/{link_id}").json()
    assert current["link"]["status"] == "rejected" and not current["link"]["auto_confirmed"]
    assert current["actions"][0]["payload_json"]["before"]["auto_confirmed"]
    # Re-run the same batch occurrence; the human decision must remain.
    from services.common.models import Job

    with session_factory() as db:
        db.add(Job(comment_id=comment_id, batch_id=db.get(Comment, comment_id).batch_id))
        db.commit()
    assert worker_setup.run_once() == "completed"
    assert client.get(f"/comment-issues/{link_id}").json()["link"]["status"] == "rejected"

def test_concrete_failure_corrects_an_inconsistent_model_category():
    assert normalized_category('usability', 'Zipper gets stuck halfway',
                               'The zipper gets stuck halfway every time.') == 'quality'

def test_auto_assigned_entry_can_be_moved_to_another_category(
    client, new_job, session_factory, worker_setup, monkeypatch, ai_response,
    reassign_target, reassign_payload,
):
    _, comment_id, _ = new_job(body='The zipper gets stuck.')
    _, reply, _ = ai_response

    def model(url, json, timeout=None):
        response = reply(url, json, timeout)
        if url.endswith('extract-issues'):
            response.payload['source'] = 'llm'
            response.payload['issues'][0]['confidence'] = 0.98
        return response

    monkeypatch.setattr(httpx, 'post', model)
    assert worker_setup.run_once() == 'completed'
    with session_factory() as db:
        link_id = db.scalar(select(CommentIssue.id).where(CommentIssue.comment_id == comment_id))
    original = client.get(f'/comment-issues/{link_id}').json()
    assert original['link']['auto_confirmed']
    target = reassign_target(original, category_id='mismatch', title='Human-selected group')
    response = client.post(f'/comment-issues/{link_id}/reassign',
                           json=reassign_payload(original, target))
    assert response.status_code == 200, response.text
    with session_factory() as db:
        old = db.get(CommentIssue, link_id)
        new = db.scalar(select(CommentIssue).where(CommentIssue.issue_id == target))
        assert old.status == 'rejected' and not old.auto_confirmed
        assert new.status == 'accepted' and new.origin == 'human' and not new.auto_confirmed


def test_legacy_repair_normalizes_categories_once_and_preserves_human_decisions(
    new_job, session_factory, worker_setup, ai_response,
):
    from scripts.regroup_legacy import repair
    from services.common.models import IngestionBatch

    _, comment_id, batch_id = new_job(body="The shoes are too big.")
    assert worker_setup.run_once() == "completed"
    with session_factory() as db:
        link = db.scalar(select(CommentIssue).where(CommentIssue.comment_id == comment_id))
        group = db.get(Issue, link.issue_id)
        group.category_id = "quality"
        db.get(IngestionBatch, batch_id).grouping_policy_version = 0
        db.commit()
        repair(db)
        assert group.category_id == "mismatch"
        assert db.get(IngestionBatch, batch_id).grouping_policy_version == 2
        group.title = "A later human title"
        db.commit()
        assert repair(db) == 0
        assert group.title == "A later human title"


def test_legacy_repair_does_not_change_a_human_reviewed_group(
    new_job, session_factory, worker_setup, ai_response,
):
    from scripts.regroup_legacy import repair
    from services.common.models import IngestionBatch

    _, comment_id, batch_id = new_job(body="The shoes are too big.")
    assert worker_setup.run_once() == "completed"
    with session_factory() as db:
        link = db.scalar(select(CommentIssue).where(CommentIssue.comment_id == comment_id))
        group = db.get(Issue, link.issue_id)
        group.category_id = "quality"
        group.title = "Human reviewed title"
        link.status = "accepted"
        link.decided_by = "reviewer"
        db.get(IngestionBatch, batch_id).grouping_policy_version = 0
        db.commit()
        assert repair(db) == 0
        assert group.category_id == "quality"
        assert group.title == "Human reviewed title"
        assert link.status == "accepted" and link.decided_by == "reviewer"
