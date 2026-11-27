# ADR 003: Separate model extraction, semantic grouping and human review

## Status

Accepted. This record documents an implemented decision.
Recorded on 2026-11-27.

## Context

Reviews contain varied Chinese and English wording. The system needs to extract concrete
problems, relate similar complaints and show why a review belongs to a group.
Provider failures and incorrect model judgments must remain visible and correctable.

## Decision

Use a configurable OpenAI-compatible provider for structured issue extraction.
Keep the extraction model and endpoint configurable rather than hard-coding a provider.
The default configuration uses heuristic extraction; a live provider must be configured explicitly.

Use the local `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` model for semantic
grouping within a batch, platform, store, product and category. This separates language extraction
from similarity matching and avoids another hosted request for the grouping step.

Validate output structure and locate quoted evidence in the original review before saving links.
Record model/prompt versions, source and fallback information.
Configured extraction failures receive bounded retries before rule fallback.
Uncertain or fallback associations remain pending; automatic acceptance requires additional
evidence and consistency checks. Human decisions and issue follow-up have separate persisted state.

## Alternatives considered

- **Rules only:** easy to run without provider credentials, but limited vocabulary and context
  handling can miss complaints or flag positive reviews.
- **Hosted LLM for both extraction and every grouping decision:** flexible, but increases
  provider dependency, latency and potential cost.
- **A full local generative model:** avoids external extraction calls, but adds deployment,
  resource and model-evaluation requirements beyond the current local setup.
- **Automatically accept all model results:** reduces review work but can persist unsupported
  judgments without meaningful human control.

## Consequences

- Provider choice can change through configuration while the application keeps its output contract.
- Local multilingual embeddings support cross-language similarity matching without an additional
  provider key for grouping, but require model downloads and runtime memory.
- Evidence and provenance make results inspectable; quotation matching does not prove semantic correctness.
- External extraction introduces network, cost and review-text privacy considerations.
- Rules are a degraded fallback, not equivalent model quality. Chinese positive-review false
  positives remain a known limitation.
- Thresholds are operational rules, not calibrated accuracy guarantees. Representative labelled
  evaluation is still required; extraction currently permits at most one issue per category per review.

## 中文摘要

将外部模型提取、本地多语言 MiniLM 归组及人工复核分开。
提取使用可配置的 OpenAI-compatible 接口，归组使用本地语义模型，结果保存前校验结构及原文证据，
并记录来源、版本和回退信息。不确定结果及规则回退保持待确认，人工决定单独保存。
该方案兼顾配置灵活性、证据可追溯和人工纠正，但仍有模型下载、外部调用成本、隐私及误判问题；
关键词回退和阈值不能替代质量评测。

## References

- [LLM adapter](../../services/ai/app/llm.py)
- [Extraction and fallback](../../services/ai/app/main.py)
- [Semantic grouping](../../services/ai/app/grouping.py)
- [Evidence validation](../../services/worker/app/analysis.py)
- [Human review](../human-review.md)

