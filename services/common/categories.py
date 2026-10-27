"""Controlled category taxonomy for issue extraction.

The first version keeps the taxonomy as reviewable code constants (with a
version string that is stored on every ``analysis_runs`` row), instead of a
database table.  When the taxonomy needs to be edited by non-developers, it
can be promoted to a ``categories`` table without changing the AI contract:
``category_id`` is already a string column on ``issues`` / ``comment_issues``.

Usage:
    from services.common.categories import CATEGORY_VERSION, get_category
    get_category("quality")           # -> Category
    assert CATEGORY_VERSION == "v1"
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORY_VERSION = "v1"


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    aliases: tuple[str, ...] = ()


CATEGORIES: dict[str, Category] = {
    "quality": Category(id="quality", name="质量", aliases=("做工", "质量", "材质")),
    "logistics": Category(id="logistics", name="物流", aliases=("快递", "发货", "物流", "包裹")),
    "mismatch": Category(id="mismatch", name="描述不符", aliases=("色差", "与描述不符", "尺寸不符")),
    "usability": Category(id="usability", name="使用体验", aliases=("使用", "体验", "功能")),
    "other": Category(id="other", name="其他", aliases=()),
}


def get_category(category_id: str) -> Category:
    """Return the category or raise ``KeyError`` for an unknown id."""
    return CATEGORIES[category_id]


def is_valid_category(category_id: str) -> bool:
    return category_id in CATEGORIES


def category_ids() -> tuple[str, ...]:
    return tuple(CATEGORIES)
