from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.smoke

CSV_HEADER = "shop_id,product_id,source_review_id,review_date,rating,body\n"
CSV_OK = CSV_HEADER + "shop-1,bag-1,smoke-001,2026-10-01,2,拉链卡住了。\n"


def test_smoke_batch_to_analysis_flow():
    base_url = os.getenv("SMOKE_BASE_URL")
    if not base_url:
        pytest.skip("SMOKE_BASE_URL not set")

    response = httpx.post(
        f"{base_url}/review-batches",
        json={
            "platform": "smoke",
            "csv_text": CSV_OK.replace("smoke-001", "smoke-" + uuid.uuid4().hex),
        },
        timeout=10,
    )
    assert response.status_code == 202
    batch_id = response.json()["batch_id"]

    deadline = time.time() + 40
    last = None
    while time.time() < deadline:
        poll = httpx.get(f"{base_url}/review-batches/{batch_id}", timeout=10)
        assert poll.status_code == 200
        last = poll.json()
        if last["status"] in {"completed", "partially_failed"}:
            break
        time.sleep(1)

    assert last is not None
    assert last["status"] in {"completed", "partially_failed"}
    assert last["analyzed_rows"] + last["failed_rows"] == 1

    comments = httpx.get(f"{base_url}/comments", params={"product_id": "bag-1"}, timeout=10)
    assert comments.status_code == 200
    assert comments.json(), "worker should have stored the comment"
