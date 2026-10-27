"""Real-stack end-to-end check against the running Docker Compose services."""

from __future__ import annotations

import time

import httpx

BASE = "http://127.0.0.1:8000"
AI = "http://127.0.0.1:8100"

CSV = (
    "shop_id,product_id,source_review_id,review_date,rating,body\n"
    "real-shop,bag-real,REAL-001,2026-10-01,2,拉链拉到一半就卡住，拉不上，只能退货。\n"
    "real-shop,bag-real,REAL-002,2026-10-02,5,整体不错，家人很喜欢。\n"
    "real-shop,bag-real,REAL-003,2026-10-03,3,肩带有点窄，背久了肩膀疼。\n"
)


def main() -> None:
    print("== health ==")
    for url in (f"{BASE}/health/live", f"{BASE}/health/ready", f"{AI}/health/live"):
        response = httpx.get(url, timeout=10)
        print(url, response.status_code)
        assert response.status_code == 200

    ui = httpx.get(f"{BASE}/ui/", timeout=10)
    print("/ui/", ui.status_code, len(ui.text))
    assert ui.status_code == 200 and "app.js" in ui.text

    print("== upload batch ==")
    response = httpx.post(
        f"{BASE}/review-batches",
        json={"platform": "real-demo", "filename": "real_reviews.csv", "csv_text": CSV},
        timeout=20,
    )
    print(response.status_code, response.json())
    assert response.status_code == 202
    payload = response.json()
    batch_id = payload["batch_id"]
    assert payload["accepted_rows"] == 3 and payload["job_count"] == 3

    print("== wait for worker ==")
    deadline = time.time() + 60
    last = None
    while time.time() < deadline:
        last = httpx.get(f"{BASE}/review-batches/{batch_id}", timeout=10).json()
        print("progress:", last["status"], last["analyzed_rows"], last["failed_rows"])
        if last["status"] in {"completed", "partially_failed"}:
            break
        time.sleep(2)
    assert last is not None
    assert last["status"] == "completed", last
    assert last["analyzed_rows"] == 3 and last["failed_rows"] == 0
    assert last["analysis_coverage"] == 1.0

    comments = httpx.get(f"{BASE}/comments", params={"limit": 200}, timeout=10).json()
    real = [c for c in comments if c["product_id"] == "bag-real"]
    print("comments:", [(c["source_review_id"], c["analysis_status"], c["has_issue"]) for c in real])
    assert len(real) == 3
    assert all(c["analysis_status"] == "analyzed" for c in real)
    zipper = next(c for c in real if c["source_review_id"] == "REAL-001")
    detail = httpx.get(f"{BASE}/comments/{zipper['id']}", timeout=10).json()
    assert detail["issues"], "zipper comment should have a suggested link"
    assert detail["issues"][0]["evidence_verified"] is True
    assert "拉链" in detail["issues"][0]["evidence_text"]
    assert detail["latest_analysis_run"]["model_version"]

    issues = httpx.get(f"{BASE}/issues", params={"product_id": "bag-real"}, timeout=10).json()
    print("issues:", [(i["category_id"], i["status"], i["suggested_count"]) for i in issues])
    assert issues, "expected issues for bag-real"
    quality = next(i for i in issues if i["category_id"] == "quality")
    issue_detail = httpx.get(f"{BASE}/issues/{quality['id']}", timeout=10).json()
    assert issue_detail["links"] and issue_detail["links"][0]["evidence_verified"]

    stats = httpx.get(f"{BASE}/stats/summary", params={"product_id": "bag-real"}, timeout=10).json()
    print("stats:", stats["received_rows"], stats["analyzed_rows"], stats["ai_suggested_count"])
    assert stats["received_rows"] == 3 and stats["analyzed_rows"] == 3

    # Duplicate upload must not create new comments/jobs.
    again = httpx.post(
        f"{BASE}/review-batches",
        json={"platform": "real-demo", "csv_text": CSV},
        timeout=20,
    ).json()
    print("duplicate upload:", again)
    assert again["accepted_rows"] == 0 and again["duplicate_rows"] == 3

    print("REAL E2E OK")


if __name__ == "__main__":
    main()
