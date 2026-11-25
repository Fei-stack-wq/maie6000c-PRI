"""Same-product semantic grouping suggestions for /suggest-groups.

Uses local sentence embeddings when available. Tests may inject a fake embedder.
Does not call the course LLM used for /extract-issues.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Sequence
from typing import Protocol

from services.common.config import Settings, get_settings
from services.common.schemas import (
    ExistingIssueRef,
    GroupingAction,
    GroupSuggestionRequest,
    GroupSuggestionResult,
)

logger = logging.getLogger("services.ai.grouping")

EmbedFn = Callable[[Sequence[str]], list[list[float]]]

_override_embedder: EmbedFn | None = None
_cached_st_embedder: EmbedFn | None = None
_st_load_failed = False

# Tokens ignored for the keyword gate (not used as "substantive" overlap).
_STOPWORDS = frozenset({
    "的", "了", "很", "太", "是", "和", "与", "都", "也", "就", "还", "吗", "啊", "呢",
    "吧", "嘛", "着", "过", "在", "有", "没", "不", "又", "更", "比较",
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "and", "or",
    "in", "on", "for", "with", "this", "that", "it", "not", "no", "very", "so",
})
# Shared product/category hubs that alone should not justify a merge.
_WEAK_HUBS = frozenset({
    "拉链", "拉锁", "zipper", "肩带", "背带", "strap", "包裹", "快递", "物流",
    "颜色", "色差", "尺寸", "大小", "质量", "问题", "做工", "面料", "材质",
    "包包", "背包", "商品", "描述", "图片", "实物", "包装", "客服", "bag",
    "quality", "issue", "product", "colour", "color", "size", "delivery",
})

class EmbedderUnavailable(Exception):
    """No embedding backend is configured or loadable."""


class Embedder(Protocol):
    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        ...


def set_embedder_override(embedder: EmbedFn | None) -> None:
    """Test hook: inject fixed vectors without loading a real model."""
    global _override_embedder
    _override_embedder = embedder


def reset_embedder_cache() -> None:
    global _cached_st_embedder, _st_load_failed
    _cached_st_embedder = None
    _st_load_failed = False


def normalize_grouping_text(text: str) -> str:
    """Language-general cleanup for embedding / keyword gate only (no vertical synonyms)."""
    cleaned = text.lower().strip()
    cleaned = cleaned.replace("\u3000", " ").replace("\xa0", " ")
    # Unify common full-width punctuation to half-width / CJK norms.
    cleaned = (
        cleaned.replace("，", ",")
        .replace("。", ".")
        .replace("！", "!")
        .replace("？", "?")
        .replace("；", ";")
        .replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
    )
    # Strip heuristic/LLM category wrappers so they do not fake keyword overlap.
    cleaned = re.sub(r"^[\u4e00-\u9fffA-Za-z ]{1,20}相关问题:\s*", "", cleaned)
    cleaned = re.sub(r"^[a-z ]{1,40} issue:\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"([!?.,;:])\1+", r"\1", cleaned)
    cleaned = re.sub(r"[!?…]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _tokenize_chars(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9]+", text.lower())


def _content_tokens(text: str) -> set[str]:
    """Latin words plus CJK character bigrams (single CJK chars are too weak alone)."""
    tokens: set[str] = set()
    for token in _tokenize_chars(text):
        if token in _STOPWORDS:
            continue
        if token.isascii() and token.isalpha() and len(token) == 1:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            # Whole CJK run from the regex is one char; rebuild bigrams below.
            continue
        tokens.add(token)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text.lower())
    for index in range(len(cjk_chars) - 1):
        tokens.add(cjk_chars[index] + cjk_chars[index + 1])
    return tokens


def _substantive_tokens(text: str) -> set[str]:
    return {token for token in _content_tokens(text) if token not in _WEAK_HUBS}


def _issue_compare_text(issue: ExistingIssueRef) -> str:
    return f"{issue.title} {issue.description}".strip() or issue.id


def _keyword_overlap(candidate: str, issue_text: str) -> list[str]:
    """Substantive shared tokens (stopwords + weak hubs removed). No synonym cheat-sheet."""
    return sorted(_substantive_tokens(candidate) & _substantive_tokens(issue_text))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def hashing_embed(texts: Sequence[str], dims: int = 256) -> list[list[float]]:
    """Offline char n-gram hashing embedder (no downloads). For tests / auto fallback."""
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * dims
        normalized = re.sub(r"\s+", "", text.lower())
        padded = f"#{normalized}#"
        for i in range(max(0, len(padded) - 2)):
            gram = padded[i : i + 3]
            vec[hash(gram) % dims] += 1.0
        tokens = _tokenize_chars(text)
        for token in tokens:
            vec[hash(f"t:{token}") % dims] += 2.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm:
            vec = [v / norm for v in vec]
        vectors.append(vec)
    return vectors


def _load_sentence_transformers(model_name: str) -> EmbedFn:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)

    def _encode(texts: Sequence[str]) -> list[list[float]]:
        vectors = model.encode(
            list(texts), normalize_embeddings=True, show_progress_bar=False,
        )
        return [list(map(float, row)) for row in vectors]

    return _encode


def resolve_embedder(settings: Settings | None = None) -> EmbedFn:
    global _cached_st_embedder, _st_load_failed
    if _override_embedder is not None:
        return _override_embedder

    settings = settings or get_settings()
    backend = settings.grouping_embedding_backend

    if backend == "none":
        raise EmbedderUnavailable("grouping_embedding_backend=none")

    if backend in ("sentence_transformers", "auto") and not _st_load_failed:
        if _cached_st_embedder is not None:
            return _cached_st_embedder
        try:
            _cached_st_embedder = _load_sentence_transformers(
                settings.grouping_embedding_model,
            )
            return _cached_st_embedder
        except Exception as exc:  # noqa: BLE001 - optional dependency / download
            _st_load_failed = True
            logger.warning(
                "sentence_transformers_unavailable",
                extra={"error": str(exc)[:200]},
            )
            if backend == "sentence_transformers":
                raise EmbedderUnavailable(str(exc)) from exc

    if backend in ("hashing", "auto"):
        return hashing_embed

    raise EmbedderUnavailable(f"unsupported backend: {backend}")


def suggest_group_assignment(
    payload: GroupSuggestionRequest,
    settings: Settings | None = None,
    embedder: EmbedFn | None = None,
) -> GroupSuggestionResult:
    settings = settings or get_settings()
    t_main = settings.grouping_similarity_threshold
    t_high = settings.grouping_overlap_threshold  # env GROUPING_OVERLAP_THRESHOLD
    issues = list(payload.existing_issues)
    if not issues:
        return GroupSuggestionResult(
            action=GroupingAction.CREATE_NEW,
            rationale="no existing issue in this category",
        )

    try:
        encode = embedder or resolve_embedder(settings)
    except EmbedderUnavailable as exc:
        raise EmbedderUnavailable(str(exc)) from exc

    candidate_text = normalize_grouping_text(payload.candidate_text)
    compare_texts = [
        normalize_grouping_text(_issue_compare_text(issue)) for issue in issues
    ]
    vectors = encode([candidate_text, *compare_texts])
    if len(vectors) != len(issues) + 1:
        raise EmbedderUnavailable("embedder returned unexpected vector count")

    candidate_vec = vectors[0]
    scored: list[tuple[float, ExistingIssueRef, list[str]]] = []
    for issue, vector, text in zip(issues, vectors[1:], compare_texts, strict=True):
        score = _cosine(candidate_vec, vector)
        scored.append((score, issue, _keyword_overlap(candidate_text, text)))
    scored.sort(key=lambda item: (-item[0], item[1].id))

    best_score, best_issue, overlap = scored[0]
    similar_ids = [issue.id for score, issue, _ in scored[:3] if score >= t_main * 0.85]
    top2_margin = settings.grouping_top2_margin

    if best_score < t_main:
        return GroupSuggestionResult(
            action=GroupingAction.CREATE_NEW,
            similar_issue_ids=[issue.id for _, issue, _ in scored[:3]],
            similarity=round(best_score, 4),
            rationale=(
                f"best score {best_score:.4f} < T_main {t_main}; create new group"
            )[:300],
        )

    if len(scored) >= 2:
        second_score = scored[1][0]
        if best_score - second_score < top2_margin:
            return GroupSuggestionResult(
                action=GroupingAction.CREATE_NEW,
                similar_issue_ids=[issue.id for _, issue, _ in scored[:3]],
                similarity=round(best_score, 4),
                rationale=(
                    f"top2 margin: best {best_score:.4f} - second {second_score:.4f} "
                    f"< {top2_margin:.2f}; create new group"
                )[:300],
            )

    gate_on = settings.grouping_keyword_gate
    allow_link = (not gate_on) or bool(overlap) or best_score >= t_high
    if allow_link:
        overlap_note = f"; shared tokens: {', '.join(overlap[:5])}" if overlap else ""
        conf_note = ""
        if gate_on and not overlap and best_score >= t_high:
            conf_note = f"; keyword gate bypass at T_high >={t_high:.2f}"
        return GroupSuggestionResult(
            action=GroupingAction.LINK_EXISTING,
            issue_id=best_issue.id,
            similar_issue_ids=similar_ids or [best_issue.id],
            similarity=round(best_score, 4),
            rationale=(
                f"semantic match score {best_score:.4f} >= T_main {t_main}"
                f"{overlap_note}{conf_note}"
            )[:300],
        )

    return GroupSuggestionResult(
        action=GroupingAction.CREATE_NEW,
        similar_issue_ids=[issue.id for _, issue, _ in scored[:3]],
        similarity=round(best_score, 4),
        rationale=(
            f"keyword gate: score {best_score:.4f} >= T_main {t_main} but no "
            f"substantive token overlap and below T_high {t_high:.2f}"
        )[:300],
    )
