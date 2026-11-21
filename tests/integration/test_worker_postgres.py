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
def session_auth(client, session_factory, monkeypatch):
    from services.api.app.auth.manage import manage_user
    from services.common.config import get_settings

    monkeypatch.setenv("REVIEW_AUTH_MODE", "session")
    monkeypatch.setenv("REVIEW_COOKIE_SECURE", "false")
    get_settings.cache_clear()
    with session_factory() as db:
        user = manage_user(db, "create", "pg-reviewer", role="reviewer",
                           password="Local-PG-test-password")
        user_id = user.id
    headers = {"X-Review-Request": "1", "Origin": "http://testserver"}
    result = client.post("/auth/login", json={"username": "pg-reviewer",
                         "password": "Local-PG-test-password"}, headers=headers)
    assert result.status_code == 200, result.text
    try:
        yield user_id, {**headers, "X-CSRF-Token": result.json()["csrf_token"]}
    finally:
        get_settings.cache_clear()


def test_auth_concurrent_failed_logins_share_throttle(client, session_auth):
    barrier = threading.Barrier(7)

    def attempt(_):
        barrier.wait(timeout=5)
        return client.post("/auth/login", json={"username": "pg-reviewer", "password": "wrong"},
                           headers={"X-Review-Request": "1"}).status_code

    with ThreadPoolExecutor(max_workers=7) as pool:
        statuses = list(pool.map(attempt, range(7)))
    assert sorted(statuses) == [401] * 5 + [429] * 2


def test_concurrent_csv_retries_create_exactly_one_batch_and_job(client, session_factory):
    from services.common.models import IngestionBatch

    barrier = threading.Barrier(3)
    payload = {'platform': 'demo', 'filename': 'retry.csv', 'idempotency_key': 'same-upload',
               'csv_text': 'shop_id,product_id,body\ns,p,broken zipper'}

    def attempt(_):
        barrier.wait(timeout=5)
        return client.post('/review-batches', json=payload)

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(attempt, range(3)))
    assert all(r.status_code == 202 for r in results)
    assert len({r.json()['batch_id'] for r in results}) == 1
    with session_factory() as db:
        assert db.query(IngestionBatch).count() == db.query(Job).count() == 1


def test_auth_revocation_committed_before_waiting_write_is_enforced(
    client, session_factory, session_auth,
):
    from sqlalchemy import delete, event
    from services.common.models import ReviewSession, ReviewUser

    user_id, headers = session_auth
    waiting = threading.Event()

    def before_execute(conn, cursor, statement, params, context, executemany):
        if "review_users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    with session_factory() as owner:
        user = owner.scalar(select(ReviewUser).where(ReviewUser.id == user_id).with_for_update())
        user.enabled = False
        owner.execute(delete(ReviewSession).where(ReviewSession.user_id == user_id))
        owner.flush()
        event.listen(owner.bind, "before_cursor_execute", before_execute)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(client.post, "/comment-issues/1/decisions",
                                     json={}, headers=headers)
                assert waiting.wait(timeout=5)
                assert not future.done()
                owner.commit()
                assert future.result(timeout=5).status_code == 401
        finally:
            event.remove(owner.bind, "before_cursor_execute", before_execute)


