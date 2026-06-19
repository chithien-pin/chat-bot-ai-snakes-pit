"""
Luồng hỏi tỉnh/thành trước khi tra cửa hàng — tránh mặc định HCM khi user nói "gần tôi".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cps_api import (
    classify_question_scenarios,
    extract_location_hint,
    is_shop_stock_question,
)
from cps_provinces import resolve_province_from_text

_NEAR_ME_RE = re.compile(
    r"\b("
    r"gần tôi|gan toi|gần mình|gan minh|"
    r"gần đây|gan day|"
    r"ở đâu gần|o dau gan|"
    r"shop gần tôi|shop gan toi|"
    r"cửa hàng gần tôi|cua hang gan toi"
    r")\b",
    re.IGNORECASE,
)

_PROVINCE_META_RE = re.compile(
    r"(?:"
    r"sao\s+(?:bạn|ban|mình|minh)?\s*(?:không|khong|ko)\s+"
    r"(?:hỏi|hoi|check|kiểm tra|kiem tra)"
    r"|"
    r"(?:tại sao|tai sao).*(?:không hỏi|khong hoi|ko hoi).*(?:ở đâu|o dau|tỉnh|tinh)"
    r"|"
    r"(?:hỏi|hoi).*(?:ở đâu|o dau|tỉnh|tinh|thành phố|thanh pho)"
    r")",
    re.IGNORECASE,
)

_ASK_PROVINCE_REPLY_SHOP = (
    "📍 Để kiểm tra cửa hàng còn hàng gần bạn, mình cần biết bạn đang ở "
    "tỉnh/thành phố nào.\n\n"
    "Ví dụ: _Hà Nội_, _TP. Hồ Chí Minh_, _Đà Nẵng_, _Bình Dương_..."
)

_ASK_PROVINCE_REPLY_STORE = (
    "📍 Để tìm cửa hàng CellphoneS gần bạn, mình cần biết bạn đang ở "
    "tỉnh/thành phố nào.\n\n"
    "Ví dụ: _Hà Nội_, _TP. Hồ Chí Minh_, _Đà Nẵng_, _Bình Dương_..."
)


@dataclass(frozen=True)
class ProvinceGateResult:
    """Kết quả kiểm tra tỉnh — should_ask=True thì trả lời ngay, không query CPS."""

    should_ask: bool = False
    reply: str = ""
    pending_kind: str = ""
    province_id: int | None = None


def _session_province_id(session: dict) -> int | None:
    raw = session.get("user_province_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def requires_province_before_shop_query(
    text: str,
    *,
    session_province_id: int | None = None,
) -> bool:
    """True khi cần hỏi tỉnh trước — không được mặc định CPS_PROVINCE_ID."""
    if session_province_id is not None:
        return False
    if resolve_province_from_text(text) is not None:
        return False
    if extract_location_hint(text):
        return False

    scenarios = classify_question_scenarios(text)
    if not scenarios.get("shop_stock") and not scenarios.get("store_locator"):
        return False
    if _NEAR_ME_RE.search(text or ""):
        return True
    if scenarios.get("store_locator"):
        return True
    return False


def is_province_meta_complaint(
    text: str,
    *,
    has_product_context: bool = False,
    pending_province: bool = False,
) -> bool:
    """User phàn nàn bot không hỏi địa điểm — trả lời hỏi tỉnh, không gọi API."""
    if not _PROVINCE_META_RE.search(text or ""):
        return False
    if pending_province or has_product_context:
        return True
    scenarios = classify_question_scenarios(text)
    return bool(scenarios.get("shop_stock") or scenarios.get("store_locator"))


def build_ask_province_reply(kind: str = "shop_stock") -> str:
    if kind == "store_locator":
        return _ASK_PROVINCE_REPLY_STORE
    return _ASK_PROVINCE_REPLY_SHOP


def _pending_kind(text: str) -> str:
    scenarios = classify_question_scenarios(text)
    if scenarios.get("store_locator") and not is_shop_stock_question(text):
        return "store_locator"
    return "shop_stock"


def handle_province_gate(
    text: str,
    session: dict,
    *,
    has_product_context: bool = False,
) -> ProvinceGateResult:
    """
    Xử lý tỉnh từ session / câu hỏi.
    should_ask=True → bot trả lời ngay, set pending_province_for trên session.
    """
    session_province = _session_province_id(session)
    resolved = resolve_province_from_text(text)
    pending = session.get("pending_province_for")

    if is_province_meta_complaint(
        text,
        has_product_context=has_product_context,
        pending_province=bool(pending),
    ):
        kind = pending or _pending_kind(text)
        session["pending_shop_question"] = session.get("pending_shop_question") or text
        return ProvinceGateResult(
            should_ask=True,
            reply=build_ask_province_reply(kind),
            pending_kind=kind,
        )

    if pending and resolved is not None:
        session["user_province_id"] = resolved
        session.pop("pending_province_for", None)
        if pending == "shop_stock":
            session["resume_shop_stock"] = True
        elif pending == "store_locator":
            session["resume_store_locator"] = True
        return ProvinceGateResult(province_id=resolved)

    if resolved is not None:
        session["user_province_id"] = resolved
        return ProvinceGateResult(province_id=resolved)

    if requires_province_before_shop_query(text, session_province_id=session_province):
        kind = _pending_kind(text)
        session["pending_shop_question"] = text
        return ProvinceGateResult(
            should_ask=True,
            reply=build_ask_province_reply(kind),
            pending_kind=kind,
        )

    if session_province is not None:
        return ProvinceGateResult(province_id=session_province)

    return ProvinceGateResult()


def shop_question_for_session(session: dict, user_question: str) -> str:
    """Câu hỏi shop gốc — dùng khi user chỉ trả lời tên tỉnh."""
    return (session.pop("pending_shop_question", None) or user_question).strip()
