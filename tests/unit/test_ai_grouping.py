"""Unit tests for semantic /suggest-groups (no real model download)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.ai.app import grouping
from services.ai.app.grouping import (
    EmbedderUnavailable,
    hashing_embed,
    normalize_grouping_text,
    set_embedder_override,
    suggest_group_assignment,
)
from services.ai.app.main import app
from services.common.config import Settings, get_settings
from services.common.schemas import (
    ExistingIssueRef,
    GroupingAction,
    GroupSuggestionRequest,
)


@pytest.fixture(autouse=True)
def _reset_grouping_hooks():
    set_embedder_override(None)
    grouping.reset_embedder_cache()
    get_settings.cache_clear()
    yield
    set_embedder_override(None)
    grouping.reset_embedder_cache()
    get_settings.cache_clear()


def _fixed_embedder(mapping: dict[str, list[float]]):
    def encode(texts):
        return [list(mapping[text]) for text in texts]

    return encode


def test_suggest_create_new_when_no_candidates():
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1", category_id="quality", candidate_text="拉链卡住",
        ),
        settings=Settings(grouping_embedding_backend="hashing"),
    )
    assert result.action == GroupingAction.CREATE_NEW
    assert result.issue_id is None


def test_suggest_links_high_similarity_with_injected_vectors():
    zipper = ExistingIssueRef(
        id="issue-zipper", title="拉链问题", description="拉链拉不上",
    )
    set_embedder_override(_fixed_embedder({
        "拉链卡住了": [1.0, 0.0],
        "拉链问题 拉链拉不上": [0.99, 0.1],
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链卡住了",
            existing_issues=[zipper],
        ),
        settings=Settings(grouping_similarity_threshold=0.75),
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert result.issue_id == "issue-zipper"
    assert result.similarity is not None and result.similarity >= 0.75


def test_suggest_create_new_for_different_specific_issue():
    zipper = ExistingIssueRef(
        id="issue-zipper", title="拉链问题", description="拉链拉不上",
    )
    set_embedder_override(_fixed_embedder({
        "掉色严重": [0.0, 1.0],
        "拉链问题 拉链拉不上": [1.0, 0.0],
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="掉色严重",
            existing_issues=[zipper],
        ),
        settings=Settings(grouping_similarity_threshold=0.75),
    )
    assert result.action == GroupingAction.CREATE_NEW
    assert result.similarity is not None and result.similarity < 0.75


def test_hashing_embedder_prefers_same_topic():
    zipper = ExistingIssueRef(
        id="issue-zipper", title="质量相关问题", description="拉链拉不上卡住",
    )
    fade = ExistingIssueRef(
        id="issue-fade", title="质量相关问题", description="掉色严重和描述不符",
    )
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链卡住拉不上",
            existing_issues=[fade, zipper],
        ),
        settings=Settings(
            grouping_embedding_backend="hashing",
            grouping_similarity_threshold=0.35,
        ),
        embedder=hashing_embed,
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert result.issue_id == "issue-zipper"


def test_embedder_none_raises():
    with pytest.raises(EmbedderUnavailable):
        suggest_group_assignment(
            GroupSuggestionRequest(
                product_id="bag-1",
                category_id="quality",
                candidate_text="拉链卡住",
                existing_issues=[
                    ExistingIssueRef(id="i1", title="t", description="拉链"),
                ],
            ),
            settings=Settings(grouping_embedding_backend="none"),
        )


def test_http_suggest_groups_endpoint_and_disabled():
    client = TestClient(app)
    ok = client.post(
        "/suggest-groups",
        json={
            "product_id": "bag-1",
            "category_id": "quality",
            "candidate_text": "拉链卡住",
            "existing_issues": [],
        },
    )
    assert ok.status_code == 200
    assert ok.json()["action"] == "create_new"

    get_settings.cache_clear()
    monkey_settings = Settings(grouping_enabled=False)
    import services.ai.app.main as ai_main

    original = ai_main.get_settings
    ai_main.get_settings = lambda: monkey_settings
    try:
        disabled = client.post(
            "/suggest-groups",
            json={
                "product_id": "bag-1",
                "category_id": "quality",
                "candidate_text": "拉链卡住",
            },
        )
        assert disabled.status_code == 503
    finally:
        ai_main.get_settings = original
        get_settings.cache_clear()


def test_legacy_existing_issue_ids_merged_into_refs():
    req = GroupSuggestionRequest(
        product_id="bag-1",
        category_id="quality",
        candidate_text="拉链",
        existing_issue_ids=["a", "b"],
    )
    assert [item.id for item in req.existing_issues] == ["a", "b"]


def test_keyword_gate_blocks_hard_negative_just_above_threshold():
    """Shared hub token alone must not merge stuck vs paint near T_main."""
    paint = ExistingIssueRef(
        id="issue-paint", title="拉链掉漆", description="拉链油漆脱落",
    )
    set_embedder_override(_fixed_embedder({
        "拉链卡住": [1.0, 0.0],
        "拉链掉漆 拉链油漆脱落": [0.55, 0.835],  # cos ≈ 0.55
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链卡住",
            existing_issues=[paint],
        ),
        settings=Settings(
            grouping_similarity_threshold=0.50,
            grouping_keyword_gate=True,
            grouping_overlap_threshold=0.75,
        ),
    )
    assert result.action == GroupingAction.CREATE_NEW
    assert "keyword gate" in (result.rationale or "").lower()


def test_keyword_gate_allows_with_substantive_overlap():
    stuck = ExistingIssueRef(
        id="issue-stuck", title="拉链卡住", description="拉链卡住拉不上",
    )
    set_embedder_override(_fixed_embedder({
        "拉链卡住拉不上": [1.0, 0.0],
        "拉链卡住 拉链卡住拉不上": [0.6, 0.8],  # cos = 0.6
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链卡住拉不上",
            existing_issues=[stuck],
        ),
        settings=Settings(
            grouping_similarity_threshold=0.50,
            grouping_keyword_gate=True,
            grouping_overlap_threshold=0.75,
        ),
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert result.issue_id == "issue-stuck"


def test_keyword_gate_high_confidence_bypass_without_overlap():
    paint = ExistingIssueRef(
        id="issue-paint", title="拉链掉漆", description="油漆脱落",
    )
    set_embedder_override(_fixed_embedder({
        "拉链卡住": [1.0, 0.0],
        "拉链掉漆 油漆脱落": [0.98, 0.199],  # cos ≈ 0.98 >= T_overlap
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链卡住",
            existing_issues=[paint],
        ),
        settings=Settings(
            grouping_similarity_threshold=0.50,
            grouping_keyword_gate=True,
            grouping_overlap_threshold=0.75,
        ),
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert "t_high" in (result.rationale or "").lower()


def test_normalize_is_language_general_only():
    assert normalize_grouping_text("  Zipper!!  ") == "zipper"
    assert "卡死" in normalize_grouping_text("拉链卡死拉不上")
    # No vertical synonym rewrite (油漆脱落 must not become 掉漆).
    assert "油漆脱落" in normalize_grouping_text("拉链油漆脱落")
    assert normalize_grouping_text("全角　空白，标点。") == "全角 空白,标点."
    assert normalize_grouping_text("质量相关问题：拉链卡住") == "拉链卡住"
    assert normalize_grouping_text("Quality issue: zipper stuck") == "zipper stuck"


def test_top2_margin_blocks_ambiguous_best():
    stuck = ExistingIssueRef(id="issue-stuck", title="卡住", description="拉链卡住")
    seam = ExistingIssueRef(id="issue-seam", title="卡顿", description="拉链卡住不顺畅")
    set_embedder_override(_fixed_embedder({
        "拉链又卡住": [1.0, 0.0],
        "卡住 拉链卡住": [0.92, 0.1],   # cos ≈ 0.994
        "卡顿 拉链卡住不顺畅": [0.90, 0.2],   # cos ≈ 0.976; delta ≈ 0.018
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链又卡住",
            existing_issues=[stuck, seam],
        ),
        settings=Settings(
            grouping_similarity_threshold=0.50,
            grouping_overlap_threshold=0.75,
            grouping_top2_margin=0.08,
            grouping_keyword_gate=True,
        ),
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert result.requires_review
    assert "top2 margin" in (result.rationale or "").lower()


def test_top2_margin_allows_clear_winner():
    stuck = ExistingIssueRef(id="issue-stuck", title="卡住", description="拉链卡住")
    seam = ExistingIssueRef(id="issue-seam", title="开线", description="侧边开线")
    set_embedder_override(_fixed_embedder({
        "拉链又卡住": [1.0, 0.0],
        "卡住 拉链卡住": [0.95, 0.05],  # high
        "开线 侧边开线": [0.2, 0.98],   # low; large margin
    }))
    result = suggest_group_assignment(
        GroupSuggestionRequest(
            product_id="bag-1",
            category_id="quality",
            candidate_text="拉链又卡住",
            existing_issues=[stuck, seam],
        ),
        settings=Settings(
            grouping_similarity_threshold=0.50,
            grouping_overlap_threshold=0.75,
            grouping_top2_margin=0.08,
            grouping_keyword_gate=True,
        ),
    )
    assert result.action == GroupingAction.LINK_EXISTING
    assert result.issue_id == "issue-stuck"
