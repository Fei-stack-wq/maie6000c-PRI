import pytest

from services.ai.app.main import extract_issues
from services.common.schemas import ExtractionRequest


def analyse(body):
    return extract_issues(ExtractionRequest(comment_id="english-test", product_id="bag", body=body))


@pytest.mark.parametrize("body,category", [
    ("The zipper gets stuck halfway.", "quality"),
    ("THE ZIPPER IS BROKEN!", "quality"),
    ("The strap broke after one day.", "quality"),
    ("It doesn’t work.", "quality"),
    ("Poor quality. The bag fell apart.", "quality"),
    ("The delivery was very late.", "logistics"),
    ("Slow shipping.", "logistics"),
    ("The package never arrived.", "logistics"),
    ("The color is different from the picture.", "mismatch"),
    ("They sent the wrong size.", "mismatch"),
    ("It is not as described.", "mismatch"),
    ("The colour doesn’t match the photo.", "mismatch"),
    ("The straps are uncomfortable.", "usability"),
    ("It is too heavy to carry.", "usability"),
    ("There is not enough space.", "usability"),
    ("It is not comfortable.", "usability"),
])
def test_english_problem_categories_and_verbatim_evidence(body, category):
    result = analyse(body)
    assert result.has_issue.value == "yes"
    issue = next(item for item in result.issues if item.category_id == category)
    assert issue.evidence_text in body
    assert issue.description.startswith(("Quality", "Logistics", "Description", "Usability"))
    assert result.model_version == "rule-baseline-2"


@pytest.mark.parametrize("body", [
    "The zipper works well.", "Great backpack, I love it.", "No problems with this bag.",
    "The zipper is not broken.", "The zipper does not get stuck.",
    "The straps are not uncomfortable.", "It arrived on time.",
])
def test_english_positive_and_negated_complaints(body):
    result = analyse(body)
    assert result.has_issue.value == "no"
    assert not result.issues


@pytest.mark.parametrize("body", [
    "The zipper.", "I am not sure about this bag.", "The bag arrived yesterday.",
    "An unbroken line of stitching.", "Good bag, but it smells strange.",
    "The zipper is not very good.", "Delivery was not late.",
    "The zipper is not loose.", "It is not a good bag.",
])
def test_unmatched_or_ambiguous_english_is_unknown(body):
    result = analyse(body)
    assert result.has_issue.value == "unknown"
    assert not result.issues


def test_mixed_review_and_contrast_preserve_all_problem_categories():
    body = ("很喜欢。The zipper is not broken, but the delivery was late. "
            "The straps are uncomfortable.")
    result = analyse(body)
    assert result.has_issue.value == "yes"
    # The Chinese fragment contains none of the existing category keywords.
    assert {i.category_id for i in result.issues} == {"logistics", "usability"}
    assert all(i.evidence_text in body for i in result.issues)


def test_positive_clause_does_not_hide_later_quality_problem():
    result = analyse("No problems initially, but now the zipper is broken.")
    assert result.has_issue.value == "yes"
    assert result.issues[0].category_id == "quality"


def test_english_periods_and_original_case_are_preserved():
    body = "The colour is great. The ZIPPER gets stuck halfway. Delivery was on time."
    result = analyse(body)
    quality = next(i for i in result.issues if i.category_id == "quality")
    assert quality.evidence_text == "The ZIPPER gets stuck halfway"


def test_long_evidence_still_contains_the_matched_problem():
    body = "Nice " * 150 + "the zipper is broken at the end."
    result = analyse(body)
    issue = result.issues[0]
    assert len(issue.evidence_text) <= 500
    assert "broken" in issue.evidence_text and issue.evidence_text in body