def test_auth_inflight_decision_finishes_before_account_revocation(
    client, session_factory, review_candidate, review_payload, request,
):
    from starlette.requests import Request
    from sqlalchemy import event
    from services.api.app.auth.access import COOKIE, require_access
    from services.api.app.auth.manage import manage_user
    from services.api.app.reviews.commands import decide
    from services.common.models import IssueAction, ReviewSession, ReviewUser
    from services.common.schemas import ReviewDecisionRequest

    item = review_candidate()
    user_id, headers = request.getfixturevalue("session_auth")
    headers = {**headers, "host": "testserver", "cookie": f"{COOKIE}={client.cookies.get(COOKIE)}"}
    req = Request({"type": "http", "method": "POST", "scheme": "http",
                   "path": f"/comment-issues/{item['link']['id']}/decisions", "query_string": b"",
                   "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})
    waiting = threading.Event()

    def before_execute(conn, cursor, statement, params, context, executemany):
        if "review_users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    def disable():
        with session_factory() as db:
            return manage_user(db, "disable", "pg-reviewer").enabled

    with session_factory() as owner:
        identity = require_access(req, owner)
        event.listen(owner.bind, "before_cursor_execute", before_execute)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(disable)
                assert waiting.wait(timeout=5)
                assert not future.done()
                decide(owner, item["link"]["id"], ReviewDecisionRequest(**review_payload(item)),
                       identity.username)
                assert future.result(timeout=5) is False
        finally:
            event.remove(owner.bind, "before_cursor_execute", before_execute)
    with session_factory() as db:
        assert db.query(IssueAction).one().operator == "pg-reviewer"
        assert db.get(CommentIssue, item["link"]["id"]).status == "accepted"
        assert not db.get(ReviewUser, user_id).enabled
        assert db.query(ReviewSession).count() == 0


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


def test_two_reviewers_conflict_without_overwriting(
    client, session_factory, review_candidate, review_payload,
):
    from services.api.app.reviews.commands import decide
    from services.common.models import IssueAction
    from services.common.schemas import ReviewDecisionRequest
    from fastapi import HTTPException

    item = review_candidate()
    barrier = threading.Barrier(2)

    def submit(decision):
        payload = ReviewDecisionRequest(**review_payload(item, decision))
        with session_factory() as db:
            barrier.wait(timeout=5)
            try:
                decide(db, item["link"]["id"], payload, decision + "-reviewer")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, ["accept", "reject"])) == [200, 409]
    with session_factory() as db:
        assert db.query(IssueAction).count() == 1


def test_concurrent_duplicate_review_returns_one_receipt(
    session_factory, review_candidate, review_payload,
):
    from services.api.app.reviews.commands import decide
    from services.common.models import IssueAction
    from services.common.schemas import ReviewDecisionRequest

    item = review_candidate()
    payload = ReviewDecisionRequest(**review_payload(item))
    barrier = threading.Barrier(2)

    def submit(_):
        with session_factory() as db:
            barrier.wait(timeout=5)
            return decide(db, item["link"]["id"], payload, "reviewer").model_dump()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    with session_factory() as db:
        assert db.query(IssueAction).count() == 1


def test_review_rejects_inflight_analysis_and_survives_later_reanalysis(
    session_factory, client, review_candidate, review_payload, worker_setup,
):

    item = review_candidate()
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        second = worker_setup.claim_next_pending_job(db)
    # The in-flight state invalidates the old page. The first valid decision must happen
    # before the claim or after completion, never silently approve a changing result.
    response = client.post(f"/comment-issues/{item['link']['id']}/decisions",
                           json=review_payload(item))
    assert response.status_code == 409
    assert worker_setup.process_job(second) == "completed"
    refreshed = client.get(f"/comment-issues/{item['link']['id']}").json()
    assert client.post(f"/comment-issues/{item['link']['id']}/decisions",
                       json=review_payload(refreshed)).status_code == 200
    with session_factory() as db:
        db.add(Job(comment_id=item["comment"]["id"]))
        db.commit()
        third = worker_setup.claim_next_pending_job(db)
    assert worker_setup.process_job(third) == "completed"
    with session_factory() as db:
        assert db.get(CommentIssue, item["link"]["id"]).status == "accepted"


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_revisions_preserve_original_and_append_once(
    client, session_factory, review_candidate, review_payload, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.commands import decide
    from services.common.models import IssueAction
    from services.common.schemas import ReviewDecisionRequest

    item = review_candidate()
    path = f"/comment-issues/{item['link']['id']}"
    assert client.post(path + "/decisions", json=review_payload(item)).status_code == 200
    item = client.get(path).json()
    first = {**review_payload(item, "reject", "重新核对后纠正"), "mode": "revise"}
    second = first if duplicate else {
        **review_payload(item, "reject", "另一位复核者的判断"), "mode": "revise",
    }
    barrier = threading.Barrier(2)

    def submit(payload):
        with session_factory() as db:
            barrier.wait(timeout=5)
            try:
                result = decide(db, item["link"]["id"],
                                ReviewDecisionRequest(**payload), "demo-reviewer")
                return 200, result.model_dump(mode="json")
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, [first, second]))
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        actions = db.query(IssueAction).order_by(IssueAction.id).all()
        assert [a.action for a in actions] == ["accept", "change"]
        assert db.get(CommentIssue, item["link"]["id"]).status == "rejected"


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_regrouping_saves_one_operation(
    session_factory, review_candidate, reassign_target, reassign_payload, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.reassign import reassign
    from services.common.models import IssueAction
    from services.common.schemas import ReassignRequest

    item = review_candidate()
    first = reassign_payload(item, reassign_target(item))
    second = first if duplicate else reassign_payload(item, reassign_target(item, title="另一目标"))
    barrier = threading.Barrier(2)

    def submit(payload):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                result = reassign(db, item["link"]["id"], ReassignRequest(**payload), "reviewer")
                return 200, result.model_dump(mode="json")
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, payload) for payload in [first, second]]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        assert db.query(IssueAction).count() == 2
        assert db.query(CommentIssue).filter_by(status="accepted").count() == 1
        assert db.get(CommentIssue, item["link"]["id"]).status == "rejected"


