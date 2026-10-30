import httpx
import pytest

from services.common.models import AnalysisRun, Comment, CommentIssue, Issue, Job
from services.worker.app import jobs


def next_claim(factory, settings):
    with factory() as db:
        return jobs.claim_next_pending_job(db, settings)


@pytest.mark.parametrize("body,expected", [("整体不错，很喜欢。", "no"), ("怪", "unknown")])
def test_valid_no_and_unknown_are_successes(
    session_factory, new_job, worker_setup, worker_settings, ai_response, body, expected,
):
    job_id, comment_id, _ = new_job(body=body)
    assert worker_setup.process_job(next_claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.get(Job, job_id).status == "completed"
        assert db.get(Comment, comment_id).has_issue == expected
        assert db.query(CommentIssue).count() == 0


@pytest.mark.parametrize("malformation", ["wrong_id", "category", "version", "shape", "not_json"])
def test_invalid_ai_output_is_bounded_and_never_creates_issues(
    session_factory, new_job, worker_setup, worker_settings, ai_response, monkeypatch, malformation,
):
    job_id, _, _ = new_job()
    Reply, normal, _ = ai_response

    def bad_reply(url, json, timeout=None):
        payload = normal(url, json, timeout).json()
        if malformation == "wrong_id":
            payload["comment_id"] = "unrelated"
        elif malformation == "category":
            payload["issues"][0]["category_id"] = "made-up"
        elif malformation == "version":
            payload["schema_version"] = "999"
        elif malformation == "shape":
            payload["has_issue"], payload["issues"] = "yes", []
        else:
            class InvalidJSON:
                def raise_for_status(self):
                    pass

                def json(self):
                    raise ValueError("SECRET raw response")
            return InvalidJSON()
        return Reply(payload)

    monkeypatch.setattr(httpx, "post", bad_reply)
    for attempt in (1, 2):
        claim = next_claim(session_factory, worker_settings)
        assert worker_setup.process_job(claim) == (
            "retry_scheduled" if attempt == 1 else "failed"
        )
        with session_factory() as db:
            job = db.get(Job, job_id)
            job.next_attempt_at = None
            db.commit()
    with session_factory() as db:
        assert db.get(Job, job_id).error_code == "ai_invalid_output"
        assert db.query(Issue).count() == 0
        assert db.query(AnalysisRun).count() == 2


def test_missing_evidence_is_discarded_and_unknown_is_saved(
    session_factory, new_job, worker_setup, worker_settings, ai_response, monkeypatch,
):
    _, comment_id, _ = new_job()
    Reply, normal, _ = ai_response

    def wrong_evidence(url, json, timeout=None):
        payload = normal(url, json, timeout).json()
        payload["issues"][0]["evidence_text"] = "并不存在的原文"
        return Reply(payload)

    monkeypatch.setattr(httpx, "post", wrong_evidence)
    assert worker_setup.process_job(next_claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.get(Comment, comment_id).has_issue == "unknown"
        assert db.query(CommentIssue).count() == 0
        assert db.query(AnalysisRun).one().output_json["_worker"]["invalid_evidence_count"] == 1


def test_superseded_suggestions_are_not_counted(
    session_factory, new_job, worker_setup, worker_settings, ai_response, monkeypatch, client,
):
    _, comment_id, _ = new_job()
    assert worker_setup.process_job(next_claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        issue_id = db.query(Issue).one().id
        comment = db.get(Comment, comment_id)
        comment.analysis_status = "queued"
        db.add(Job(comment_id=comment_id, batch_id=comment.batch_id))
        db.commit()
    Reply, _, _ = ai_response

    def no_issue(url, json, timeout=None):
        return Reply({
            "comment_id": json["comment_id"], "has_issue": "no", "issues": [],
            "model_version": "test-model", "prompt_version": "test-prompt",
        })

    monkeypatch.setattr(httpx, "post", no_issue)
    assert worker_setup.process_job(next_claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.query(CommentIssue).one().superseded_at is not None
    assert client.get(f"/issues/{issue_id}").json()["suggested_count"] == 0
    assert client.get("/stats/summary").json()["ai_suggested_count"] == 0


def test_same_product_id_in_different_shops_does_not_share_group(
    session_factory, new_job, worker_setup, worker_settings, ai_response,
):
    new_job(shop="one")
    new_job(shop="two")
    for _ in range(2):
        assert worker_setup.process_job(next_claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.query(Issue).count() == 2
