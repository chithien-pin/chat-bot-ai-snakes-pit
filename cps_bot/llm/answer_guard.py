"""
Hậu kiểm số liệu trong câu trả lời LLM — phát hiện giá/tiền có thể bịa.
Giai đoạn đầu: log-only, không chặn câu trả lời.
"""
from __future__ import annotations

import re
from typing import Any

# 12.990.000đ | 12,990,000 ₫ | 12990000
_FULL_PRICE_RE = re.compile(
    r"(?<!\d)([\d]{1,3}(?:[.,\s]\d{3})+|\d{6,})(?:\s*(?:đ|₫|vnd|dong))?",
    re.IGNORECASE,
)
# 990k | 12.5tr | 12 triệu | 500 nghìn
_SHORT_PRICE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:k|nghìn|nghin|triệu|trieu|tr)\b",
    re.IGNORECASE,
)

_PRICE_FIELD_HINTS = (
    "price",
    "old_price",
    "value",
    "amount",
    "prepaid",
    "monthly",
    "payment",
    "promo",
    "pmh",
    "tro_gia",
    "discount",
    "fee",
    "root",
    "special",
    "chiet_khau",
)


def _normalize_digits(text: str) -> str:
    return re.sub(r"[^\d]", "", text or "")


def parse_price_to_vnd(text: str) -> int | None:
    """Chuyển chuỗi giá hiển thị → số VND nguyên."""
    raw = (text or "").strip()
    if not raw:
        return None

    short = _SHORT_PRICE_RE.search(raw)
    if short:
        num = float(short.group(1).replace(",", "."))
        unit = short.group(0).lower()
        if "tr" in unit or "tri" in unit:
            return int(num * 1_000_000)
        return int(num * 1_000)

    match = _FULL_PRICE_RE.search(raw)
    if not match:
        digits = _normalize_digits(raw)
        if len(digits) >= 5:
            return int(digits)
        return None

    digits = _normalize_digits(match.group(1))
    if not digits:
        return None
    value = int(digits)
    return value if value >= 1000 else None


def extract_currency_numbers(text: str) -> set[int]:
    """Trích các số tiền VND xuất hiện trong câu trả lời."""
    found: set[int] = set()
    if not text:
        return found

    for match in _SHORT_PRICE_RE.finditer(text):
        parsed = parse_price_to_vnd(match.group(0))
        if parsed:
            found.add(parsed)

    for match in _FULL_PRICE_RE.finditer(text):
        parsed = parse_price_to_vnd(match.group(0))
        if parsed:
            found.add(parsed)

    return found


def _maybe_add_number(value: Any, bucket: set[int]) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        iv = int(value)
        if iv >= 1000:
            bucket.add(iv)
        return
    if isinstance(value, str):
        parsed = parse_price_to_vnd(value)
        if parsed:
            bucket.add(parsed)


def _walk_payload(value: Any, bucket: set[int], *, key_hint: str = "") -> None:
    if value is None:
        return
    if isinstance(value, dict):
        for k, v in value.items():
            hint = f"{key_hint}.{k}" if key_hint else str(k)
            if any(h in k.lower() for h in _PRICE_FIELD_HINTS):
                _maybe_add_number(v, bucket)
            _walk_payload(v, bucket, key_hint=hint)
        return
    if isinstance(value, list):
        for item in value:
            _walk_payload(item, bucket, key_hint=key_hint)
        return
    if key_hint and any(h in key_hint.lower() for h in _PRICE_FIELD_HINTS):
        _maybe_add_number(value, bucket)


def collect_known_numbers(payload: dict[str, Any]) -> set[int]:
    """Gom số tiền hợp lệ từ payload sản phẩm."""
    known: set[int] = set()
    if not payload:
        return known

    primary = payload.get("primary_product") or {}
    for key in ("price", "old_price", "price_value"):
        _maybe_add_number(primary.get(key), known)

    for item in payload.get("search_results") or []:
        if isinstance(item, dict):
            _maybe_add_number(item.get("price"), known)

    for item in payload.get("compare_products") or []:
        if isinstance(item, dict):
            _maybe_add_number(item.get("price"), known)
            _maybe_add_number(item.get("old_price"), known)

    for section in (
        "member_prices",
        "trade_promo",
        "installment",
        "online_stock",
        "shop_stock",
        "similar_products",
        "recommended_products",
        "color_sibling_variants",
    ):
        _walk_payload(payload.get(section), known, key_hint=section)

    _walk_payload(primary.get("member_prices"), known, key_hint="member_prices")
    _walk_payload(primary.get("promotions"), known, key_hint="promotions")

    return known


def _numbers_match(candidate: int, known: set[int], *, tolerance: float = 0.01) -> bool:
    if not known:
        return False
    for ref in known:
        if ref <= 0:
            continue
        if candidate == ref:
            return True
        if abs(candidate - ref) / ref <= tolerance:
            return True
    return False


def check_answer_numbers(
    answer: str,
    payload: dict[str, Any],
    *,
    tolerance: float = 0.01,
) -> list[int]:
    """
    Trả về danh sách số tiền trong answer không khớp payload (±tolerance).
    Rỗng nếu không phát hiện bất thường hoặc payload không có số tham chiếu.
    """
    answer_nums = extract_currency_numbers(answer)
    if not answer_nums:
        return []

    known = collect_known_numbers(payload)
    if not known:
        return []

    mismatches: list[int] = []
    for num in sorted(answer_nums):
        if not _numbers_match(num, known, tolerance=tolerance):
            mismatches.append(num)
    return mismatches