def test_opposite_regrouping_between_categories_does_not_deadlock(
    client, session_factory, review_candidate, reassign_target, reassign_payload,
):
    from services.api.app.reviews.reassign import reassign
    from services.common.models import IssueAction
    from services.common.schemas import ReassignRequest

    first, second = review_candidate(), review_candidate()
    target_id = reassign_target(first)
    with session_factory() as db:
        db.get(CommentIssue, second["link"]["id"]).issue_id = target_id
        db.commit()
    second = client.get(f"/comment-issues/{second['link']['id']}").json()
    requests = [(first, reassign_payload(first, target_id)),
                (second, reassign_payload(second, first["issue"]["id"]))]
    barrier = threading.Barrier(2)

    def submit(pair):
        item, payload = pair
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            return reassign(db, item["link"]["id"], ReassignRequest(**payload), "reviewer")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, pair) for pair in requests]
        results = [future.result(timeout=12) for future in futures]
    assert {r.target_issue_id for r in results} == {target_id, first["issue"]["id"]}
    with session_factory() as db:
        assert db.query(IssueAction).count() == 4
        assert db.query(CommentIssue).filter_by(status="accepted").count() == 2
        assert db.query(CommentIssue).filter_by(status="rejected").count() == 2


def test_regrouping_and_worker_share_category_lock_order(
    session_factory, review_candidate, reassign_target, reassign_payload,
    new_job, worker_setup, worker_settings, monkeypatch,
):
    import importlib
    from services.common.locking import lock_issue_groups
    from services.common.schemas import ReassignRequest

    module = importlib.import_module("services.api.app.reviews.reassign")
    item = review_candidate()
    target_id = reassign_target(item, category_id="logistics")
    payload = ReassignRequest(**reassign_payload(item, target_id))
    new_job(body="拉链卡住了。物流太慢。")
    worker_claim = claim(session_factory, worker_settings)
    barrier = threading.Barrier(2)

    def simultaneous_lock(db, *args):
        db.execute(text("SET LOCAL statement_timeout = '8s'"))
        barrier.wait(timeout=5)
        return lock_issue_groups(db, *args)

    monkeypatch.setattr(module, "lock_issue_groups", simultaneous_lock)
    monkeypatch.setattr(jobs, "lock_issue_groups", simultaneous_lock)

    def submit():
        with session_factory() as db:
            return module.reassign(db, item["link"]["id"], payload, "reviewer")

    with ThreadPoolExecutor(max_workers=2) as pool:
        human = pool.submit(submit)
        worker = pool.submit(worker_setup.process_job, worker_claim)
        assert human.result(timeout=12).target_issue_id == target_id
        assert worker.result(timeout=12) == "completed"
    with session_factory() as db:
        assert db.get(CommentIssue, item["link"]["id"]).status == "rejected"
        assert db.query(CommentIssue).filter_by(status="accepted").count() == 1
        assert db.query(CommentIssue).filter_by(status="suggested").count() == 2


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_manual_addition_saves_once(
    session_factory, manual_candidate, manual_payload, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.manual import add_link
    from services.common.models import IssueAction
    from services.common.schemas import ManualLinkRequest

    item = manual_candidate()
    first = manual_payload(item)
    second = first if duplicate else manual_payload(
        item, new_issue={"title": "另一问题", "category_id": "other"},
    )
    barrier = threading.Barrier(2)

    def submit(payload):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                result = add_link(db, item["comment"]["id"],
                                  ManualLinkRequest(**payload), "reviewer")
                return 200, result.model_dump(mode="json")
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, p) for p in [first, second]]
        results = [future.result(timeout=12) for future in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        assert db.query(IssueAction).count() == db.query(Issue).count() == 1
        assert db.query(CommentIssue).count() == 1


def test_two_comments_cannot_create_the_same_named_group_concurrently(
    session_factory, manual_candidate, manual_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.manual import add_link
    from services.common.models import IssueAction
    from services.common.schemas import ManualLinkRequest

    items = [manual_candidate(), manual_candidate()]
    barrier = threading.Barrier(2)

    def submit(item):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                add_link(db, item["comment"]["id"],
                         ManualLinkRequest(**manual_payload(item)), "human")
                return "saved"
            except HTTPException as exc:
                return exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, item) for item in items]
        assert sorted(f.result(timeout=12) for f in futures) == ["duplicate_issue", "saved"]
    with session_factory() as db:
        assert db.query(Issue).count() == db.query(IssueAction).count() == 1


