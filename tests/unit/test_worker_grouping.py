"""Worker semantic grouping selection and fallback behaviour."""

from __future__ import annotations

import hashlib
import uuid

import httpx
import pytest

from services.common.models import (
    AnalysisRun,
    CommentIssue,
    Issue,
    IssueStatus,
    LinkOrigin,
    LinkStatus,
)
from services.common.schemas import (
    ExtractedIssue,
    ExtractionResult,
    GroupingAction,
    GroupSuggestionResult,
    HasIssue,
)
from services.worker.app.analysis import AnalysisInput, VerifiedAnalysis, VerifiedIssue
from services.worker.app import jobs


def _snapshot(comment_id: str, product: str = "bag-1", body: str = "拉链卡住了") -> AnalysisInput:
    return AnalysisInput(
        comment_id, "demo", "shop-1", product, body,
        hashlib.sha256(body.encode()).hexdigest(), 1, 1,
    )


def _verified(text: str = "拉链卡住了", category: str = "quality") -> VerifiedAnalysis:
    issue = ExtractedIssue(category_id=category, description=text, evidence_text=text)
    result = ExtractionResult(
        comment_id="c",
        has_issue=HasIssue.YES,
        issues=[issue],
        model_version="test",
        prompt_version="v1",
    )
    return VerifiedAnalysis(result, (VerifiedIssue(issue, 0, len(text)),), "yes", 0)


def _seed_issue(session_factory, product: str, title: str, description: str) -> str:
    with session_factory() as db:
        issue = Issue(
            platform="demo", shop_id="shop-1", product_id=product,
            category_id="quality", title=title, description=description,
            status=IssueStatus.PROPOSED.value, created_by="ai",
        )
        db.add(issue)
        db.commit()
        return issue.id


def _seed_run(session_factory, job_id: int, comment_id: str) -> int:
    with session_factory() as db:
        run = AnalysisRun(
            job_id=job_id,
            comment_id=comment_id,
            model_version="test",
            prompt_version="v1",
            category_version="1",
            input_hash="x",
            output_json={"_worker": {}},
            status="succeeded",
        )
        db.add(run)
        db.commit()
        return run.id


def test_save_issue_links_uses_suggest_link_and_writes_similarity(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链卡住了", product="bag-group")
    existing_id = _seed_issue(
        session_factory, "bag-group", "拉链问题", "拉链拉不上",
    )
    run_id = _seed_run(session_factory, job_id, comment_id)

    def fake_suggest(**kwargs):
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=existing_id,
            similar_issue_ids=[existing_id],
            similarity=0.91,
            rationale="test link",
        )

    monkeypatch.setattr(jobs, "call_suggest_groups", fake_suggest)
    snapshot = _snapshot(comment_id, product="bag-group", body="拉链卡住了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链卡住了"), run_id=run_id,
            ai_service_url="http://ai.test",
        )
        db.commit()
        links = db.query(CommentIssue).all()
        assert len(links) == 1
        assert links[0].issue_id == existing_id
        assert links[0].similarity == pytest.approx(0.91)
        run = db.get(AnalysisRun, run_id)
        hints = (run.output_json or {}).get("grouping_hints")
        assert hints and hints[0]["action"] == "link_existing"
        assert hints[0]["fallback"] is None


def test_save_issue_links_create_new_despite_existing_candidate(
    session_factory, new_job, monkeypatch,
):
    _, comment_id, _ = new_job(body="掉色严重", product="bag-group")
    other_id = _seed_issue(session_factory, "bag-group", "拉链", "拉链坏了")

    def fake_suggest(**kwargs):
        return GroupSuggestionResult(
            action=GroupingAction.CREATE_NEW,
            similarity=0.2,
            rationale="different issue",
        )

    monkeypatch.setattr(jobs, "call_suggest_groups", fake_suggest)
    snapshot = _snapshot(comment_id, product="bag-group", body="掉色严重")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("掉色严重"), run_id=2,
            ai_service_url="http://ai.test",
        )
        db.commit()
        links = db.query(CommentIssue).all()
        assert len(links) == 1
        assert links[0].issue_id != other_id
        assert links[0].similarity == pytest.approx(0.2)
        assert db.query(Issue).count() == 2


