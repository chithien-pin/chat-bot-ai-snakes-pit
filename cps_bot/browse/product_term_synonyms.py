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


def normalize_product_terms(text: str) -> str:
    """Thay cụm đồng nghĩa bằng tên chuẩn CPS (product map / category)."""
    if not (text or "").strip():
        return text or ""
    result = text
    for pattern, replacement in _TERM_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    result = _STORAGE_SHORTHAND_RE.sub(
        lambda m: f"{m.group(1)}gb",
        result,
    )
    return re.sub(r"\s+", " ", result).strip()
