"""Internal AI service: rule-baseline issue extraction (R3 starter).

The contract is frozen in ``services/common/schemas.py`` (``ExtractionResult``):
the service only proposes issues + evidence; the Worker validates evidence
against the comment body and writes all database state.  R3 replaces the rule
baseline with an LLM behind the same interface.
"""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from services.common.categories import CATEGORY_VERSION, CATEGORIES
from services.common.config import configure_logging
from services.common.schemas import (
    ExtractedIssue,
    ExtractionRequest,
    ExtractionResult,
    GroupSuggestionRequest,
    GroupSuggestionResult,
    HealthResponse,
    GroupingAction,
)

configure_logging()
logger = logging.getLogger("services.ai.main")

app = FastAPI(title="Review Management AI Service (rule baseline)", version="0.2.0")

EXTRACTION_REQUESTS = Counter(
    "ai_extraction_requests_total", "Total extraction requests", ["has_issue"]
)
EXTRACTION_LATENCY = Histogram("ai_extraction_duration_seconds", "Extraction duration in seconds")

MODEL_VERSION = "rule-baseline-1"
PROMPT_VERSION = "v1"

# Keywords per category; the first match in the body becomes the evidence.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "quality": ("拉链", "开线", "掉色", "破", "坏", "卡住", "拉不上", "做工", "质量", "断裂"),
    "logistics": ("物流", "快递", "发货", "包裹", "配送", "到货", "慢"),
    "mismatch": ("色差", "不符", "描述", "尺寸", "大小", "图片", "实物"),
    "usability": ("使用", "体验", "功能", "容量", "肩带", "舒适", "太重", "装不下"),
}

SENTENCE_BREAKS = "。！？；!?;\n"


def _find_evidence(body: str, keyword: str) -> str | None:
    """Return a sentence (or a bounded snippet) that contains ``keyword``."""
    index = body.find(keyword)
    if index < 0:
        return None
    start = index
    while start > 0 and body[start - 1] not in SENTENCE_BREAKS:
        start -= 1
    end = index + len(keyword)
    while end < len(body) and body[end] not in SENTENCE_BREAKS:
        end += 1
    evidence = body[start:end].strip()
    return evidence or None


def extract_issues(payload: ExtractionRequest) -> ExtractionResult:
    body = payload.body
    issues: list[ExtractedIssue] = []
    used_categories: set[str] = set()

    for category_id, keywords in KEYWORDS.items():
        if category_id in used_categories:
            continue
        for keyword in keywords:
            evidence = _find_evidence(body, keyword)
            if evidence is None:
                continue
            issues.append(
                ExtractedIssue(
                    category_id=category_id,
                    description=f"{CATEGORIES[category_id].name}相关问题：{evidence[:80]}",
                    evidence_text=evidence[:500],
                )
            )
            used_categories.add(category_id)
            break

    if issues:
        has_issue = "yes"
    elif len(body.strip()) < 4:
        has_issue = "unknown"
    else:
        has_issue = "no"

    return ExtractionResult(
        comment_id=payload.comment_id,
        has_issue=has_issue,  # type: ignore[arg-type]
        issues=issues,
        model_version=MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
        category_version=CATEGORY_VERSION,
    )


@app.get("/", response_model=HealthResponse)
def root() -> HealthResponse:
    return HealthResponse(service="ai", status="ok")


@app.get("/health/live", response_model=HealthResponse)
def health_live() -> HealthResponse:
    return HealthResponse(service="ai", status="ok")


@app.get("/health/ready", response_model=HealthResponse)
def health_ready() -> HealthResponse:
    return HealthResponse(service="ai", status="ok")


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/extract-issues", response_model=ExtractionResult)
def extract(payload: ExtractionRequest) -> ExtractionResult:
    start = perf_counter()
    result = extract_issues(payload)
    EXTRACTION_REQUESTS.labels(result.has_issue.value).inc()
    EXTRACTION_LATENCY.observe(perf_counter() - start)
    logger.info(
        "extraction_completed",
        extra={
            "comment_id": payload.comment_id,
            "has_issue": result.has_issue.value,
            "issue_count": len(result.issues),
        },
    )
    return result


@app.post("/suggest-groups", response_model=GroupSuggestionResult)
def suggest_groups(payload: GroupSuggestionRequest) -> GroupSuggestionResult:
    """Baseline grouping hint: link the first existing issue, else create new."""
    if payload.existing_issue_ids:
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=payload.existing_issue_ids[0],
            similar_issue_ids=payload.existing_issue_ids[:3],
            similarity=0.5,
            rationale="rule baseline: reuse the first issue of the same category",
        )
    return GroupSuggestionResult(
        action=GroupingAction.CREATE_NEW,
        rationale="rule baseline: no existing issue in this category",
    )