def test_manual_addition_and_source_import_serialize_on_comment(
    client, session_factory, manual_candidate, manual_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.manual import add_link
    from services.common.models import Comment
    from services.common.schemas import ManualLinkRequest

    item = manual_candidate()
    c = item["comment"]
    barrier = threading.Barrier(2)

    def human():
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                return add_link(db, c["id"], ManualLinkRequest(**manual_payload(item)), "human")
            except HTTPException as exc:
                assert exc.status_code == 409 and exc.detail["code"] == "comment_changed"
                return None

    def update_source():
        barrier.wait(timeout=5)
        return client.post("/review-batches", json={"platform": c["platform"], "comments": [{
            **{key: c[key] for key in ("platform", "shop_id", "product_id", "source_review_id")},
            "body": "售后已经解决问题。",
        }]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        h, source = pool.submit(human), pool.submit(update_source)
        saved = h.result(timeout=12)
        assert source.result(timeout=12).status_code == 202
    with session_factory() as db:
        assert db.get(Comment, c["id"]).body == "售后已经解决问题。"
        assert db.query(CommentIssue).count() == (1 if saved else 0)
    if saved:
        detail = client.get(f"/comment-issues/{saved.link_id}").json()
        assert not detail["can_revise"] and detail["revision_blocked_reason"] == "source_changed"
        assert detail["actions"][0]["payload_json"]["snapshot"]["body"] == c["body"]


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_group_actions_save_one_decision(
    session_factory, issue_candidate, issue_payload, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.issue_workflow import act
    from services.common.models import IssueAction
    from services.common.schemas import IssueWorkflowRequest

    _, item = issue_candidate()
    first = issue_payload(item)
    second = first if duplicate else issue_payload(item, "dismiss")
    barrier = threading.Barrier(2)

    def submit(payload):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                result = act(db, item["issue"]["id"], IssueWorkflowRequest(**payload), "reviewer")
                return 200, result.model_dump(mode="json")
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, p) for p in [first, second]]
        results = [f.result(timeout=12) for f in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        assert db.query(IssueAction).filter(IssueAction.comment_issue_id.is_(None)).count() == 1
        assert db.get(Issue, item["issue"]["id"]).version == 2


def test_group_confirmation_and_last_evidence_rejection_serialize(
    session_factory, issue_candidate, issue_payload, review_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.commands import decide
    from services.api.app.reviews.issue_workflow import act
    from services.common.schemas import IssueWorkflowRequest, ReviewDecisionRequest

    link, item = issue_candidate()
    barrier = threading.Barrier(2)

    def submit(operation):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                if operation == "confirm":
                    act(db, item["issue"]["id"],
                        IssueWorkflowRequest(**issue_payload(item)), "human")
                else:
                    decide(db, link["link"]["id"], ReviewDecisionRequest(**{
                        **review_payload(link, "reject"), "mode": "revise",
                    }), "human")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, op) for op in ["confirm", "reject"]]
        results = [f.result(timeout=12) for f in futures]
    assert sorted(results) == [200, 409]
    with session_factory() as db:
        confirmed = db.get(Issue, item["issue"]["id"]).status == "confirmed"
        assert (db.get(CommentIssue, link["link"]["id"]).status == "accepted") == confirmed


def test_groups_sharing_comments_lock_them_in_one_order(
    client, session_factory, issue_candidate, issue_payload, reassign_target,
):
    from services.api.app.reviews.issue_workflow import act
    from services.api.app.reviews.rules import body_hash
    from services.common.schemas import IssueWorkflowRequest

    first_link, _ = issue_candidate()
    second_link, first_group = issue_candidate()
    target_id = reassign_target(first_link)
    with session_factory() as db:
        for record in (second_link, first_link):
            source = record["link"]
            db.add(CommentIssue(
                issue_id=target_id, comment_id=source["comment_id"], origin="human",
                status="accepted", evidence_text=source["evidence_text"],
                evidence_start=source["evidence_start"], evidence_end=source["evidence_end"],
                evidence_verified=True, evidence_body_hash=body_hash(record["comment"]["body"]),
                decided_by="human", decided_at=utcnow(),
            ))
        db.commit()
    second_group = client.get(f"/review-issues/{target_id}").json()
    barrier = threading.Barrier(2)

    def submit(item):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            return act(db, item["issue"]["id"],
                       IssueWorkflowRequest(**issue_payload(item)), "human")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, item) for item in (first_group, second_group)]
        assert [f.result(timeout=12).status for f in futures] == ["confirmed", "confirmed"]


