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
_GALAXY_S_TIER_RE = re.compile(
    r"\b(?:ss\s+)?s(\d{2})\s*(ultra|u|plus|\+|fe|e)\b",
    re.IGNORECASE,
)
_GALAXY_S_COMPACT_ULTRA_RE = re.compile(
    r"\bs(\d{2})u\b",
    re.IGNORECASE,
)


def _expand_galaxy_s_models(text: str) -> str:
    """s26 ultra / s26u → samsung galaxy s26 ultra (viết tắt phổ biến)."""
    result = _GALAXY_S_COMPACT_ULTRA_RE.sub(
        lambda m: f"samsung galaxy s{m.group(1)} ultra",
        text,
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
    result = _expand_galaxy_s_models(result)
    result = _STORAGE_SHORTHAND_RE.sub(
        lambda m: f"{m.group(1)}gb",
        result,
    )
    return re.sub(r"\s+", " ", result).strip()
