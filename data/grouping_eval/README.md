# Grouping evaluation pairs

## Primary set (lock thresholds here)

- `pairs_llm.jsonl` — issue **descriptions from the real course `/extract-issues` LLM**
- Built from `raw_reviews.jsonl` via `scripts/build_grouping_pairs_from_llm.py`
- Labels: same source `cluster_id` within product + category → `same_group=true` (with light manual relabel for color-vs-spec mismatches)
- Fields include `source=llm`, `model`, `review_ids`, `cluster_ids`

## Smoke / regression only

- `pairs.jsonl` — handwritten short problem phrases (~106 reviewed)
- Useful for quick checks; **do not** treat its accuracy as online grouping quality

## Score thresholds

Deliverable lock uses MiniLM on the LLM set:

```powershell
python -m scripts.eval_grouping --backend sentence_transformers --pairs data/grouping_eval/pairs_llm.jsonl --dump-errors
```

Offline draft (no model download):

```powershell
python -m scripts.eval_grouping --backend hashing --pairs data/grouping_eval/pairs_llm.jsonl
```

Rebuild LLM pairs (requires `LLM_PROVIDER=openai_compatible` and API key; no heuristic fallback):

```powershell
python -m scripts.build_grouping_pairs_from_llm --auto-review
```

Record **T_main / T_overlap / top2_margin**, backend, model, and metrics in `EVAL_NOTES.md`.