def test_worker_adding_a_new_comment_during_group_locking_invalidates_confirmation(
    session_factory, issue_candidate, issue_payload, new_job, worker_setup, worker_settings,
    monkeypatch,
):
    from fastapi import HTTPException
    from services.api.app.reviews import issue_workflow
    from services.common.locking import lock_issue_groups
    from services.common.schemas import IssueWorkflowRequest

    _, item = issue_candidate()
    new_job()
    worker_claim = claim(session_factory, worker_settings)
    human_ready, worker_done = threading.Event(), threading.Event()

    def wait_for_worker(db, *args):
        human_ready.set()
        assert worker_done.wait(timeout=8)
        return lock_issue_groups(db, *args)

    monkeypatch.setattr(issue_workflow, "lock_issue_groups", wait_for_worker)

    def human():
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            try:
                issue_workflow.act(db, item["issue"]["id"],
                                   IssueWorkflowRequest(**issue_payload(item)), "human")
            except HTTPException as exc:
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(human)
        try:
            assert human_ready.wait(timeout=5)
            assert worker_setup.process_job(worker_claim) == "completed"
        finally:
            worker_done.set()
        assert future.result(timeout=12) == (409, "issue_changed")
    with session_factory() as db:
        assert db.get(Issue, item["issue"]["id"]).status == "proposed"
        assert db.query(CommentIssue).count() == 2


@pytest.mark.parametrize("mode,duplicate", [("merge", False), ("merge", True),
                                           ("split", False), ("split", True)])
