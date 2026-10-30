import pytest

from services.ai.app.main import extract_issues
from services.common.schemas import ExtractionRequest


def analyse(body):
    request = ExtractionRequest(comment_id="delivery-test", product_id="bag", body=body)
    return extract_issues(request)


@pytest.mark.parametrize("body", [
    "The delivery is taking too long.",
    "The delivery is taking WAY TOO LONG!",
    "Shipping takes forever.",
    "My order took ages.",
    "The package has taken far too long.",
    "It took too long to arrive.",
    "Delivery took longer than promised.",
    "Shipping is slower than expected.",
    "The parcel arrived much later than promised.",
    "My order is overdue.",
    "I haven't received my order.",
    "I haven’t received it yet.",
    "I have not received the package.",
    "I did not receive my parcel.",
    "I didn't get my package.",
    "I never got my order.",
    "The package still hasn't arrived.",
    "It has not arrived yet.",
    "It didn't arrive.",
    "My order has not been delivered yet.",
    "The parcel has still not shown up.",
    "The courier hasn't delivered my order.",
    "I have yet to receive my order.",
    "Still waiting for delivery.",
    "I've been waiting for my parcel for weeks.",
])
def test_common_english_delivery_complaints(body):
    result = analyse(body)
    assert result.has_issue.value == "yes"
    logistics = next(item for item in result.issues if item.category_id == "logistics")
    assert logistics.evidence_text in body


@pytest.mark.parametrize("body", [
    "The delivery is not taking too long.",
    "Delivery did not take too long.",
    "Shipping hasn't taken too long.",
    "The package didn't arrive late.",
    "The package has not arrived damaged.",
    "I have not received a damaged item.",
    "Delivery is not slower than expected.",
    "Delivery is taking no longer than expected.",
    "I am waiting for delivery tomorrow.",
    "The delivery takes three days.",
    "The delivery is on time.",
    "Fast delivery, everything works well.",
])
def test_normal_or_negated_delivery_is_not_a_problem(body):
    result = analyse(body)
    assert not result.issues
    assert result.has_issue.value in ("no", "unknown")


def test_one_negated_clause_does_not_hide_the_actual_delay():
    body = "The delivery was not late last time, but this order is taking too long."
    result = analyse(body)
    assert {item.category_id for item in result.issues} == {"logistics"}
    assert result.issues[0].evidence_text in body


def test_delayed_delivery_and_broken_product_are_both_kept():
    result = analyse("I haven't received my order. The previous bag had a broken zipper.")
    assert {item.category_id for item in result.issues} == {"logistics", "quality"}
