"""Build grouping eval pairs from real /extract-issues LLM descriptions.

Requires LLM_PROVIDER=openai_compatible and a working course API key.
Does not fall back to handwritten pairs or heuristic descriptions.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from collections import defaultdict
from pathlib import Path

from services.ai.app.llm import LlmError, call_llm_extraction
from services.common.config import Settings, get_settings
from services.common.schemas import ExtractionRequest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REVIEWS = ROOT / "data" / "grouping_eval" / "raw_reviews.jsonl"
DEFAULT_OUT = ROOT / "data" / "grouping_eval" / "pairs_llm.jsonl"
DEFAULT_CACHE = ROOT / "data" / "grouping_eval" / "llm_extractions.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_all(
    reviews: list[dict],
    settings: Settings,
    *,
    cache_path: Path,
    sleep_s: float,
) -> list[dict]:
    cache: dict[str, dict] = {}
    if cache_path.exists():
        for row in load_jsonl(cache_path):
            cache[row["review_id"]] = row

    results: list[dict] = []
    for index, review in enumerate(reviews, start=1):
        review_id = review["review_id"]
        if review_id in cache and cache[review_id].get("ok"):
            results.append(cache[review_id])
            print(f"[{index}/{len(reviews)}] cache hit {review_id}")
            continue

        payload = ExtractionRequest(
            comment_id=review_id,
            product_id=review["product_id"],
            body=review["body"],
        )
        extracted = None
        last_error = ""
        for attempt in range(1, 4):
            try:
                extracted = call_llm_extraction(payload, settings)
                break
            except LlmError as exc:
                last_error = str(exc)
                # Auth / config failures must stop; schema glitches can retry/skip.
                if last_error in {"no_api_key", "missing_model_config", "auth_error"}:
                    raise SystemExit(
                        f"LLM extraction failed for {review_id}: {exc}. "
                        "Refusing to invent pairs from handwritten/heuristic text."
                    ) from exc
                print(f"[{index}/{len(reviews)}] {review_id} attempt {attempt} → {exc}")
                if sleep_s > 0:
                    time.sleep(sleep_s * attempt)

        if extracted is None:
            row = {
                "review_id": review_id,
                "product_id": review["product_id"],
                "cluster_id": review["cluster_id"],
                "expected_category": review.get("expected_category"),
                "body": review["body"],
                "has_issue": "error",
                "issues": [],
                "model_version": settings.llm_model,
                "prompt_version": settings.llm_prompt_version,
                "ok": False,
                "error": last_error,
            }
        else:
            issues = [
                {
                    "category_id": issue.category_id,
                    "description": issue.description,
                    "evidence_text": issue.evidence_text,
                }
                for issue in extracted.issues
            ]
            row = {
                "review_id": review_id,
                "product_id": review["product_id"],
                "cluster_id": review["cluster_id"],
                "expected_category": review.get("expected_category"),
                "body": review["body"],
                "has_issue": extracted.has_issue.value,
                "issues": issues,
                "model_version": extracted.model_version,
                "prompt_version": extracted.prompt_version,
                "ok": extracted.has_issue.value == "yes" and bool(issues),
            }
        cache[review_id] = row
        results.append(row)
        write_jsonl(cache_path, list(cache.values()))
        print(
            f"[{index}/{len(reviews)}] {review_id} has_issue={row['has_issue']} "
            f"issues={len(row.get('issues') or [])} ok={row['ok']}"
        )
        if sleep_s > 0:
            time.sleep(sleep_s)

    return results


def _issue_for_expected(row: dict) -> dict | None:
    expected = row.get("expected_category")
    issues = row.get("issues") or []
    if expected:
        for issue in issues:
            if issue["category_id"] == expected:
                return issue
    return issues[0] if issues else None


def build_pairs(
    extractions: list[dict],
    *,
    reviewed_by: str,
    auto_review: bool,
) -> list[dict]:
    """Pair LLM descriptions within product+category using source cluster labels."""
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    skipped = 0
    for row in extractions:
        if not row.get("ok"):
            skipped += 1
            continue
        issue = _issue_for_expected(row)
        if issue is None:
            skipped += 1
            continue
        key = (row["product_id"], issue["category_id"])
        buckets[key].append({
            "review_id": row["review_id"],
            "cluster_id": row["cluster_id"],
            "description": issue["description"],
            "category_id": issue["category_id"],
            "product_id": row["product_id"],
            "model_version": row.get("model_version"),
        })

    pairs: list[dict] = []
    pair_n = 0
    for (product_id, category_id), items in sorted(buckets.items()):
        # Positive: same cluster (cap per cluster).
        by_cluster: dict[str, list[dict]] = defaultdict(list)
        for item in items:
            by_cluster[item["cluster_id"]].append(item)
        for cluster_id, members in by_cluster.items():
            for left, right in itertools.combinations(members, 2):
                pair_n += 1
                pairs.append(_pair_row(
                    pair_n, left, right, same=True, reviewed_by=reviewed_by,
                    auto_review=auto_review, notes=f"same cluster {cluster_id}",
                ))

        # Negatives: different clusters, prefer hard pairs in same category.
        clusters = list(by_cluster.keys())
        for i, c_a in enumerate(clusters):
            for c_b in clusters[i + 1 :]:
                for left, right in itertools.product(by_cluster[c_a][:2], by_cluster[c_b][:2]):
                    pair_n += 1
                    pairs.append(_pair_row(
                        pair_n, left, right, same=False, reviewed_by=reviewed_by,
                        auto_review=auto_review,
                        notes=f"hard neg {c_a} vs {c_b}",
                    ))

    print(f"skipped_reviews={skipped} pairs={len(pairs)} buckets={len(buckets)}")
    return pairs


def _pair_row(
    pair_n: int,
    left: dict,
    right: dict,
    *,
    same: bool,
    reviewed_by: str,
    auto_review: bool,
    notes: str,
) -> dict:
    return {
        "pair_id": f"llm{pair_n:03d}",
        "product_id": left["product_id"],
        "category_id": left["category_id"],
        "text_a": left["description"],
        "text_b": right["description"],
        "same_group": same,
        "notes": notes,
        "source": "llm",
        "model": left.get("model_version"),
        "review_ids": [left["review_id"], right["review_id"]],
        "cluster_ids": [left["cluster_id"], right["cluster_id"]],
        "review_status": "reviewed" if auto_review else "pending",
        "reviewed_by": reviewed_by if auto_review else None,
        "label_method": "cluster_from_source_review" if auto_review else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument(
        "--auto-review",
        action="store_true",
        help="Mark pairs reviewed using source-review cluster_id labels",
    )
    parser.add_argument("--reviewed-by", default="mike")
    args = parser.parse_args()

    get_settings.cache_clear()
    settings = get_settings()
    if settings.llm_provider != "openai_compatible":
        raise SystemExit(
            f"Need LLM_PROVIDER=openai_compatible, got {settings.llm_provider}. "
            "Will not build pairs_llm from heuristic output."
        )
    if not settings.llm_api_key or not settings.llm_base_url or not settings.llm_model:
        raise SystemExit("Missing LLM_API_KEY / LLM_BASE_URL / LLM_MODEL")

    reviews = load_jsonl(args.reviews)
    print(f"reviews={len(reviews)} model={settings.llm_model}")
    extractions = extract_all(
        reviews, settings, cache_path=args.cache, sleep_s=args.sleep,
    )
    pairs = build_pairs(
        extractions, reviewed_by=args.reviewed_by, auto_review=args.auto_review,
    )
    write_jsonl(args.out, pairs)
    print(f"wrote {args.out} ({len(pairs)} pairs)")


if __name__ == "__main__":
    main()