def test_concurrent_structure_requests_are_atomic_and_idempotent(
    session_factory, structure_case, structure_payload, mode, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.structure import restructure
    from services.common.models import IssueAction
    from services.common.schemas import IssueMergeRequest, IssueSplitRequest

    links, source, target = structure_case()
    payload = structure_payload(source, target) if mode == "merge" else structure_payload(
        source, ids=[links[0]["link"]["id"]],
    )
    second = payload if duplicate else {**payload, "request_id": str(uuid.uuid4())}
    barrier = threading.Barrier(2)
    model = IssueMergeRequest if mode == "merge" else IssueSplitRequest

    def submit(data):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                return 200, restructure(db, source["issue"]["id"], model(**data), "human", mode)
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, p) for p in (payload, second)]
        results = [f.result(timeout=12) for f in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        assert db.query(IssueAction).filter(IssueAction.comment_issue_id.is_(None)).count() == 2
        assert db.query(Issue).count() == (2 if mode == "merge" else 3)


def test_opposite_direction_merges_cannot_form_cycle_or_deadlock(
    client, session_factory, structure_case, structure_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.structure import restructure
    from services.common.schemas import IssueMergeRequest

    links, source, target = structure_case()
    # Give the target its own member; both operations must lock the union in the same order.
    with session_factory() as db:
        link = db.get(CommentIssue, links[2]["link"]["id"])
        link.issue_id = target["issue"]["id"]
        db.commit()
    source = client.get(f"/review-issues/{source['issue']['id']}").json()
    target = client.get(f"/review-issues/{target['issue']['id']}").json()
    barrier = threading.Barrier(2)

    def submit(first, second):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                restructure(db, first["issue"]["id"],
                            IssueMergeRequest(**structure_payload(first, second)), "human", "merge")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, a, b) for a, b in ((source, target), (target, source))]
        assert sorted(f.result(timeout=12) for f in futures) == [200, 409]
    with session_factory() as db:
        assert db.query(Issue).filter(Issue.merged_into_id.is_not(None)).count() == 1
        assert db.query(CommentIssue).filter(CommentIssue.superseded_at.is_(None)).count() == 3


def test_split_and_review_of_selected_evidence_serialize(
    session_factory, structure_case, structure_payload, review_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.commands import decide
    from services.api.app.reviews.structure import restructure
    from services.common.schemas import IssueSplitRequest, ReviewDecisionRequest

    links, source, _ = structure_case()
    selected = links[0]
    barrier = threading.Barrier(2)

    def submit(mode):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                if mode == "split":
                    restructure(db, source["issue"]["id"], IssueSplitRequest(**structure_payload(
                        source, ids=[selected["link"]["id"]],
                    )), "human", "split")
                else:
                    decide(db, selected["link"]["id"], ReviewDecisionRequest(**{
                        **review_payload(selected, "reject"), "mode": "revise",
                    }), "human")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, mode) for mode in ("split", "reject")]
        assert sorted(f.result(timeout=12) for f in futures) == [200, 409]


def test_worker_adding_members_during_merge_rejects_stale_source(
    session_factory, structure_case, structure_payload, new_job, worker_setup, worker_settings,
    monkeypatch,
):
    from fastapi import HTTPException
    from services.api.app.reviews import structure
    from services.common.locking import lock_issue_groups
    from services.common.schemas import IssueMergeRequest

    _, source, target = structure_case()
    new_job()
    worker_claim = claim(session_factory, worker_settings)
    ready, done = threading.Event(), threading.Event()

    def wait_worker(db, *args):
        ready.set()
        assert done.wait(timeout=8)
        return lock_issue_groups(db, *args)

    monkeypatch.setattr(structure, "lock_issue_groups", wait_worker)

    def human():
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            try:
                structure.restructure(db, source["issue"]["id"],
                                      IssueMergeRequest(**structure_payload(source, target)),
                                      "human", "merge")
            except HTTPException as exc:
                return exc.status_code, exc.detail["code"]

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(human)
        try:
            assert ready.wait(timeout=5)
            assert worker_setup.process_job(worker_claim) == "completed"
        finally:
            done.set()
        assert future.result(timeout=12) == (409, "issue_changed")
    with session_factory() as db:
        assert db.get(Issue, source["issue"]["id"]).merged_into_id is None
        assert db.query(CommentIssue).filter(CommentIssue.superseded_at.is_(None)).count() == 4


@pytest.mark.parametrize("duplicate", [False, True])
def test_concurrent_rechecks_keep_one_new_decision_and_group_audit(
    session_factory, recheck_case, recheck_payload, duplicate,
):
    from fastapi import HTTPException
    from services.api.app.reviews.recheck import recheck
    from services.common.models import IssueAction
    from services.common.schemas import ReviewRecheckRequest

    _, item = recheck_case()
    first = recheck_payload(item)
    second = first if duplicate else recheck_payload(item, "reject")
    barrier = threading.Barrier(2)

    def submit(payload):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                return 200, recheck(db, item["link"]["id"],
                                    ReviewRecheckRequest(**payload), "human")
            except HTTPException as exc:
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, p) for p in (first, second)]
        results = [f.result(timeout=12) for f in futures]
    assert sorted(r[0] for r in results) == ([200, 200] if duplicate else [200, 409])
    if duplicate:
        assert results[0][1] == results[1][1]
    with session_factory() as db:
        # Original decision/confirmation plus two new audits.
        assert db.query(IssueAction).count() == 4
        assert db.get(CommentIssue, item["link"]["id"]).review_version == item["review_version"] + 1
        assert db.get(Issue, item["issue"]["id"]).status == "proposed"


