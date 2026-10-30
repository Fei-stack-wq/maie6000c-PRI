"""End-to-end: API ingestion -> Worker -> AI extraction -> issue links.

The AI service is called through the Worker's ``httpx.post``; the test patches
that single module-level function so the pipeline runs in-process (no server,
no PostgreSQL) while still exercising the real extraction + validation logic.
"""

from __future__ import annotations

import httpx

from services.ai.app.main import extract_issues
from services.common.schemas import ExtractionRequest
from services.worker.app import main as worker_main

CSV = (
    "shop_id,product_id,source_review_id,review_date,rating,body\n"
    "shop-1,bag-1,e2e-001,2026-10-01,2,拉链拉到一半就卡住，拉不上。\n"
    "shop-1,bag-1,e2e-002,2026-10-02,5,整体不错，家人很喜欢。\n"
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_batch_to_issue_end_to_end(client, session_factory, monkeypatch):
    monkeypatch.setattr(worker_main, "get_session_factory", lambda: session_factory)

    def fake_post(url, json, timeout=None):  # noqa: ANN001, ARG001
        result = extract_issues(ExtractionRequest(**json))
        return _FakeResponse(result.model_dump(mode="json"))

    monkeypatch.setattr(httpx, "post", fake_post)

    response = client.post(
        "/review-batches",
        json={"platform": "demo", "csv_text": CSV},
    )
    assert response.status_code == 202
    batch_id = response.json()["batch_id"]

    # Worker: claim and process every pending job (single-threaded for the test).
    with session_factory() as db:
        jobs = []
        while True:
            job = worker_main.claim_next_pending_job(db)
            if job is None:
                break
            jobs.append(job)
    assert len(jobs) == 2
    for claim in jobs:
        worker_main.process_job(claim)

    progress = client.get(f"/review-batches/{batch_id}").json()
    assert progress["analyzed_rows"] == 2
    assert progress["failed_rows"] == 0
    assert progress["status"] == "completed"
    assert progress["analysis_coverage"] == 1.0

    comments = client.get("/comments").json()
    assert len(comments) == 2
    analyzed = [comment for comment in comments if comment["analysis_status"] == "analyzed"]
    assert len(analyzed) == 2
    assert {comment["has_issue"] for comment in analyzed} == {"yes", "no"}

    issues = client.get("/issues").json()
    assert issues, "expected at least one proposed issue"
    quality = [issue for issue in issues if issue["category_id"] == "quality"]
    assert quality and quality[0]["suggested_count"] >= 1

    detail = client.get(f"/issues/{quality[0]['id']}").json()
    assert detail["links"], "issue detail should carry comment links"
    link = detail["links"][0]
    assert link["evidence_verified"] is True
    assert link["evidence_text"]
    assert link["evidence_start"] is not None

    stats = client.get("/stats/summary").json()
    assert stats["received_rows"] == 2
    assert stats["analyzed_rows"] == 2
    assert stats["ai_suggested_count"] >= 1
