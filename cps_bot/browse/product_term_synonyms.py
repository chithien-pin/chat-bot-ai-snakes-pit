"""
Chuẩn hóa cụm sản phẩm đồng nghĩa — rule-based, không cần gọi LLM.

Ví dụ: "sạc dự phòng" và "pin dự phòng" cùng chỉ power bank trên CPS.
"""
from __future__ import annotations

import re

_TERM_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpin\s+sạc\s+dự\s+phòng\b", re.I), "pin dự phòng"),
    (re.compile(r"\bpin\s+sac\s+du\s+phong\b", re.I), "pin du phong"),
    (re.compile(r"\bsạc\s+dự\s+phòng\b", re.I), "pin dự phòng"),
    (re.compile(r"\bsac\s+du\s+phong\b", re.I), "pin du phong"),
    (re.compile(r"\bpower\s*bank\b", re.I), "pin dự phòng"),
    (re.compile(r"\bbao\s+di\s+dong\b", re.I), "pin dự phòng"),
)
_STORAGE_SHORTHAND_RE = re.compile(
    r"\b(64|128|256|512|1024)\s*g\b(?![bt])",
    re.IGNORECASE,
)
_STORAGE_BARE_RE = re.compile(
    r"\b(64|128|256|512|1024)\b(?!\s*(?:gb|g|tb)\b)",
    re.IGNORECASE,
)
_GALAXY_S_TIER_RE = re.compile(
    r"\b(?:ss\s+)?(?<!galaxy\s)(?<!samsung\sgalaxy\s)s(\d{2})\s*(ultra|u|plus|\+|fe|e)\b",
    re.IGNORECASE,
)
_GALAXY_S_COMPACT_ULTRA_RE = re.compile(
    r"(?<![\w])s(\d{2})u\b",
    re.IGNORECASE,
)
_GALAXY_S_COMPACT_PLUS_RE = re.compile(
    r"(?<![\w])s(\d{2})\+(?:\b|$)",
    re.IGNORECASE,
)
_GALAXY_PREFIXED_COMPACT_RE = re.compile(
    r"\bgalaxy\s+s(\d{2})(u|\+)(?:\b|$)",
    re.IGNORECASE,
)
_GALAXY_ALREADY_PREFIXED_RE = re.compile(
    r"\bsamsung\s+galaxy\s+s\d{2}\b",
    re.IGNORECASE,
)

# iPhone / iPad — model dính liền: ip17prm, iphone17promax, ipadpro
_IPHONE_GLUED_RE = re.compile(
    r"\b(?:iphone|ip)(\d{1,2})(promax|prm|pm|proplus|pro|plus)\b",
    re.IGNORECASE,
)
_IPAD_GLUED_RE = re.compile(
    r"\bipad(air|mini|pro)(?:\s*(\d{1,2}))?\b|\bipad(\d{1,2})(air|mini|pro)\b",
    re.IGNORECASE,
)
_MACBOOK_GLUED_RE = re.compile(
    r"\bmb(air|pro)(?:\s*(m\d(?:\s*pro)?|\d{1,2}(?:\s*inch)?))?\b",
    re.IGNORECASE,
)
_MI_PHONE_GLUED_RE = re.compile(
    r"\bmi(\d{1,2})(t(?:\s*pro)?|tpro|ultra)?\b",
    re.IGNORECASE,
)
_APPLE_ACCESSORY_GLUED_REPLACERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bairpodspro(\d)?\b", re.I), r"airpods pro \1"),
    (re.compile(r"\bairpodsmax\b", re.I), "airpods max"),
    (re.compile(r"\bwatchultra(\d)?\b", re.I), r"watch ultra \1"),
    (re.compile(r"\bmacbookneo\b", re.I), "macbook neo"),
    (re.compile(r"\bmacbookair\b", re.I), "macbook air"),
    (re.compile(r"\bmacbookpro\b", re.I), "macbook pro"),
)
_OPPO_RENO_GLUED_RE = re.compile(
    r"\bopporeno(\d+(?:\s*pro)?(?:\s*plus)?)\b",
    re.IGNORECASE,
)
_TIER_PLUS_SUFFIX_RE = re.compile(r"\bpro\+(?:\b|$)", re.IGNORECASE)
_POCKET_GLUED_RE = re.compile(r"\bpocket(\d)\b", re.IGNORECASE)


