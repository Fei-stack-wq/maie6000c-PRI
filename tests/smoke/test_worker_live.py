"""Real API + worker + HTTP AI service, enabled explicitly by SMOKE_BASE_URL."""
import os
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from services.common.models import Comment, IngestionBatch, Job, utcnow

pytestmark = pytest.mark.smoke


@pytest.fixture()
def live_url():
    url = os.getenv("SMOKE_BASE_URL")
    if not url or not os.getenv("WORKER_LIVE_FAULT_PROXY"):
        pytest.skip("Use tests/support/run_worker_live.py for the fault/recovery smoke suite")
    return url


def wait_batch(url, batch_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = httpx.get(f"{url}/review-batches/{batch_id}", timeout=5)
        response.raise_for_status()
        result = response.json()
        if result["status"] in ("completed", "partially_failed"):
            return result
        time.sleep(0.1)
    pytest.fail("Live batch did not finish within 15 seconds")


def upload(url, product, bodies):
    csv = "shop_id,product_id,source_review_id,body\n"
    csv += "".join(f"shop-live,{product},r-{i},{body}\n" for i, body in enumerate(bodies))
    response = httpx.post(f"{url}/review-batches", json={"platform": "live", "csv_text": csv})
    response.raise_for_status()
    return response.json()["batch_id"]


def comments(url, product):
    response = httpx.get(f"{url}/comments", params={"product_id": product})
    response.raise_for_status()
    return response.json()


def test_live_results_and_metrics(live_url):
    product = "live-" + uuid.uuid4().hex
    batch = upload(live_url, product, ["拉链卡住了。", "总体不错，很喜欢。", "怪"])
    result = wait_batch(live_url, batch)
    assert result["status"] == "completed" and result["analyzed_rows"] == 3
    rows = comments(live_url, product)
    assert {row["has_issue"] for row in rows} == {"yes", "no", "unknown"}
    issues = httpx.get(f"{live_url}/issues", params={"product_id": product}).json()
    detail = httpx.get(f"{live_url}/issues/{issues[0]['id']}").json()
    assert detail["links"][0]["evidence_verified"]
    link = detail["links"][0]
    assert link["evidence_text"] in link["comment_body"]
    metrics = httpx.get("http://127.0.0.1:8200/metrics")
    assert metrics.status_code == 200
    assert "worker_job_events_total" in metrics.text
    assert "worker_last_poll_timestamp_seconds" in metrics.text


@pytest.mark.parametrize("prefix,expected,attempts", [
    ("fail-once-", "completed", 2), ("always-fail-", "partially_failed", 3),
])
def test_live_http_retry_and_final_failure(live_url, prefix, expected, attempts):
    product = prefix + uuid.uuid4().hex
    batch = upload(live_url, product, ["拉链卡住了。"])
    result = wait_batch(live_url, batch)
    assert result["status"] == expected
    row = comments(live_url, product)[0]
    detail = httpx.get(f"{live_url}/comments/{row['id']}").json()
    assert row["analysis_status"] == ("analyzed" if expected == "completed" else "failed")
    assert detail["latest_analysis_run"]["status"] == (
        "succeeded" if expected == "completed" else "failed"
    )
    url = os.environ["WORKER_TEST_DATABASE_URL"]
    assert make_url(url).database.endswith("_test")
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            job = db.execute(select(Job).where(Job.comment_id == row["id"])).scalar_one()
            assert job.attempts == attempts
            assert job.status == ("completed" if expected == "completed" else "failed")
    finally:
        engine.dispose()


def test_live_expired_task_is_recovered(live_url):
    url = os.environ["WORKER_TEST_DATABASE_URL"]
    assert make_url(url).database.endswith("_test")
    product = "recover-" + uuid.uuid4().hex
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            batch = IngestionBatch(
                platform="live", source_type="csv", status="imported",
                accepted_rows=1, declared_rows=1,
            )
            db.add(batch)
            db.flush()
            comment = Comment(
                platform="live", shop_id="shop-live", product_id=product,
                source_review_id=uuid.uuid4().hex, body="拉链卡住了。",
                content_hash="live-test", batch_id=batch.id, analysis_status="analyzing",
            )
            db.add(comment)
            db.flush()
            job = Job(
                comment_id=comment.id, batch_id=batch.id, status="claimed", attempts=1,
                claimed_at=utcnow() - timedelta(seconds=10),
                lease_expires_at=utcnow() - timedelta(seconds=1),
            )
            db.add(job)
            db.commit()
            batch_id, job_id = batch.id, job.id
        assert wait_batch(live_url, batch_id)["status"] == "completed"
        assert httpx.get(f"{live_url}/jobs/{job_id}").json()["attempts"] == 2
    finally:
        engine.dispose()