def test_suggest_failure_falls_back_to_category_baseline(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链又坏了", product="bag-group")
    earliest = _seed_issue(session_factory, "bag-group", "最早", "拉链问题A")
    run_id = _seed_run(session_factory, job_id, comment_id)

    def boom(**kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(jobs, "call_suggest_groups", boom)
    snapshot = _snapshot(comment_id, product="bag-group", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=run_id,
            ai_service_url="http://ai.test",
        )
        db.commit()
        link = db.query(CommentIssue).one()
        assert link.issue_id != earliest
        assert link.status == "suggested"
        assert link.similarity is None
        assert db.query(Issue).count() == 2
        hints = (db.get(AnalysisRun, run_id).output_json or {}).get("grouping_hints")
        assert hints and hints[0]["action"] == "create_new"
        assert hints[0]["fallback"] == "ConnectError"


def test_suggest_timeout_falls_back(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链又坏了", product="bag-timeout")
    earliest = _seed_issue(session_factory, "bag-timeout", "最早", "拉链")
    run_id = _seed_run(session_factory, job_id, comment_id)

    def timed_out(**kwargs):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(jobs, "call_suggest_groups", timed_out)
    snapshot = _snapshot(comment_id, product="bag-timeout", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=run_id,
            ai_service_url="http://ai.test",
        )
        db.commit()
        assert db.query(CommentIssue).one().issue_id != earliest
        assert db.query(CommentIssue).one().status == "suggested"
        hints = (db.get(AnalysisRun, run_id).output_json or {}).get("grouping_hints")
        assert hints[0]["fallback"] == "TimeoutException"


def test_suggest_http_503_falls_back(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链又坏了", product="bag-503")
    earliest = _seed_issue(session_factory, "bag-503", "最早", "拉链")
    run_id = _seed_run(session_factory, job_id, comment_id)

    def service_unavailable(**kwargs):
        response = httpx.Response(503, request=httpx.Request("POST", "http://ai.test/suggest-groups"))
        raise httpx.HTTPStatusError("503", request=response.request, response=response)

    monkeypatch.setattr(jobs, "call_suggest_groups", service_unavailable)
    snapshot = _snapshot(comment_id, product="bag-503", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=run_id,
            ai_service_url="http://ai.test",
        )
        db.commit()
        assert db.query(CommentIssue).one().issue_id != earliest
        assert db.query(CommentIssue).one().status == "suggested"
        hints = (db.get(AnalysisRun, run_id).output_json or {}).get("grouping_hints")
        assert hints[0]["fallback"] == "HTTPStatusError"


def test_no_ai_url_falls_back_without_http(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链又坏了", product="bag-nourl")
    earliest = _seed_issue(session_factory, "bag-nourl", "最早", "拉链")
    run_id = _seed_run(session_factory, job_id, comment_id)
    called = {"n": 0}

    def should_not_call(**kwargs):
        called["n"] += 1
        raise AssertionError("HTTP must not run without ai_service_url")

    monkeypatch.setattr(jobs, "call_suggest_groups", should_not_call)
    snapshot = _snapshot(comment_id, product="bag-nourl", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=run_id,
            ai_service_url=None,
        )
        db.commit()
        assert called["n"] == 0
        assert db.query(CommentIssue).one().issue_id != earliest
        assert db.query(CommentIssue).one().status == "suggested"
        hints = (db.get(AnalysisRun, run_id).output_json or {}).get("grouping_hints")
        assert hints[0]["fallback"] == "no_ai_url"


def test_stale_issue_id_after_revalidation_falls_back(
    session_factory, new_job, monkeypatch,
):
    job_id, comment_id, _ = new_job(body="拉链又坏了", product="bag-stale")
    earliest = _seed_issue(session_factory, "bag-stale", "最早", "拉链A")
    gone_id = _seed_issue(session_factory, "bag-stale", "将消失", "拉链B")
    run_id = _seed_run(session_factory, job_id, comment_id)

    def link_gone(**kwargs):
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=gone_id,
            similarity=0.95,
            rationale="stale after lock",
        )

    monkeypatch.setattr(jobs, "call_suggest_groups", link_gone)

    original_locked = jobs._list_active_issues_locked

    def locked_without_gone(db, snapshot, category_id):
        rows = original_locked(db, snapshot, category_id)
        return [row for row in rows if row.id != gone_id]

    monkeypatch.setattr(jobs, "_list_active_issues_locked", locked_without_gone)
    snapshot = _snapshot(comment_id, product="bag-stale", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=run_id,
            ai_service_url="http://ai.test",
        )
        db.commit()
        assert db.query(CommentIssue).one().issue_id != earliest
        assert db.query(CommentIssue).one().status == "suggested"
        hints = (db.get(AnalysisRun, run_id).output_json or {}).get("grouping_hints")
        assert hints[0]["fallback"] == "stale_issue_id"


def test_http_runs_before_row_lock(session_factory, new_job, monkeypatch):
    _, comment_id, _ = new_job(body="拉链卡住了", product="bag-order")
    existing_id = _seed_issue(session_factory, "bag-order", "拉链", "拉链拉不上")
    order: list[str] = []

    def fake_suggest(**kwargs):
        order.append("http")
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=existing_id,
            similarity=0.9,
            rationale="order",
        )

    original_lock = jobs._group_lock
    original_locked = jobs._list_active_issues_locked

    def tracking_lock(db, snapshot, category):
        order.append("advisory_lock")
        return original_lock(db, snapshot, category)

    def tracking_locked(db, snapshot, category_id):
        order.append("row_lock")
        return original_locked(db, snapshot, category_id)

    monkeypatch.setattr(jobs, "call_suggest_groups", fake_suggest)
    monkeypatch.setattr(jobs, "_group_lock", tracking_lock)
    monkeypatch.setattr(jobs, "_list_active_issues_locked", tracking_locked)
    snapshot = _snapshot(comment_id, product="bag-order", body="拉链卡住了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链卡住了"), run_id=9,
            ai_service_url="http://ai.test",
        )
        db.commit()
    assert order.index("http") < order.index("advisory_lock")
    assert order.index("http") < order.index("row_lock")


def test_invalid_suggested_issue_id_falls_back(
    session_factory, new_job, monkeypatch,
):
    _, comment_id, _ = new_job(body="拉链又坏了", product="bag-group")
    earliest = _seed_issue(session_factory, "bag-group", "最早", "拉链")

    def bad_id(**kwargs):
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=str(uuid.uuid4()),
            similarity=0.99,
            rationale="foreign id",
        )

    monkeypatch.setattr(jobs, "call_suggest_groups", bad_id)
    snapshot = _snapshot(comment_id, product="bag-group", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=4,
            ai_service_url="http://ai.test",
        )
        db.commit()
        assert db.query(CommentIssue).one().issue_id != earliest
        assert db.query(CommentIssue).one().status == "suggested"


def test_human_accepted_link_is_preserved(
    session_factory, new_job, monkeypatch,
):
    _, comment_id, _ = new_job(body="拉链卡住了", product="bag-group")
    issue_id = _seed_issue(session_factory, "bag-group", "拉链", "拉链")
    with session_factory() as db:
        db.add(CommentIssue(
            comment_id=comment_id, issue_id=issue_id,
            status=LinkStatus.ACCEPTED.value, origin=LinkOrigin.HUMAN.value,
            evidence_text="拉链卡住了", evidence_verified=True,
        ))
        db.commit()

    def fake_suggest(**kwargs):
        return GroupSuggestionResult(
            action=GroupingAction.CREATE_NEW, similarity=0.1, rationale="x",
        )

    monkeypatch.setattr(jobs, "call_suggest_groups", fake_suggest)
    # After create_new a second issue appears; accepted link must remain untouched.
    snapshot = _snapshot(comment_id, product="bag-group", body="拉链卡住了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链卡住了"), run_id=5,
            ai_service_url="http://ai.test",
        )
        db.commit()
        accepted = db.query(CommentIssue).filter_by(issue_id=issue_id).one()
        assert accepted.status == LinkStatus.ACCEPTED.value
        assert accepted.origin == LinkOrigin.HUMAN.value
