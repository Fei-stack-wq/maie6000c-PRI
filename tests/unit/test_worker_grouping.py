"""Worker semantic grouping selection and fallback behaviour."""

from __future__ import annotations

import hashlib
import uuid

import httpx
import pytest

from services.common.models import CommentIssue, Issue, IssueStatus, LinkOrigin, LinkStatus
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


def test_save_issue_links_uses_suggest_link_and_writes_similarity(
    session_factory, new_job, monkeypatch,
):
    _, comment_id, _ = new_job(body="拉链卡住了", product="bag-group")
    existing_id = _seed_issue(
        session_factory, "bag-group", "拉链问题", "拉链拉不上",
    )

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
            db, snapshot, _verified("拉链卡住了"), run_id=1,
            ai_service_url="http://ai.test",
        )
        db.commit()
        links = db.query(CommentIssue).all()
        assert len(links) == 1
        assert links[0].issue_id == existing_id
        assert links[0].similarity == pytest.approx(0.91)


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
    _, comment_id, _ = new_job(body="拉链又坏了", product="bag-group")
    earliest = _seed_issue(session_factory, "bag-group", "最早", "拉链问题A")

    def boom(**kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(jobs, "call_suggest_groups", boom)
    snapshot = _snapshot(comment_id, product="bag-group", body="拉链又坏了")
    with session_factory() as db:
        jobs.save_issue_links(
            db, snapshot, _verified("拉链又坏了"), run_id=3,
            ai_service_url="http://ai.test",
        )
        db.commit()
        link = db.query(CommentIssue).one()
        assert link.issue_id == earliest
        assert link.similarity is None
        assert db.query(Issue).count() == 1


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
        assert db.query(CommentIssue).one().issue_id == earliest


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
