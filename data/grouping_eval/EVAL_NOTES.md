# Grouping eval notes (threshold lock)

- Script: `python -m scripts.eval_grouping --backend sentence_transformers`
- **Calibration set:** `pairs_calib.jsonl` (n=91) — used only for threshold / grid search
- **Held-out test set:** `pairs_test.jsonl` (n=39) — final reported accuracy only
- Full LLM pool (legacy): `pairs_llm.jsonl` (n=130) = calib ∪ test (kept for reproducibility)
- Handwritten `pairs.jsonl`: **dev smoke / regression only** — not the deliverable lock
- Date: 2026-11-22 (T_high gate naming; **no synonym/alias cheat-sheet**; calib/test split)
- Backend: `sentence_transformers`
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Keyword gate: **on** (substantive token overlap only; hubs/stopwords stripped)
- Selection rule on **calib**: highest accuracy → higher F1 → higher precision
- **Locked: T_main = 0.35, T_high = 0.55 (`GROUPING_OVERLAP_THRESHOLD`), top2_margin = 0.08**

## Gate policy

- `score < T_main` → create_new
- `T_main <= score < T_high` → link only with substantive token overlap
- `score >= T_high` → link even without overlap (strong-confidence bypass)
- Env name `GROUPING_OVERLAP_THRESHOLD` still maps to **T_high**
- **No hand-authored synonym / alias clusters** (rejected as dataset-specific overfitting)

## How `pairs_llm.jsonl` was built

1. Multi-category reviews in `raw_reviews.jsonl` (100 source reviews; bag / phone / kettle / shirt / earbud / lamp).
2. `python -m scripts.build_grouping_pairs_from_llm --auto-review` against the course API (`gemini-2.5-flash-lite`).
3. Labels follow source-review `cluster_id` within product + extracted category; 2 pairs relabeled when descriptions were color-vs-spec mismatches.
4. Extraction cache: `llm_extractions.jsonl`. Some reviews skipped on `duplicate_category` / unknown / timeout.
5. Split (seed `20261122`, stratified by `same_group`, ~70/30): `pairs_calib.jsonl` / `pairs_test.jsonl`.

## Calibration lock (n=91, no aliases)

| Setup | T_main | T_high | top2 | accuracy | precision | recall | f1 | fp | fn | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Locked (MiniLM, no aliases)** | **0.35** | **0.55** | **0.08** | **0.8352** | 0.8163 | 0.8696 | **0.8421** | 9 | 6 | **15** |
| Stricter T_high | 0.35 | 0.60 | 0.08 | 0.7912 | 0.8140 | 0.7609 | 0.7865 | 8 | 11 | 19 |

## Held-out test report (n=39) — scored once after lock

```powershell
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs_test.jsonl --fixed-t-main 0.35 --fixed-t-overlap 0.55 --fixed-top2-margin 0.08
```

| Setup | T_main | T_high | top2 | accuracy | precision | recall | f1 | fp | fn | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **Current (no aliases)** | **0.35** | **0.55** | **0.08** | **0.7692** | 0.8235 | 0.7000 | 0.7568 | 3 | 6 | 9 |

A short-lived alias-cluster experiment raised test ≈0.85 but was **removed** as a dataset-specific cheat-sheet.

## Historical full-pool lock (n=130, pre-split)

| Setup | T_main | T_overlap | top2 | accuracy | precision | recall | f1 | fp | fn | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Locked (expanded + cleaned) | 0.35 | 0.55 | 0.08 | 0.8154 | 0.8182 | 0.8182 | 0.8182 | 12 | 12 | 24 |

**Product note:** `/suggest-groups` remains a **hint** for staff review. Runtime still does **not** call the course LLM to decide same-group (repo design).

## Second-annotator spot-check

- Sample: `spotcheck_annotator2.jsonl` (20 pairs from `pairs_test.jsonl`, seed `20261122`)
- Status: sample prepared; **agree rate pending team fill-in**

## Commands

```powershell
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs_calib.jsonl
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs_test.jsonl --fixed-t-main 0.35 --fixed-t-overlap 0.55 --fixed-top2-margin 0.08
.\scripts\test_grouping_e2e.ps1 -SkipUp
```

Do not treat pytest green alone as analysis accuracy.
