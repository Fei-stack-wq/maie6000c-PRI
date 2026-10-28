from datetime import timedelta
import threading

import httpx
import pytest

from services.common.models import (
    AnalysisRun, Comment, CommentIssue, CommentRevision, Issue, Job, utcnow,
)
from services.worker.app import jobs


def claim(factory, settings):
    with factory() as db:
        return jobs.claim_next_pending_job(db, settings)


def due(factory, job_id):
    with factory() as db:
        db.get(Job, job_id).next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()


def queue_again(factory, comment_id):
    with factory() as db:
        comment = db.get(Comment, comment_id)
        comment.analysis_status = "queued"
        job = Job(comment_id=comment_id, batch_id=comment.batch_id)
        db.add(job)
        db.commit()
        return job.id


def test_claim_updates_both_states_and_cannot_claim_twice(
    session_factory, new_job, worker_settings,
):
    job_id, comment_id, _ = new_job()
    first = claim(session_factory, worker_settings)
    assert first.id == job_id and first.attempts == 1
    assert claim(session_factory, worker_settings) is None
    with session_factory() as db:
        assert db.get(Job, job_id).status == "claimed"
        assert db.get(Comment, comment_id).analysis_status == "analyzing"


def test_future_retry_and_exhausted_pending_are_not_claimed(
    session_factory, new_job, worker_settings,
):
    job_id, comment_id, _ = new_job()
    with session_factory() as db:
        job = db.get(Job, job_id)
        job.next_attempt_at = utcnow() + timedelta(hours=1)
        db.commit()
    assert claim(session_factory, worker_settings) is None
    with session_factory() as db:
        job = db.get(Job, job_id)
        job.attempts = job.max_attempts
        db.commit()
    with session_factory() as db:
        assert jobs.recover_stale_jobs(db, worker_settings) == 1
    with session_factory() as db:
        assert db.get(Job, job_id).status == "failed"
        assert db.get(Comment, comment_id).analysis_status == "failed"


def test_timeout_then_success_is_recorded_without_duplicates(
    session_factory, new_job, worker_setup, worker_settings, ai_response, monkeypatch, client,
):
    job_id, comment_id, _ = new_job()
    _, normal, calls = ai_response
    first = claim(session_factory, worker_settings)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ReadTimeout("private request body")))
    assert worker_setup.process_job(first) == "retry_scheduled"
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job.status == "pending" and job.attempts == 1
        assert job.error_code == "ai_timeout" and job.next_attempt_at
        assert "private" not in job.error
        assert db.get(Comment, comment_id).analysis_status == "queued"
    assert claim(session_factory, worker_settings) is None
    due(session_factory, job_id)
    monkeypatch.setattr(httpx, "post", normal)
    second = claim(session_factory, worker_settings)
    assert second.attempts == 2
    assert worker_setup.process_job(second) == "completed"
    assert worker_setup.process_job(second) == "stale"
    with session_factory() as db:
        assert db.get(Job, job_id).status == "completed"
        assert db.query(AnalysisRun).count() == 2
        assert db.query(CommentIssue).count() == 1
        assert db.query(AnalysisRun).filter_by(status="failed").one().model_version == "unknown"
    assert len(calls) == 1
    assert client.get(f"/jobs/{job_id}").json()["attempts"] == 2


def test_continuous_failure_stops_at_job_limit(
    session_factory, new_job, worker_setup, worker_settings, monkeypatch, client,
):
    job_id, comment_id, batch_id = new_job()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ConnectError("unavailable")))
    for attempt in range(1, 4):
        current = claim(session_factory, worker_settings)
        assert current.attempts == attempt
        expected = "failed" if attempt == 3 else "retry_scheduled"
        assert worker_setup.process_job(current) == expected
        due(session_factory, job_id)
    assert claim(session_factory, worker_settings) is None
    with session_factory() as db:
        assert db.get(Comment, comment_id).analysis_status == "failed"
        assert db.query(AnalysisRun).count() == 3
        assert db.query(Issue).count() == 0
    progress = client.get(f"/review-batches/{batch_id}").json()
    assert progress["failed_rows"] == 1 and progress["status"] == "partially_failed"


@pytest.mark.parametrize("last_attempt", [False, True])
def test_expired_claim_recovery_has_limit_and_does_not_double_count(
    session_factory, new_job, worker_settings, last_attempt,
):
    job_id, comment_id, _ = new_job()
    old = claim(session_factory, worker_settings)
    with session_factory() as db:
        job = db.get(Job, job_id)
        if last_attempt:
            job.max_attempts = 1
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with session_factory() as db:
        assert jobs.recover_stale_jobs(db, worker_settings) == 1
    with session_factory() as db:
        job = db.get(Job, job_id)
        assert job.attempts == 1
        assert job.status == ("failed" if last_attempt else "pending")
        assert db.get(Comment, comment_id).analysis_status == (
            "failed" if last_attempt else "queued"
        )
        assert jobs.lock_owned_job(db, old, utcnow()) is None


@pytest.mark.parametrize("late_failure", [False, True])
def test_old_worker_cannot_overwrite_new_completion(
    session_factory, new_job, worker_settings, worker_setup, ai_response,
    monkeypatch, late_failure,
):
    job_id, comment_id, _ = new_job()
    _, normal, _ = ai_response
    old = claim(session_factory, worker_settings)

    def late_reply(url, json, timeout=None):
        with session_factory() as db:
            db.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        with session_factory() as db:
            jobs.recover_stale_jobs(db, worker_settings)
        replacement = claim(session_factory, worker_settings)
        monkeypatch.setattr(httpx, "post", normal)
        assert worker_setup.process_job(replacement) == "completed"
        if late_failure:
            raise httpx.ReadTimeout("late")
        return normal(url, json, timeout)

    monkeypatch.setattr(httpx, "post", late_reply)
    assert worker_setup.process_job(old) == "stale"
    with session_factory() as db:
        assert db.get(Job, job_id).status == "completed"
        assert db.get(Comment, comment_id).analysis_status == "analyzed"
        assert db.query(AnalysisRun).count() == 1
        assert db.query(CommentIssue).count() == 1


