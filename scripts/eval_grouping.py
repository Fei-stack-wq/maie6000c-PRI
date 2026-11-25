"""Score grouping pairs at similarity thresholds (and dual T_main x T_overlap).

Default backend is hashing (no model download) for local/CI draft sweeps.
Deliverable threshold locking uses --backend sentence_transformers (MiniLM).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.ai.app.grouping import (
    hashing_embed,
    normalize_grouping_text,
    reset_embedder_cache,
    resolve_embedder,
    suggest_group_assignment,
)
from services.common.config import Settings
from services.common.schemas import ExistingIssueRef, GroupingAction, GroupSuggestionRequest

ROOT = Path(__file__).resolve().parents[1]
# Default to held-out test for final scoring; use pairs_calib.jsonl for retuning.
DEFAULT_PAIRS = ROOT / "data" / "grouping_eval" / "pairs_test.jsonl"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def load_pairs(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def predict_same(
    text_a: str,
    text_b: str,
    *,
    t_main: float,
    t_overlap: float,
    top2_margin: float,
    backend: str,
    model: str,
    embedder,
) -> tuple[bool, float | None, str | None]:
    settings = Settings(
        grouping_embedding_backend=backend,  # type: ignore[arg-type]
        grouping_embedding_model=model,
        grouping_similarity_threshold=t_main,
        grouping_overlap_threshold=t_overlap,
        grouping_top2_margin=top2_margin,
        grouping_keyword_gate=True,
    )
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="eval",
            category_id="quality",
            candidate_text=text_a,
            existing_issues=[
                ExistingIssueRef(id="ref", title=text_b[:120], description=text_b),
            ],
        ),
        settings=settings,
        embedder=embedder,
    )
    return (
        result.action == GroupingAction.LINK_EXISTING,
        result.similarity,
        result.rationale,
    )


def metrics(
    pairs: list[dict],
    t_main: float,
    t_overlap: float,
    top2_margin: float,
    *,
    backend: str,
    model: str,
    embedder,
) -> dict:
    tp = fp = tn = fn = 0
    for row in pairs:
        pred, _, _ = predict_same(
            row["text_a"],
            row["text_b"],
            t_main=t_main,
            t_overlap=t_overlap,
            top2_margin=top2_margin,
            backend=backend,
            model=model,
            embedder=embedder,
        )
        label = bool(row["same_group"])
        if pred and label:
            tp += 1
        elif pred and not label:
            fp += 1
        elif (not pred) and (not label):
            tn += 1
        else:
            fn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) else 0.0
    )
    accuracy = (tp + tn) / len(pairs) if pairs else 0.0
    return {
        "t_main": t_main,
        "t_overlap": t_overlap,
        "top2_margin": top2_margin,
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
        "errors": fp + fn,
        "n": len(pairs),
    }


def dump_errors(
    pairs: list[dict],
    t_main: float,
    t_overlap: float,
    top2_margin: float,
    *,
    backend: str,
    model: str,
    embedder,
    limit: int,
) -> None:
    printed = 0
    for row in pairs:
        pred, score, rationale = predict_same(
            row["text_a"],
            row["text_b"],
            t_main=t_main,
            t_overlap=t_overlap,
            top2_margin=top2_margin,
            backend=backend,
            model=model,
            embedder=embedder,
        )
        label = bool(row["same_group"])
        if pred == label:
            continue
        kind = "fp" if pred and not label else "fn"
        print(
            json.dumps(
                {
                    "kind": kind,
                    "pair_id": row.get("pair_id"),
                    "score": score,
                    "same_group": label,
                    "pred_link": pred,
                    "text_a": row["text_a"],
                    "text_b": row["text_b"],
                    "norm_a": normalize_grouping_text(row["text_a"]),
                    "norm_b": normalize_grouping_text(row["text_b"]),
                    "rationale": rationale,
                    "notes": row.get("notes"),
                },
                ensure_ascii=False,
            )
        )
        printed += 1
        if printed >= limit:
            break
    print(f"dump_errors_printed={printed}")


def _pick_best(rows: list[dict]) -> dict:
    """Fewest total errors (accuracy); ties → higher F1; then higher precision."""
    best = rows[0]
    for row in rows[1:]:
        if row["accuracy"] > best["accuracy"]:
            best = row
        elif row["accuracy"] == best["accuracy"]:
            if row["f1"] > best["f1"]:
                best = row
            elif row["f1"] == best["f1"] and row["precision"] > best["precision"]:
                best = row
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS)
    parser.add_argument(
        "--backend",
        choices=("hashing", "sentence_transformers"),
        default="hashing",
        help="Embedding backend (deliverable lock uses sentence_transformers)",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--thresholds",
        default="0.35,0.40,0.45,0.50,0.55,0.60",
        help="Comma-separated T_main values",
    )
    parser.add_argument(
        "--overlap-thresholds",
        default="0.45,0.50,0.55,0.60,0.65,0.70,0.75",
        help="Comma-separated T_overlap values for dual-threshold grid",
    )
    parser.add_argument(
        "--top2-margins",
        default="0.08",
        help="Comma-separated top2 margin values (pair eval is single-candidate; "
        "margin still recorded for lock/docs)",
    )
    parser.add_argument(
        "--t-overlap",
        type=float,
        default=None,
        help="Fix T_overlap and only sweep T_main (default: full grid)",
    )
    parser.add_argument(
        "--reviewed-only",
        action="store_true",
        default=True,
        help="Only score pairs with review_status=reviewed (default true)",
    )
    parser.add_argument(
        "--include-unreviewed",
        action="store_true",
        help="Include pairs that are not yet reviewed",
    )
    parser.add_argument(
        "--dump-errors",
        action="store_true",
        help="Print misclassified pairs at the best (or --fixed) thresholds",
    )
    parser.add_argument("--dump-limit", type=int, default=40)
    parser.add_argument("--fixed-t-main", type=float, default=None)
    parser.add_argument("--fixed-t-overlap", type=float, default=None)
    parser.add_argument("--fixed-top2-margin", type=float, default=0.08)
    args = parser.parse_args()

    if not args.pairs.exists():
        raise SystemExit(
            f"pairs file missing: {args.pairs}. "
            "Build LLM pairs with: python -m scripts.build_grouping_pairs_from_llm --auto-review"
        )

    pairs = load_pairs(args.pairs)
    if args.include_unreviewed:
        scored = pairs
    else:
        scored = [row for row in pairs if row.get("review_status") == "reviewed"]
    pending = sum(1 for row in pairs if row.get("review_status") != "reviewed")
    print(f"pairs={len(pairs)} scored={len(scored)} pending_human_review={pending}")
    print(f"backend={args.backend} model={args.model}")

    reset_embedder_cache()
    if args.backend == "hashing":
        embedder = hashing_embed
    else:
        settings = Settings(
            grouping_embedding_backend="sentence_transformers",
            grouping_embedding_model=args.model,
        )
        embedder = resolve_embedder(settings)

    if args.fixed_t_main is not None and args.fixed_t_overlap is not None:
        row = metrics(
            scored,
            args.fixed_t_main,
            args.fixed_t_overlap,
            args.fixed_top2_margin,
            backend=args.backend,
            model=args.model,
            embedder=embedder,
        )
        print(row)
        if args.dump_errors:
            dump_errors(
                scored,
                args.fixed_t_main,
                args.fixed_t_overlap,
                args.fixed_top2_margin,
                backend=args.backend,
                model=args.model,
                embedder=embedder,
                limit=args.dump_limit,
            )
        return

    t_mains = [float(x.strip()) for x in args.thresholds.split(",") if x.strip()]
    if args.t_overlap is not None:
        overlap_values = [args.t_overlap]
    else:
        overlap_values = [
            float(x.strip()) for x in args.overlap_thresholds.split(",") if x.strip()
        ]
    top2_values = [float(x.strip()) for x in args.top2_margins.split(",") if x.strip()]

    results = []
    for t_main in t_mains:
        for t_overlap in overlap_values:
            if t_overlap < t_main:
                continue
            for top2_margin in top2_values:
                row = metrics(
                    scored,
                    t_main,
                    t_overlap,
                    top2_margin,
                    backend=args.backend,
                    model=args.model,
                    embedder=embedder,
                )
                print(row)
                results.append(row)

    if not results:
        raise SystemExit("no threshold combinations evaluated")
    best = _pick_best(results)
    print("best_accuracy_then_f1_precision", best)
    if args.dump_errors:
        dump_errors(
            scored,
            best["t_main"],
            best["t_overlap"],
            best["top2_margin"],
            backend=args.backend,
            model=args.model,
            embedder=embedder,
            limit=args.dump_limit,
        )


if __name__ == "__main__":
    main()
