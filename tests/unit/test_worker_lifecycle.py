"""R2 unit tests: claim, fencing, retry taxonomy, lease recover, human-link protect."""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from services.common.models import (
    AnalysisStatus,
    Comment,
    CommentIssue,
    ErrorCode,
    HasIssue,
    Issue,
    IssueStatus,
    Job,
    JobStatus,
    JobType,
    LinkOrigin,
    LinkStatus,
    utcnow,
)
from services.worker.app import main as worker_main
from services.worker.app.lifecycle import (
    JobConflictError,
    backoff_delta,
    claim_next_pending_job,
    fail_or_retry,
    fence_complete_job,
    recover_job,
    recover_stale_jobs,
    requeue_batch_jobs,
    retry_job,
    sanitize_error_message,
    should_auto_retry,
)


def _seed_comment_job(db, *, status: str = JobStatus.PENDING.value, attempts: int = 0) -> Job:
    comment = Comment(
        platform="demo",
        shop_id="shop-1",
        product_id="bag-1",
        source_review_id=f"src-{utcnow().timestamp()}-{attempts}-{status}",
        body="拉链拉到一半就卡住，拉不上。",
        content_hash="hash-1",
        analysis_status=AnalysisStatus.QUEUED.value,
    )
    db.add(comment)
    db.flush()
    job = Job(
        comment_id=comment.id,
        batch_id=None,
        job_type=JobType.EXTRACT_ISSUES.value,
        status=status,
        attempts=attempts,
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_sanitize_error_message_strips_urls():
    text = sanitize_error_message("boom at http://ai:8100/extract-issues detail")
    assert "http://" not in text
    assert "<redacted-url>" in text


def test_should_auto_retry_taxonomy():
    assert should_auto_retry(ErrorCode.AI_TIMEOUT.value, attempts=1, max_attempts=3)
    assert should_auto_retry(ErrorCode.AI_ERROR.value, attempts=2, max_attempts=3)
    assert should_auto_retry(ErrorCode.DB_ERROR.value, attempts=1, max_attempts=3)
    assert should_auto_retry(ErrorCode.AI_INVALID_OUTPUT.value, attempts=1, max_attempts=3)
    assert not should_auto_retry(ErrorCode.AI_INVALID_OUTPUT.value, attempts=2, max_attempts=3)
    assert not should_auto_retry(ErrorCode.UNKNOWN.value, attempts=1, max_attempts=3)
    assert not should_auto_retry(ErrorCode.COMMENT_NOT_FOUND.value, attempts=1, max_attempts=3)
    assert not should_auto_retry(ErrorCode.AI_TIMEOUT.value, attempts=3, max_attempts=3)
    assert backoff_delta(1) == timedelta(seconds=60)
    assert backoff_delta(2) == timedelta(seconds=300)
    assert backoff_delta(3) == timedelta(seconds=900)


def test_claim_respects_next_attempt_at(session_factory):
    with session_factory() as db:
        job = _seed_comment_job(db)
        job.next_attempt_at = utcnow() + timedelta(minutes=10)
        db.commit()

        assert claim_next_pending_job(db) is None

        job.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
        claimed = claim_next_pending_job(db)
        assert claimed is not None
        assert claimed.id == job.id
        assert claimed.status == JobStatus.CLAIMED.value
        assert claimed.attempts == 1
        assert claimed.lease_expires_at is not None


def test_claim_only_once_sequentially(session_factory):
    with session_factory() as db:
        job = _seed_comment_job(db)
        first = claim_next_pending_job(db)
        second = claim_next_pending_job(db)
        assert first is not None and first.id == job.id
        assert second is None


def test_fail_or_retry_requeues_then_fails(session_factory):
    with session_factory() as db:
        _seed_comment_job(db)
        claimed = claim_next_pending_job(db)
        assert claimed is not None
        seen = claimed.claimed_at

        outcome = fail_or_retry(
            db, claimed.id, seen, ErrorCode.AI_TIMEOUT.value, "timeout http://x"
        )
        assert outcome == "requeued"
        db.refresh(claimed)
        assert claimed.status == JobStatus.PENDING.value
        assert claimed.attempts == 1
        assert claimed.next_attempt_at is not None
        assert "http://" not in (claimed.error or "")
        comment = db.get(Comment, claimed.comment_id)
        assert comment.analysis_status == AnalysisStatus.QUEUED.value

        # Make due and claim again until attempts hit max.
        claimed.next_attempt_at = None
        db.commit()
        claimed = claim_next_pending_job(db)
        assert claimed.attempts == 2
        fail_or_retry(db, claimed.id, claimed.claimed_at, ErrorCode.AI_TIMEOUT.value, "t2")
        claimed.next_attempt_at = None
        db.commit()
        claimed = claim_next_pending_job(db)
        assert claimed.attempts == 3
        outcome = fail_or_retry(
            db, claimed.id, claimed.claimed_at, ErrorCode.AI_TIMEOUT.value, "t3"
        )
        assert outcome == "failed"
        db.refresh(claimed)
        assert claimed.status == JobStatus.FAILED.value
        comment = db.get(Comment, claimed.comment_id)
        assert comment.analysis_status == AnalysisStatus.FAILED.value


def test_fencing_rejects_stale_complete_and_fail(session_factory):
    with session_factory() as db:
        _seed_comment_job(db)
        claimed = claim_next_pending_job(db)
        stale_claimed_at = claimed.claimed_at

        # Simulate lease recovery + re-claim by another worker.
        claimed.status = JobStatus.PENDING.value
        claimed.claimed_at = None
        claimed.lease_expires_at = None
        claimed.attempts = 1
        db.commit()
        fresh = claim_next_pending_job(db)
        assert fresh is not None
        assert fresh.attempts == 2
        assert fresh.claimed_at != stale_claimed_at

        assert fence_complete_job(db, fresh.id, stale_claimed_at) is False
        db.rollback()
        db.refresh(fresh)
        assert fresh.status == JobStatus.CLAIMED.value

        outcome = fail_or_retry(
            db, fresh.id, stale_claimed_at, ErrorCode.AI_ERROR.value, "stale"
        )
        assert outcome == "fenced"
        db.refresh(fresh)
        assert fresh.status == JobStatus.CLAIMED.value


def test_recover_stale_jobs_respects_max_attempts(session_factory):
    with session_factory() as db:
        job = _seed_comment_job(db, status=JobStatus.CLAIMED.value, attempts=2)
        job.claimed_at = utcnow() - timedelta(minutes=20)
        job.lease_expires_at = utcnow() - timedelta(minutes=5)
        db.commit()

        assert recover_stale_jobs(db) == 1
        db.refresh(job)
        # attempts becomes 3 → terminal failed
        assert job.attempts == 3
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == ErrorCode.LEASE_EXPIRED.value

        job2 = _seed_comment_job(db, status=JobStatus.CLAIMED.value, attempts=0)
        job2.claimed_at = utcnow() - timedelta(minutes=20)
        job2.lease_expires_at = utcnow() - timedelta(minutes=5)
        db.commit()
        assert recover_stale_jobs(db) == 1
        db.refresh(job2)
        assert job2.status == JobStatus.PENDING.value
        assert job2.attempts == 1


def test_retry_and_recover_api_helpers(session_factory):
    with session_factory() as db:
        job = _seed_comment_job(db, status=JobStatus.FAILED.value, attempts=3)
        job.error_code = ErrorCode.AI_TIMEOUT.value
        db.commit()

        retry_job(db, job.id, operator="tester")
        db.commit()
        db.refresh(job)
        assert job.status == JobStatus.PENDING.value
        assert job.attempts == 0
        assert job.error_code is None

        with pytest.raises(JobConflictError):
            retry_job(db, job.id)

        claimed = claim_next_pending_job(db)
        with pytest.raises(JobConflictError):
            recover_job(db, claimed.id)  # lease not expired

        claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        recover_job(db, claimed.id, operator="tester")
        db.commit()
        db.refresh(claimed)
        # claim set attempts=1; recover increments again → 2
        assert claimed.status == JobStatus.PENDING.value
        assert claimed.attempts == 2
        assert claimed.error_code == ErrorCode.LEASE_EXPIRED.value


def test_requeue_batch_jobs(session_factory):
    with session_factory() as db:
        comment = Comment(
            platform="demo",
            shop_id="shop-1",
            product_id="bag-1",
            source_review_id="batch-rq-1",
            body="肩带断了",
            content_hash="h2",
            analysis_status=AnalysisStatus.FAILED.value,
        )
        db.add(comment)
        db.flush()
        batch_id = "11111111-1111-1111-1111-111111111111"
        job = Job(
            comment_id=comment.id,
            batch_id=batch_id,
            job_type=JobType.EXTRACT_ISSUES.value,
            status=JobStatus.FAILED.value,
            attempts=3,
        )
        db.add(job)
        db.commit()

        count = requeue_batch_jobs(db, batch_id, status="failed", operator="script")
        db.commit()
        assert count == 1
        db.refresh(job)
        assert job.status == JobStatus.PENDING.value
        assert job.attempts == 0


def test_process_job_does_not_overwrite_accepted_links(session_factory, monkeypatch):
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)

    with session_factory() as db:
        job = _seed_comment_job(db)
        comment = db.get(Comment, job.comment_id)
        issue = Issue(
            platform=comment.platform,
            shop_id=comment.shop_id,
            product_id=comment.product_id,
            category_id="quality",
            title="拉链问题",
            description="拉链卡住",
            status=IssueStatus.CONFIRMED.value,
            created_by="human",
        )
        db.add(issue)
        db.flush()
        link = CommentIssue(
            comment_id=comment.id,
            issue_id=issue.id,
            status=LinkStatus.ACCEPTED.value,
            origin=LinkOrigin.HUMAN.value,
            evidence_text="拉链",
            evidence_verified=True,
        )
        db.add(link)
        db.commit()
        human_link_id = link.id

        claimed = claim_next_pending_job(db)
        assert claimed is not None

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "comment_id": comment.id,
                "has_issue": "yes",
                "issues": [
                    {
                        "category_id": "quality",
                        "description": "拉链卡住/拉不上",
                        "evidence_text": "拉链拉到一半就卡住",
                    }
                ],
                "model_version": "test",
                "prompt_version": "v1",
                "category_version": "v1",
                "schema_version": "1",
            }

    monkeypatch.setattr(httpx, "post", lambda *a, **k: _Resp())
    worker_main.process_job(claimed.id)

    with session_factory() as db:
        link = db.get(CommentIssue, human_link_id)
        assert link is not None
        assert link.status == LinkStatus.ACCEPTED.value
        assert link.origin == LinkOrigin.HUMAN.value
        job = db.get(Job, claimed.id)
        assert job.status == JobStatus.COMPLETED.value
        comment = db.get(Comment, job.comment_id)
        assert comment.analysis_status == AnalysisStatus.ANALYZED.value
        assert comment.has_issue in {HasIssue.YES.value, HasIssue.UNKNOWN.value}


def test_retry_recover_http_endpoints(client, session_factory):
    with session_factory() as db:
        job = _seed_comment_job(db, status=JobStatus.FAILED.value, attempts=2)
        job_id = job.id

    ok = client.post(f"/jobs/{job_id}/retry")
    assert ok.status_code == 200
    body = ok.json()
    assert body["status"] == "pending"
    assert body["attempts"] == 0

    conflict = client.post(f"/jobs/{job_id}/retry")
    assert conflict.status_code == 409

    missing = client.post("/jobs/999999/retry")
    assert missing.status_code == 404

    with session_factory() as db:
        job = db.get(Job, job_id)
        job.status = JobStatus.CLAIMED.value
        job.claimed_at = utcnow() - timedelta(minutes=30)
        job.lease_expires_at = utcnow() - timedelta(minutes=1)
        job.attempts = 1
        db.commit()

    recovered = client.post(f"/jobs/{job_id}/recover")
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "pending"
    assert recovered.json()["error_code"] == ErrorCode.LEASE_EXPIRED.value