@pytest.mark.parametrize("status,origin", [
    ("accepted", "ai"), ("rejected", "ai"), ("suggested", "human"),
])
def test_reanalysis_preserves_human_decision_and_evidence(
    session_factory, new_job, worker_settings, worker_setup, ai_response, status, origin,
):
    _, comment_id, _ = new_job()
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        link = db.query(CommentIssue).one()
        original_run = link.analysis_run_id
        link.status, link.origin = status, origin
        link.decided_by = "reviewer"
        link.decided_at = utcnow()
        db.commit()
    queue_again(session_factory, comment_id)
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        link = db.query(CommentIssue).one()
        assert (link.status, link.origin) == (status, origin)
        assert link.decided_by == "reviewer"
        assert link.analysis_run_id == original_run
        assert link.superseded_at is None
        assert db.query(AnalysisRun).count() == 2


@pytest.mark.parametrize("call_fails", [False, True])
def test_input_changed_during_call_is_requeued_with_original_input_audit(
    session_factory, new_job, worker_settings, worker_setup, ai_response, monkeypatch, call_fails,
):
    _, comment_id, _ = new_job()
    _, normal, _ = ai_response
    old = claim(session_factory, worker_settings)
    new_body = "整体不错，很喜欢。"

    def changing_reply(url, json, timeout=None):
        with session_factory() as db:
            comment = db.get(Comment, comment_id)
            comment.body = new_body
            comment.content_hash = "updated"
            db.add(CommentRevision(comment_id=comment_id, version=1, body=new_body,
                                   content_hash="updated"))
            db.commit()
        if call_fails:
            raise httpx.ReadTimeout("changed input")
        return normal(url, json, timeout)

    monkeypatch.setattr(httpx, "post", changing_reply)
    assert worker_setup.process_job(old) == "input_changed"
    with session_factory() as db:
        job = db.get(Job, old.id)
        assert job.status == "pending" and job.attempts == 0
        assert db.get(Comment, comment_id).current_analysis_run_id is None
        assert db.query(CommentIssue).count() == 0
        assert db.query(AnalysisRun).one().status == "failed"
    monkeypatch.setattr(httpx, "post", normal)
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.get(Comment, comment_id).has_issue == "no"


def test_result_transaction_rolls_back_before_failure_recording(
    session_factory, new_job, worker_settings, worker_setup, ai_response, monkeypatch,
):
    job_id, _, _ = new_job()
    original = jobs.save_issue_links

    def broken_save(*args):
        original(*args)
        raise RuntimeError("failure after issue/link flush")

    monkeypatch.setattr(jobs, "save_issue_links", broken_save)
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "failed"
    with session_factory() as db:
        assert db.query(Issue).count() == 0
        assert db.query(CommentIssue).count() == 0
        assert db.query(AnalysisRun).one().status == "failed"
        assert db.get(Job, job_id).error_code == "unknown"


def test_failure_recording_outage_does_not_crash_attempt(
    session_factory, new_job, worker_settings, worker_setup, monkeypatch,
):
    new_job()
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(
        httpx.ReadTimeout("timeout")))
    monkeypatch.setattr(jobs, "handle_job_failure",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("DB down")))
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "recording_failed"


def test_loop_survives_poll_failure_and_honors_shutdown(worker_setup, monkeypatch):
    stop = threading.Event()
    calls = []

    def one_round():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary outage")
        stop.set()
        return "idle"

    monkeypatch.setattr(worker_setup, "run_once", one_round)
    worker_setup.run_worker(stop, serve_metrics=False)
    assert len(calls) == 2


def test_plain_job_id_is_rejected(worker_setup):
    with pytest.raises(TypeError):
        worker_setup.process_job(1)


def test_expired_claim_cannot_finish_even_before_recovery(
    session_factory, new_job, worker_settings, worker_setup, ai_response, monkeypatch,
):
    job_id, _, _ = new_job()
    _, normal, calls = ai_response

    def expired_reply(*args, **kwargs):
        reply = normal(*args, **kwargs)
        with session_factory() as db:
            db.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
            db.commit()
        return reply

    monkeypatch.setattr(httpx, "post", expired_reply)
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "stale"
    with session_factory() as db:
        assert db.query(AnalysisRun).count() == 0
    assert len(calls) == 1


def test_recovery_of_updated_input_gets_fresh_budget(
    session_factory, new_job, worker_settings, worker_setup, ai_response,
):
    job_id, comment_id, _ = new_job()
    old = claim(session_factory, worker_settings)
    with session_factory() as db:
        job = db.get(Job, job_id)
        job.max_attempts = 1
        job.lease_expires_at = utcnow() - timedelta(seconds=1)
        comment = db.get(Comment, comment_id)
        comment.body = "总体不错，很喜欢。"
        comment.analysis_status = "queued"  # R1 marks a changed input this way.
        db.commit()
    with session_factory() as db:
        jobs.recover_stale_jobs(db, worker_settings)
    fresh = claim(session_factory, worker_settings)
    assert fresh.attempts == 1
    assert worker_setup.process_job(old) == "stale"
    assert worker_setup.process_job(fresh) == "completed"
