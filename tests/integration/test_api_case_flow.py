from __future__ import annotations

from pathlib import Path

import pytest

CSV_HEADER = "shop_id,product_id,source_review_id,review_date,rating,body\n"
CSV_OK = CSV_HEADER + (
    "shop-1,bag-1,r-001,2026-10-01,5,拉链很好用，容量也够。\n"
    "shop-1,bag-1,r-002,2026-10-02,2,拉链卡住了。\n"
)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def test_health_endpoints(client):
    for path in ["/", "/health/live", "/health/ready"]:
        response = client.get(path)
        assert response.status_code == 200, path


def test_batch_upload_creates_comments_and_jobs(client):
    response = client.post(
        "/review-batches",
        json={"platform": "demo", "filename": "reviews.csv", "csv_text": CSV_OK},
    )
    assert response.status_code == 202
    payload = response.json()
    batch_id = payload["batch_id"]
    assert payload["accepted_rows"] == 2
    assert payload["invalid_rows"] == 0
    assert payload["job_count"] == 2

    progress = client.get(f"/review-batches/{batch_id}")
    assert progress.status_code == 200
    data = progress.json()
    assert data["job_count"] == 2
    assert data["pending_rows"] == 2
    assert data["analyzed_rows"] == 0
    assert data["status"] == "imported"
    assert data["scope"]["as_of"]

    comments = client.get("/comments").json()
    assert len(comments) == 2
    assert {comment["source_review_id"] for comment in comments} == {"r-001", "r-002"}
    assert all(comment["analysis_status"] == "queued" for comment in comments)

    detail = client.get(f"/comments/{comments[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["revisions"] == []
    assert detail.json()["issues"] == []
    assert detail.json()["latest_analysis_run"] is None

    error_rows = client.get(f"/review-batches/{batch_id}/errors").json()
    assert error_rows == []


def test_batch_upload_reports_invalid_rows(client):
    csv_text = CSV_HEADER + (
        "shop-1,bag-1,r-010,2026-10-01,5,好用的包。\n"
        ",bag-1,r-011,2026-10-02,5,缺少店铺。\n"
    )
    response = client.post(
        "/review-batches", json={"platform": "demo", "csv_text": csv_text}
    )
    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted_rows"] == 1
    assert payload["invalid_rows"] == 1

    errors = client.get(f"/review-batches/{payload['batch_id']}/errors").json()
    assert len(errors) == 1
    assert errors[0]["row_number"] == 3
    assert errors[0]["code"] == "required"


def test_batch_upload_is_idempotent_with_key(client):
    body = {
        "platform": "demo",
        "csv_text": CSV_OK,
        "idempotency_key": "demo-batch-key-1",
    }
    first = client.post("/review-batches", json=body)
    second = client.post("/review-batches", json=body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["batch_id"] == second.json()["batch_id"]


def test_duplicate_upload_does_not_recreate_comments(client):
    client.post("/review-batches", json={"platform": "demo", "csv_text": CSV_OK})
    again = client.post("/review-batches", json={"platform": "demo", "csv_text": CSV_OK})

    payload = again.json()
    assert payload["accepted_rows"] == 0
    assert payload["duplicate_rows"] == 2
    assert payload["job_count"] == 0
    assert len(client.get("/comments").json()) == 2


def test_batch_rejects_missing_columns(client):
    response = client.post(
        "/review-batches",
        json={"platform": "demo", "csv_text": "product_id\nbag-1\n"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "batch_rejected"
    assert detail["errors"][0]["code"] == "missing_columns"


@pytest.mark.skipif(not FRONTEND_DIR.is_dir(), reason="frontend not built yet")
def test_static_ui_is_served(client):
    response = client.get("/ui/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "batches" in response.text
