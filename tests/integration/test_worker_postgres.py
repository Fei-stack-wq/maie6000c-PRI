"""Real PostgreSQL tests; only an explicitly named *_test database is accepted."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from services.common.db import Base
from services.common.models import AnalysisRun, CommentIssue, Issue, Job, utcnow
from services.worker.app import jobs


@pytest.fixture()
def engine():
    url = os.getenv("WORKER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WORKER_TEST_DATABASE_URL is required for PostgreSQL locking tests")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not parsed.database.endswith("_test"):
        pytest.fail("Use an isolated PostgreSQL database whose name ends with _test")
    schema = "r2_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    test_engine = create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    Base.metadata.create_all(test_engine)
    try:
        yield test_engine
    finally:
        test_engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def claim(factory, settings):
    with factory() as db:
        return jobs.claim_next_pending_job(db, settings)


def test_two_workers_cannot_claim_the_same_job(session_factory, new_job, worker_settings):
    job_id, _, _ = new_job()
    barrier = threading.Barrier(2)

    def concurrent_claim():
        barrier.wait(timeout=5)
        return claim(session_factory, worker_settings)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: concurrent_claim(), range(2)))
    assert [item.id for item in claims if item] == [job_id]


def test_parallel_jobs_do_not_create_duplicate_groups(
    session_factory, new_job, worker_settings, worker_setup, ai_response,
):
    for _ in range(8):
        new_job(body="拉链卡住了。物流太慢。")
    claims = [claim(session_factory, worker_settings) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(worker_setup.process_job, item) for item in claims]
        assert [future.result(timeout=15) for future in futures] == ["completed"] * 8
    with session_factory() as db:
        assert db.query(Job).filter_by(status="completed").count() == 8
        assert db.query(Issue).count() == 2
        assert db.query(CommentIssue).count() == 16


def test_recovery_skips_a_row_locked_by_another_transaction(
    session_factory, new_job, worker_settings,
):
    from datetime import timedelta

    job_id, _, _ = new_job()
    claim(session_factory, worker_settings)
    with session_factory() as db:
        db.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with session_factory() as owner:
        owner.execute(select(Job).where(Job.id == job_id).with_for_update()).scalar_one()
        with session_factory() as recovery:
            assert jobs.recover_stale_jobs(recovery, worker_settings) == 0
        owner.rollback()
    with session_factory() as recovery:
        assert jobs.recover_stale_jobs(recovery, worker_settings) == 1


def test_human_decision_committed_during_reanalysis_is_preserved(
    session_factory, new_job, worker_settings, worker_setup, ai_response, monkeypatch,
):
    import httpx

    _, comment_id, _ = new_job()
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        db.add(Job(comment_id=comment_id))
        db.commit()
    second = claim(session_factory, worker_settings)
    _, normal, _ = ai_response
    started = threading.Event()

    def notify_ai(*args, **kwargs):
        started.set()
        return normal(*args, **kwargs)

    monkeypatch.setattr(httpx, "post", notify_ai)
    with session_factory() as human:
        link = human.execute(select(CommentIssue).with_for_update()).scalar_one()
        link.status, link.decided_by, link.decided_at = "accepted", "human", utcnow()
        human.flush()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker_setup.process_job, second)
            assert started.wait(timeout=5)
            human.commit()
            assert future.result(timeout=10) == "completed"
    with session_factory() as db:
        link = db.query(CommentIssue).one()
        assert link.status == "accepted" and link.decided_by == "human"
        assert link.superseded_at is None
        assert db.query(AnalysisRun).count() == 2


def test_postgres_rejects_late_claim_after_recovery(
    session_factory, new_job, worker_settings, worker_setup, ai_response,
):
    from datetime import timedelta

    job_id, _, _ = new_job()
    old = claim(session_factory, worker_settings)
    with session_factory() as db:
        db.get(Job, job_id).lease_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with session_factory() as db:
        jobs.recover_stale_jobs(db, worker_settings)
    current = claim(session_factory, worker_settings)
    assert worker_setup.process_job(current) == "completed"
    assert worker_setup.process_job(old) == "stale"
    with session_factory() as db:
        assert db.query(AnalysisRun).count() == 1


def test_api_body_update_during_ai_call_is_reanalyzed(
    session_factory, new_job, worker_settings, worker_setup, ai_response, monkeypatch, client,
):
    import httpx
    from services.common.models import Comment

    _, comment_id, _ = new_job()
    old = claim(session_factory, worker_settings)
    with session_factory() as db:
        source_id = db.get(Comment, comment_id).source_review_id
    _, normal, _ = ai_response

    def update_during_call(url, json, timeout=None):
        response = client.post("/review-batches", json={
            "platform": "demo", "comments": [{
                "platform": "demo", "shop_id": "shop-1", "product_id": "bag-1",
                "source_review_id": source_id, "body": "总体不错，很喜欢。",
            }],
        })
        assert response.status_code == 202
        assert response.json()["job_count"] == 0  # The old claim is still active.
        return normal(url, json, timeout)

    monkeypatch.setattr(httpx, "post", update_during_call)
    assert worker_setup.process_job(old) == "input_changed"
    monkeypatch.setattr(httpx, "post", normal)
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        assert db.get(Comment, comment_id).has_issue == "no"
        assert db.query(Job).count() == 1
        assert db.query(AnalysisRun).count() == 2
