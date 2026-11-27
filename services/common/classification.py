"""Shared five-category definitions and conservative, bilingual issue checks."""

import re

CATEGORY_GUIDANCE = (
    "quality: physical damage, cracking, broken parts, jammed zippers, torn seams or fading. "
    "logistics: delayed delivery, missing delivery, wrong delivery address. "
    "mismatch: incorrect size or fit (too big/small/narrow/wide/long/short/tight/loose), "
    "wrong colour/style, or differences from the listing. All size/fit complaints belong here, "
    "never quality/usability/other. "
    "usability: comfort and ease of use, excluding size/fit. "
    "other: price/value complaints and concrete issues outside the preceding four categories. "
    "Do not infer a defect from a fear, question, or request for a refund. "
)

FACETS = {
    "size_large": (
        "mismatch",
        (
            "\\btoo\\s+(?:big|large)\\b|\\brun[s]?\\s+(?:big|large)\\b|\\b(?:big"
            "ger|larger)\\s+than\\b|偏大|太大|尺码大"
        ),
    ),
    "size_small": (
        "mismatch",
        r"\btoo\s+small\b|\brun[s]?\s+small\b|\bsmaller\s+than\b|偏小|太小|尺码小",
    ),
    "size_narrow": ("mismatch", r"\btoo\s+(?:narrow|tight)\b|偏窄|太窄|太紧"),
    "size_wide": ("mismatch", r"\btoo\s+(?:wide|loose)\b|偏宽|太宽|太松"),
    "size_long": ("mismatch", r"\btoo\s+long\b|偏长|太长"),
    "size_short": ("mismatch", r"\btoo\s+short\b|偏短|太短"),
    "price_high": (
        "other",
        r"\btoo?\s+expensive\b|\boverpriced\b|\bpoor\s+value\b|太贵|价格过高|不值这个价",
    ),
    "zipper_stuck": (
        "quality",
        (
            "\\b(?:zipper|zip)\\b[^.!?\\n]{0,35}\\b(?:stuck|jam|jams|jammed)\\"
            "b|拉链[^。！？\\n]{0,15}(?:卡|拉不上)|拉不上[^。！？\\n]{0,15}拉链"
        ),
    ),
    "seam_torn": (
        "quality",
        ("\\b(?:seam|stitching)\\b[^.!?\\n]{0,30}\\b(?:torn|split|broke|broken)\\b|开线|脱线"),
    ),
    "strap_broken": (
        "quality",
        (
            "\\bstrap\\b[^.!?\\n]{0,30}\\b(?:broke|broken|torn|detached)\\b|(?"
            ":肩带|带子)[^。！？\\n]{0,20}(?:断|脱开)"
        ),
    ),
    "physical_damage": (
        "quality",
        r"\b(?:cracked|cracking|fell apart|defective|damaged)\b|开裂|破损|断裂",
    ),
    "color_fade": ("quality", r"\bfad(?:e|es|ed|ing)\b|掉色|褪色"),
    "delivery_late": (
        "logistics",
        (
            "\\b(?:late|slow|delayed)\\s+(?:delivery|shipping)\\b|\\b(?:deliv"
            "ery|shipping)\\b[^.!?\\n]{0,35}\\b(?:late|slow|too long|delayed"
            ")\\b|(?:快递|物流|配送|送达)[^。！？\\n]{0,20}(?:慢|晚|迟)|送达太慢"
        ),
    ),
    "delivery_missing": (
        "logistics",
        r"\b(?:never arrived|not received|missing package)\b|没有收到|未收到|没收到",
    ),
    "comfort": ("usability", r"\buncomfortable\b|不舒服|不舒适"),
}
PATTERNS = {key: re.compile(pattern, re.I) for key, (_, pattern) in FACETS.items()}


def facets(text):
    found = {key for key, pattern in PATTERNS.items() if pattern.search(text)}
    if re.search(r"\b(?:delivery|shipping|taking|takes|took|waiting)\b|快递|配送|等待", text, re.I):
        if not re.search(r"\b(?:shoe|pants|size|sleeve|length|dress)\b|尺码|鞋|裤|衣", text, re.I):
            found.discard("size_long")
    return found


def normalized_category(category, description, evidence):
    # A concrete description takes precedence over a quote covering several issues.
    keys = facets(description) or facets(evidence)
    forced = {FACETS[key][0] for key in keys}
    return next(iter(forced)) if len(forced) == 1 else category


def incompatible(left, right):
    a, b = facets(left), facets(right)
    # Known different specific failures must not merge just because both are
    # short complaints or have a high multilingual embedding score.
    return bool(a and b and a.isdisjoint(b))


def can_auto_confirm(extracted, verified, hint, candidate_text):
    if verified.result.source != "llm" or verified.invalid_evidence_count:
        return False
    if extracted.confidence is None or extracted.confidence < 0.9:
        return False
    keys = facets(extracted.description)
    evidence_keys = facets(extracted.evidence_text)
    if not evidence_keys or (keys and keys.isdisjoint(evidence_keys)):
        return False
    keys = keys & evidence_keys if keys else evidence_keys
    if re.search(
        r"\b(?:hope|might|maybe|not sure|not too)\b|可能|担心|希望", extracted.evidence_text, re.I
    ):
        return False
    if not keys or any(FACETS[key][0] != extracted.category_id for key in keys):
        return False
    if hint["fallback"] or hint.get("requires_review", False):
        return False
    if hint["action"] == "link_existing":
        return hint["similarity"] is not None and hint["similarity"] >= 0.8
    return hint["action"] == "create_new"
