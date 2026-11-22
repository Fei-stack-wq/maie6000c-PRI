"""Same-product semantic grouping through the worker orchestrator."""

from __future__ import annotations

from services.common.models import CommentIssue, Issue
from services.worker.app import jobs


def claim(factory, settings):
    with factory() as db:
        return jobs.claim_next_pending_job(db, settings)


def test_similar_reviews_share_issue_different_specific_split(
    session_factory, new_job, worker_setup, worker_settings, ai_response,
):
    # Two zipper complaints on one product should land on one quality issue.
    job_a, comment_a, _ = new_job(body="这个包的拉链拉不上，卡住了。", product="bag-sem")
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"

    job_b, comment_b, _ = new_job(body="拉链又卡住了，根本拉不上。", product="bag-sem")
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"

    with session_factory() as db:
        links_a = db.query(CommentIssue).filter_by(comment_id=comment_a).all()
        links_b = db.query(CommentIssue).filter_by(comment_id=comment_b).all()
        assert links_a and links_b
        quality_a = [
            link for link in links_a
            if db.get(Issue, link.issue_id).category_id == "quality"
        ]
        quality_b = [
            link for link in links_b
            if db.get(Issue, link.issue_id).category_id == "quality"
        ]
        assert quality_a and quality_b
        assert quality_a[0].issue_id == quality_b[0].issue_id
        assert quality_b[0].similarity is not None

    # Colour fade on the same product should open a separate quality issue when scores differ.
    job_c, comment_c, _ = new_job(body="颜色掉色很严重，和图片完全不一样。", product="bag-sem")
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        fade_links = db.query(CommentIssue).filter_by(comment_id=comment_c).all()
        fade_quality = [
            link for link in fade_links
            if db.get(Issue, link.issue_id).category_id == "quality"
        ]
        assert fade_quality
        zipper_id = quality_a[0].issue_id
        assert all(link.issue_id != zipper_id for link in fade_quality)


def test_different_products_do_not_merge(
    session_factory, new_job, worker_setup, worker_settings, ai_response,
):
    _, comment_a, _ = new_job(body="拉链卡住了拉不上。", product="bag-a")
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    _, comment_b, _ = new_job(body="拉链卡住了拉不上。", product="bag-b")
    assert worker_setup.process_job(claim(session_factory, worker_settings)) == "completed"
    with session_factory() as db:
        issue_a = db.query(CommentIssue).filter_by(comment_id=comment_a).one().issue_id
        issue_b = db.query(CommentIssue).filter_by(comment_id=comment_b).one().issue_id
        assert issue_a != issue_b
        assert db.get(Issue, issue_a).product_id == "bag-a"
        assert db.get(Issue, issue_b).product_id == "bag-b"
