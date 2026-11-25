"""Docker/stack smoke: LLM-or-heuristic extract + semantic grouping.

Requires a running Compose stack with AI using sentence_transformers (not hashing)
and SMOKE_BASE_URL pointing at the API (default http://localhost:8000).
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

pytestmark = pytest.mark.smoke

CSV_HEADER = "shop_id,product_id,source_review_id,review_date,rating,body\n"


def _base_url() -> str:
    return os.getenv("SMOKE_BASE_URL", "").rstrip("/")


def _threshold() -> float:
    return float(os.getenv("GROUPING_SIMILARITY_THRESHOLD", "0.35"))


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _post_batch(client: httpx.Client, platform: str, rows: list[str]) -> str:
    csv_text = CSV_HEADER + "".join(rows)
    response = client.post(
        "/review-batches",
        json={"platform": platform, "csv_text": csv_text},
        timeout=30,
    )
    assert response.status_code == 202, response.text
    return response.json()["batch_id"]


def _wait_batch(client: httpx.Client, batch_id: str, expected_rows: int, timeout: float = 180.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        poll = client.get(f"/review-batches/{batch_id}", timeout=15)
        assert poll.status_code == 200
        last = poll.json()
        if last["status"] in {"completed", "partially_failed"}:
            break
        time.sleep(2)
    assert last is not None
    assert last["status"] in {"completed", "partially_failed"}, last
    assert last["analyzed_rows"] + last["failed_rows"] == expected_rows, last
    assert last["analyzed_rows"] >= 1, last
    return last


def _comment_detail(client: httpx.Client, comment_id: str) -> dict:
    response = client.get(f"/comments/{comment_id}", timeout=15)
    assert response.status_code == 200, response.text
    return response.json()


def _quality_issue_ids(detail: dict) -> set[str]:
    return {
        link["issue_id"]
        for link in detail.get("issues", [])
        if link.get("status") in {"suggested", "accepted"}
    }


@pytest.fixture(scope="module")
def api():
    base = _base_url()
    if not base:
        pytest.skip("SMOKE_BASE_URL not set")
    # trust_env=False: Windows system proxy (e.g. 127.0.0.1:7897) otherwise 502s local Compose.
    with httpx.Client(base_url=base, trust_env=False) as client:
        live = client.get("/health/live", timeout=10)
        assert live.status_code == 200
        yield client


def test_ai_uses_sentence_transformers_not_hashing():
    """Hit AI /suggest-groups; near-duplicate phrasing should link at locked T_main."""
    ai_url = os.getenv("SMOKE_AI_URL", "http://localhost:8100").rstrip("/")
    if not _base_url() and not os.getenv("SMOKE_AI_URL"):
        pytest.skip("SMOKE_BASE_URL / SMOKE_AI_URL not set")
    response = httpx.post(
        f"{ai_url}/suggest-groups",
        json={
            "product_id": "smoke-group",
            "category_id": "quality",
            "candidate_text": "拉链卡住拉不上",
            "existing_issues": [
                {
                    "id": "iss-zip",
                    "title": "拉链卡住",
                    "description": "拉链又卡住拉不上",
                }
            ],
        },
        timeout=60,
        trust_env=False,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["action"] == "link_existing", body
    assert body["issue_id"] == "iss-zip"
    assert body["similarity"] is not None
    assert body["similarity"] >= _threshold()
    assert "hashing" not in (body.get("rationale") or "").lower()


def test_same_product_synonyms_share_issue(api: httpx.Client):
    platform = _unique("grp")
    product = _unique("bag")
    shop = "shop-group"
    rid_a = _unique("r")
    rid_b = _unique("r")
    rows = [
        f"{shop},{product},{rid_a},2026-10-01,2,拉链卡住拉不上了。\n",
        f"{shop},{product},{rid_b},2026-10-02,2,拉链又卡住拉不动。\n",
    ]
    batch_id = _post_batch(api, platform, rows)
    _wait_batch(api, batch_id, expected_rows=2)

    comments = api.get("/comments", params={"product_id": product}, timeout=15)
    assert comments.status_code == 200
    items = comments.json()
    assert len(items) >= 2

    details = [_comment_detail(api, item["id"]) for item in items]
    issue_sets = [_quality_issue_ids(d) for d in details]
    assert all(issue_sets), f"expected quality links, got {details}"
    shared = set.intersection(*issue_sets)
    assert shared, f"synonym reviews should share an issue: {issue_sets}"

    # Linked comments (second+) should carry similarity when AI suggested the link.
    sims = [
        link.get("similarity")
        for detail in details
        for link in detail.get("issues", [])
        if link.get("issue_id") in shared
    ]
    assert any(s is not None and s >= _threshold() for s in sims), sims


def test_hard_negative_and_cross_product_do_not_merge(api: httpx.Client):
    platform = _unique("grpneg")
    product = _unique("bag")
    other_product = _unique("bag-other")
    shop = "shop-group"
    rows = [
        f"{shop},{product},{_unique('r')},2026-10-01,2,拉链卡住拉不上。\n",
        f"{shop},{product},{_unique('r')},2026-10-02,2,掉色很严重和图片不一样。\n",
        f"{shop},{other_product},{_unique('r')},2026-10-03,2,拉链又卡住拉不上。\n",
    ]
    batch_id = _post_batch(api, platform, rows)
    _wait_batch(api, batch_id, expected_rows=3)

    same = api.get("/comments", params={"product_id": product}, timeout=15).json()
    assert len(same) >= 2
    details = [_comment_detail(api, item["id"]) for item in same]
    sets = [_quality_issue_ids(d) for d in details]
    # Zipper vs fade: if both have quality links, they must not be the same issue.
    if all(sets):
        assert set.intersection(*sets) == set(), f"hard negative merged: {sets}"

    other = api.get("/comments", params={"product_id": other_product}, timeout=15).json()
    assert other
    other_detail = _comment_detail(api, other[0]["id"])
    other_issues = _quality_issue_ids(other_detail)
    same_issues = set.union(*sets) if any(sets) else set()
    assert other_issues.isdisjoint(same_issues), (
        f"cross-product merge: {other_issues} vs {same_issues}"
    )