def test_recheck_and_new_source_import_do_not_accept_the_wrong_snapshot(
    client, session_factory, recheck_case, recheck_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.recheck import recheck
    from services.common.schemas import ReviewRecheckRequest

    _, item = recheck_case()
    c = item["comment"]
    barrier = threading.Barrier(2)

    def human():
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                return recheck(db, item["link"]["id"],
                               ReviewRecheckRequest(**recheck_payload(item)), "human")
            except HTTPException as exc:
                assert exc.status_code == 409 and exc.detail["code"] == "review_changed"
                return None

    def source():
        barrier.wait(timeout=5)
        return client.post("/review-batches", json={"platform": c["platform"], "comments": [{
            **{key: c[key] for key in ("platform", "shop_id", "product_id", "source_review_id")},
            "body": "第三次更新：拉链问题已经解决。",
        }]})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(human), pool.submit(source)
        result = first.result(timeout=12)
        assert second.result(timeout=12).status_code == 202
    current = client.get(f"/comment-issues/{item['link']['id']}").json()
    assert current["needs_recheck"] and not current["can_recheck"]
    assert current["comment"]["body"] == "第三次更新：拉链问题已经解决。"
    if result:
        assert current["actions"][0]["payload_json"]["after"]["body"] == c["body"]


def test_recheck_and_merge_of_same_group_serialize_without_lost_evidence(
    client, session_factory, recheck_case, recheck_payload, reassign_target, structure_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.recheck import recheck
    from services.api.app.reviews.structure import restructure
    from services.common.schemas import IssueMergeRequest, ReviewRecheckRequest

    _, item = recheck_case()
    source = client.get(f"/review-issues/{item['issue']['id']}").json()
    target_id = reassign_target(item)
    target = client.get(f"/review-issues/{target_id}").json()
    barrier = threading.Barrier(2)

    def submit(mode):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                if mode == "recheck":
                    recheck(db, item["link"]["id"],
                            ReviewRecheckRequest(**recheck_payload(item)), "human")
                else:
                    restructure(db, source["issue"]["id"], IssueMergeRequest(**structure_payload(
                        source, target,
                    )), "human", "merge")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, mode) for mode in ("recheck", "merge")]
        assert sorted(f.result(timeout=12) for f in futures) == [200, 409]


def test_recheck_and_group_confirmation_cannot_commit_two_old_snapshots(
    client, session_factory, recheck_case, recheck_payload, issue_candidate, issue_payload,
):
    from fastapi import HTTPException
    from services.api.app.reviews.issue_workflow import act
    from services.api.app.reviews.recheck import recheck
    from services.common.schemas import IssueWorkflowRequest, ReviewRecheckRequest

    _, item = recheck_case()
    issue_candidate()  # A second, current accepted comment makes confirmation possible.
    with session_factory() as db:
        db.get(Issue, item["issue"]["id"]).status = "proposed"
        db.commit()
    item = client.get(f"/comment-issues/{item['link']['id']}").json()
    group = client.get(f"/review-issues/{item['issue']['id']}").json()
    assert group["valid_accepted_count"] == 1
    barrier = threading.Barrier(2)

    def submit(mode):
        with session_factory() as db:
            db.execute(text("SET LOCAL statement_timeout = '8s'"))
            barrier.wait(timeout=5)
            try:
                if mode == "recheck":
                    recheck(db, item["link"]["id"],
                            ReviewRecheckRequest(**recheck_payload(item)), "human")
                else:
                    act(db, group["issue"]["id"],
                        IssueWorkflowRequest(**issue_payload(group)), "human")
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, mode) for mode in ("recheck", "confirm")]
        assert sorted(f.result(timeout=12) for f in futures) == [200, 409]
