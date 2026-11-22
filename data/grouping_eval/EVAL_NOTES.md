# Grouping eval notes (threshold lock)

- Script: `python -m scripts.eval_grouping --backend sentence_transformers`
- Primary lock set: **`pairs_llm.jsonl`** (real `/extract-issues` LLM descriptions)
- Handwritten `pairs.jsonl`: **dev smoke / regression only** — not the deliverable lock
- Date: 2026-11-22 (accuracy-oriented retune + top2 margin)
- Backend: `sentence_transformers`
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- Keyword gate: **on**
- Dual thresholds + top2 margin (no vertical synonym dictionary)
- Selection rule: **fewest errors (accuracy)** → higher F1 → higher precision
- **Locked: T_main = 0.35, T_overlap = 0.55, top2_margin = 0.08**

## How `pairs_llm.jsonl` was built

1. Multi-category reviews in `raw_reviews.jsonl` (100 source reviews; bag / phone / kettle / shirt / earbud / lamp).
2. `python -m scripts.build_grouping_pairs_from_llm --auto-review` against the course API (`gemini-2.5-flash-lite`).
3. Labels follow source-review `cluster_id` within product + extracted category; 2 pairs relabeled when descriptions were color-vs-spec mismatches.
4. Extraction cache: `llm_extractions.jsonl`. Some reviews skipped on `duplicate_category` / unknown / timeout.

## Primary lock (LLM descriptions, n=130)

| Setup | T_main | T_overlap | top2 | accuracy | precision | recall | f1 | fp | fn | errors |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prior lock (n=78, no top2) | 0.45 | 0.50 | — | 0.7692 | 0.6316 | 0.8571 | 0.7273 | 14 | 4 | 18 |
| **Locked (expanded + cleaned)** | **0.35** | **0.55** | **0.08** | **0.8154** | **0.8182** | **0.8182** | **0.8182** | 12 | 12 | **24** |
| Nearby (safer T_main) | 0.45 | 0.55 | 0.08 | 0.8077 | 0.8154 | 0.8030 | 0.8092 | 12 | 13 | 25 |

Accuracy rose **~77% → ~82%** on the real-LLM set after prompt tighten, expanded pairs, label cleanup, and retune. MiniLM-only ceiling on this set did **not** reach 0.85; remaining errors are mostly hard paraphrases (FN) and mid-score hard negatives that clear `T_overlap` (FP).

**Product note:** `/suggest-groups` remains a **hint** for staff review. Extreme confidence still depends on human accept/reject, not embedding alone. Runtime still does **not** call the course LLM to decide same-group (repo design).

## Handwritten smoke control (n=106, not the lock)

Run:

```powershell
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs.jsonl --fixed-t-main 0.35 --fixed-t-overlap 0.55 --fixed-top2-margin 0.08
```

## Commands

```powershell
python -m scripts.build_grouping_pairs_from_llm --auto-review
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs_llm.jsonl --dump-errors
```

Do not treat pytest green alone as analysis accuracy.
