from __future__ import annotations

from services.ai.app.main import extract_issues
from services.common.schemas import ExtractionRequest


def test_extract_issues_finds_quality_problem_with_evidence():
    result = extract_issues(
        ExtractionRequest(
            comment_id="c-1",
            product_id="bag-1",
            body="拉链拉到一半就卡住，拉不上，只能退货。",
        )
    )

    assert result.has_issue.value == "yes"
    assert result.issues
    quality = [issue for issue in result.issues if issue.category_id == "quality"]
    assert quality, "expected a quality issue"
    assert quality[0].evidence_text in "拉链拉到一半就卡住，拉不上，只能退货。"
    assert result.model_version == "rule-baseline-1"


def test_extract_issues_returns_no_for_positive_comment():
    result = extract_issues(
        ExtractionRequest(comment_id="c-2", product_id="bag-1", body="整体不错，家人很喜欢。")
    )
    assert result.has_issue.value == "no"
    assert result.issues == []


def test_extract_issues_returns_unknown_for_tiny_body():
    result = extract_issues(ExtractionRequest(comment_id="c-3", product_id="bag-1", body="好"))
    assert result.has_issue.value == "unknown"