def _expand_iphone_glued_shorthands(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        num = match.group(1)
        tier = match.group(2).lower()
        if tier in {"promax", "prm", "pm"}:
            label = "pro max"
        elif tier == "proplus":
            label = "pro plus"
        elif tier == "pro":
            label = "pro"
        else:
            label = "plus"
        return f"iphone {num} {label}"

    return _IPHONE_GLUED_RE.sub(_repl, text)


def _expand_ipad_glued_shorthands(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        if match.group(1):
            tier = match.group(1).lower()
            size = (match.group(2) or "").strip()
            return f"ipad {tier} {size}".strip()
        size = match.group(3)
        tier = match.group(4).lower()
        return f"ipad {tier} {size}".strip()

    return _IPAD_GLUED_RE.sub(_repl, text)


def _expand_macbook_glued_shorthands(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        tier = match.group(1).lower()
        suffix = (match.group(2) or "").strip()
        return f"macbook {tier} {suffix}".strip()

    return _MACBOOK_GLUED_RE.sub(_repl, text)


def _expand_mi_glued_shorthands(text: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        num = match.group(1)
        suffix = (match.group(2) or "").lower().replace(" ", "")
        if suffix in {"t", "tpro"}:
            return f"xiaomi {num}t"
        if suffix == "ultra":
            return f"xiaomi {num} ultra"
        return f"xiaomi {num}"

    return _MI_PHONE_GLUED_RE.sub(_repl, text)


def _expand_apple_accessory_glued_shorthands(text: str) -> str:
    result = text
    for pattern, replacement in _APPLE_ACCESSORY_GLUED_REPLACERS:
        result = pattern.sub(replacement, result)
    return re.sub(r"\s+", " ", result).strip()


def _expand_oppo_glued_shorthands(text: str) -> str:
    return _OPPO_RENO_GLUED_RE.sub(r"oppo reno \1", text)


def _expand_glued_model_shorthands(text: str) -> str:
    """Mở token model dính liền (đa hãng) trước khi tokenize / product map."""
    result = _TIER_PLUS_SUFFIX_RE.sub("pro plus", text)
    result = _expand_iphone_glued_shorthands(result)
    result = _expand_ipad_glued_shorthands(result)
    result = _expand_macbook_glued_shorthands(result)
    result = _expand_apple_accessory_glued_shorthands(result)
    result = _expand_mi_glued_shorthands(result)
    result = _expand_oppo_glued_shorthands(result)
    result = _POCKET_GLUED_RE.sub(r"pocket \1", result)
    return result


def _expand_galaxy_s_models(text: str) -> str:
    """s26 ultra / s26u / s26+ → samsung galaxy s26 ultra|plus (viết tắt phổ biến)."""
    if _GALAXY_ALREADY_PREFIXED_RE.search(text):
        return re.sub(r"\s+", " ", text).strip()

    result = _GALAXY_PREFIXED_COMPACT_RE.sub(
        lambda m: (
            f"samsung galaxy s{m.group(1)} ultra"
            if m.group(2).lower() == "u"
            else f"samsung galaxy s{m.group(1)} plus"
        ),
        text,
    )
    result = _GALAXY_S_COMPACT_ULTRA_RE.sub(
        lambda m: f"samsung galaxy s{m.group(1)} ultra",
        result,
    )
    result = _GALAXY_S_COMPACT_PLUS_RE.sub(
        lambda m: f"samsung galaxy s{m.group(1)} plus",
        result,
    )

    def _tier_repl(match: re.Match[str]) -> str:
        num = match.group(1)
        tier_raw = (match.group(2) or "").lower()
        if tier_raw in {"u"}:
            tier = "ultra"
        elif tier_raw == "+":
            tier = "plus"
        else:
            tier = tier_raw
        return f"samsung galaxy s{num} {tier}"

    return _GALAXY_S_TIER_RE.sub(_tier_repl, result)


def normalize_product_terms(text: str) -> str:
    """Thay cụm đồng nghĩa bằng tên chuẩn CPS (product map / category)."""
    if not (text or "").strip():
        return text or ""
    result = text
    for pattern, replacement in _TERM_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = _expand_glued_model_shorthands(result)
    result = _expand_galaxy_s_models(result)
    result = _STORAGE_SHORTHAND_RE.sub(
        lambda m: f"{m.group(1)}gb",
        result,
    )
    result = _STORAGE_BARE_RE.sub(
        lambda m: f"{m.group(1)}gb",
        result,
    )
    return re.sub(r"\s+", " ", result).strip()
