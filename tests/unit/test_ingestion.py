from __future__ import annotations

from services.api.app.ingestion import parse_csv

CSV_HEADER = "shop_id,product_id,source_review_id,review_date,rating,body\n"


def test_parse_csv_builds_normalized_comments():
    text = CSV_HEADER + (
        "shop-1,bag-1,r-001,2026-10-01,5,拉链很好用，容量也够。\n"
        "shop-1,bag-1,r-002,2026-10-02,2,拉链卡住了。\n"
    )
    result = parse_csv(text, "demo")

    assert not result.fatal
    assert result.declared_rows == 2
    assert len(result.comments) == 2
    assert result.comments[0].source_review_id == "r-001"
    assert result.comments[0].dedupe_mode == "source_id"
    assert result.comments[0].content_hash


def test_parse_csv_synthesises_source_id_when_missing():
    text = CSV_HEADER + "shop-1,bag-1,,2026-10-01,5,肩带有点窄。\n"
    result = parse_csv(text, "demo")

    assert not result.fatal
    comment = result.comments[0]
    assert comment.source_review_id.startswith("synth:")
    assert comment.dedupe_mode == "content_hash"


def test_parse_csv_reports_row_errors_and_keeps_valid_rows():
    text = CSV_HEADER + (
        "shop-1,bag-1,r-001,2026-10-01,5,正常评论。\n"
        ",bag-1,r-002,2026-10-02,5,缺少店铺。\n"
        "shop-1,bag-1,r-003,not-a-date,9,评分和日期都不对。\n"
    )
    result = parse_csv(text, "demo")

    assert len(result.comments) == 1
    codes = {error.code for error in result.errors}
    assert {"required", "invalid_date", "invalid_rating"} <= codes
    assert result.comments[0].source_review_id == "r-001"


def test_parse_csv_missing_required_columns_is_fatal():
    result = parse_csv("product_id,body\nbag-1,only two columns\n", "demo")

    assert result.fatal
    assert result.errors[0].code == "missing_columns"
