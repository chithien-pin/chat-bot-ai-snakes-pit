"""
Phân tích ý định tin nhắn trước khi tra cứu / search CellphoneS.
Tránh search ngẫu nhiên khi user chào hỏi hoặc hỏi ngoài phạm vi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from cps_api import (
    classify_question_scenarios,
    extract_cellphones_urls,
    is_stock_status_browse_query,
)
from budget_browse import is_budget_browse_query
from cps_provinces import resolve_province_from_text
from gemini_client import (
    extract_compare_product_queries,
    is_contextual_follow_up,
    _mentions_new_product,
)

_GREETING_RE = re.compile(
    r"^(?:"
    r"hi|hello|hey|yo|alo|"
    r"chào(?:\s+(?:bạn|ban|shop|bot|anh|em|ad|admin|nhé|nha))?|"
    r"chao(?:\s+(?:ban|shop|bot))?|"
    r"xin chào(?:\s+(?:bạn|ban))?|"
    r"xin chao(?:\s+ban)?|"
    r"good\s+morning|good\s+afternoon|good\s+evening"
    r")(?:\s|!|\.|,|\?|ạ|a|$)+$",
    re.IGNORECASE,
)

_THANKS_RE = re.compile(
    r"^(?:"
    r"cảm ơn|cam on|cám ơn|thank(?:s| you)?|"
    r"ok(?:ey|ie|e)?|oke|được rồi|duoc roi|"
    r"bye|tạm biệt|tam biet|hẹn gặp|hen gap"
    r")(?:\s+(?:nhé|nha|ạ|a|bạn|ban))?(?:\s|!|\.|,|\?|$)+$",
    re.IGNORECASE,
)

_HELP_RE = re.compile(
    r"\b(?:"
    r"bạn là ai|ban la ai|bot là gì|bot la gi|"
    r"làm được gì|lam duoc gi|giúp gì|giup gi|"
    r"hướng dẫn|huong dan|hướng dẫn sử dụng|"
    r"cách dùng|cach dung|sử dụng sao|"
    r"help|/help|/start|bạn biết gì|ban biet gi"
    r")\b",
    re.IGNORECASE,
)

_OFF_TOPIC_RE = re.compile(
    r"\b(?:"
    r"thời tiết|thoi tiet|weather|"
    r"bóng đá|bong da|world cup|"
    r"chính trị|chinh tri|bầu cử|bau cu|"
    r"nấu ăn|nau an|công thức|cong thuc|"
    r"làm bài|lam bai|giải bài|giai bai|"
    r"viết code|viet code|python|javascript|"
    r"kể chuyện|ke chuyen|đùa|dua|tán gẫu|tan gau|"
    r"tình yêu|tinh yeu|phim |xem phim|"
    r"giá vàng|gia vang|bitcoin|crypto|chứng khoán|chung khoan"
    r")\b",
    re.IGNORECASE,
)

_VAGUE_ASK_RE = re.compile(
    r"^(?:"
    r"cho hỏi|cho hoi|hỏi chút|hoi chut|"
    r"tư vấn(?:\s+giúp)?(?:\s+mình|\s+em)?|"
    r"tu van(?:\s+giup)?(?:\s+minh|\s+em)?|"
    r"giúp mình|giup minh|giúp em|giup em|"
    r"check giúp|check giup|xem giúp|xem giup"
    r")(?:\s|!|\.|,|\?|ạ|a|$)*$",
    re.IGNORECASE,
)

_CPS_SCOPE_HINTS = (
    "cellphone", "cellphones", "smember", "s-member", "s-vip", "svip",
    "cửa hàng", "cua hang", "chi nhánh", "chi nhanh", "shop ",
    "điện thoại", "dien thoai", "laptop", "macbook", "iphone", "ipad",
    "samsung", "galaxy", "xiaomi", "oppo", "vivo", "tablet",
    "trả góp", "tra gop", "thu cũ", "thu cu", "trade-in", "trade in",
    "bảo hành", "bao hanh", "khuyến mãi", "khuyen mai",
)

_GREETING_PREFIX_RE = re.compile(
    r"^(?:hi|hello|hey|chào|chao|xin chào|xin chao|alo|yo)\b",
    re.IGNORECASE,
)

_HELP_REQUEST_RE = re.compile(
    r"\b(?:"
    r"cần giúp|can giup|giúp đỡ|giup do|giúp mình|giup minh|"
    r"giúp em|giup em|giúp với|giup voi|"
    r"need help|help me|hỗ trợ|ho tro"
    r")\b",
    re.IGNORECASE,
)

_SOCIAL_HELP_REPLY = (
    "👋 Chào bạn! Mình là bot tư vấn CellphoneS — sẵn sàng hỗ trợ tra cứu "
    "giá, khuyến mãi, tồn cửa hàng, trả góp và thông tin sản phẩm.\n\n"
    "Bạn muốn hỏi về sản phẩm nào? Ví dụ:\n"
    "• Giá iPhone 17 Pro Max 256GB?\n"
    "• Shop quận 1 còn Samsung S26 Ultra không?"
)

_GREETING_REPLY = (
    "👋 Chào bạn! Mình là bot tư vấn sản phẩm công nghệ của CellphoneS.\n\n"
    "Bạn có thể hỏi về giá, khuyến mãi, tồn cửa hàng, trả góp, thu cũ đổi mới "
    "hoặc so sánh sản phẩm — ví dụ:\n"
    "• Giá iPhone 17 Pro Max 256GB?\n"
    "• Shop gần quận 1 còn Samsung S26 Ultra không?\n"
    "• So sánh iPhone 16 Pro Max và S25 Ultra"
)

_HELP_REPLY = (
    "📖 Mình hỗ trợ tra cứu và tư vấn sản phẩm trên cellphones.com.vn:\n\n"
    "• Giá & khuyến mãi (Smember, HSSV, voucher)\n"
    "• Tồn cửa hàng / shop gần bạn\n"
    "• Thu cũ đổi mới, trả góp, bảo hành\n"
    "• So sánh 2 sản phẩm, thông số kỹ thuật\n\n"
    "Gửi tên sản phẩm hoặc câu hỏi cụ thể — mình sẽ tra dữ liệu thật trên website.\n"
    "Gõ /help để xem thêm."
)

_OFF_TOPIC_REPLY = (
    "Mình chỉ hỗ trợ tư vấn sản phẩm công nghệ trên CellphoneS "
    "(điện thoại, laptop, phụ kiện, giá, KM, tồn kho, trả góp…).\n\n"
    "Bạn muốn hỏi sản phẩm nào? Ví dụ: _Giá MacBook Air M4 16GB?_"
)

_CLARIFY_REPLY = (
    "Bạn muốn hỏi về sản phẩm nào trên CellphoneS?\n\n"
    "Gợi ý: ghi rõ tên máy + dung lượng/màu nếu có, "
    "vd _iPhone 16 Pro Max 256GB_ hoặc _laptop gaming dưới 20 triệu_."
)

_THANKS_REPLY = (
    "Không có gì ạ! Nếu cần hỏi thêm về giá, tồn kho hay khuyến mãi sản phẩm khác, "
    "cứ nhắn mình nhé 😊"
)


@dataclass(frozen=True)
class MessageIntent:
    """Kết quả phân tích — kind=product thì tiếp tục tra cứu CPS."""

    kind: str
    reply: str = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _has_cps_scenario(text: str) -> bool:
    return any(classify_question_scenarios(text).values())


def _mentions_cps_scope(text: str) -> bool:
    lower = text.lower()
    return any(h in lower for h in _CPS_SCOPE_HINTS)


def _has_product_signal(text: str) -> bool:
    return bool(
        _mentions_new_product(text)
        or _mentions_cps_scope(text)
        or _has_cps_scenario(text)
        or is_budget_browse_query(text)
        or re.search(r"\d", text)
        or extract_cellphones_urls(text)
    )


def is_social_message(text: str) -> bool:
    """
    Chào hỏi / nhờ giúp chung — không phải hỏi sản phẩm cụ thể.
    Dùng để không kế thừa session SP cũ (vd: hello tôi cần giúp đỡ).
    """
    t = _norm(text)
    if not t:
        return False
    if _GREETING_RE.match(t):
        return True
    if _has_product_signal(t):
        return False
    if _HELP_REQUEST_RE.search(t) and len(t.split()) <= 10:
        return True
    if _GREETING_PREFIX_RE.match(t) and len(t.split()) <= 10:
        return True
    if _HELP_RE.search(t) and len(t.split()) <= 8:
        return True
    return False


def _social_reply(text: str) -> str:
    if _HELP_REQUEST_RE.search(text) or _HELP_RE.search(text):
        return _SOCIAL_HELP_REPLY
    return _GREETING_REPLY


def _is_product_query(
    text: str,
    *,
    has_pending_disambiguation: bool,
    has_compare: bool,
    has_urls: bool,
) -> bool:
    if has_pending_disambiguation or has_compare or has_urls:
        return True
    if is_stock_status_browse_query(text):
        return True
    if _has_cps_scenario(text):
        return True
    if _mentions_new_product(text):
        return True
    if _mentions_cps_scope(text):
        return True
    if re.search(r"\d", text):
        return True
    if extract_cellphones_urls(text):
        return True
    return False


def resolve_message_intent(
    user_text: str,
    *,
    conversation_context: str = "",
    has_product_context: bool = False,
    is_follow_up: bool = False,
    has_pending_disambiguation: bool = False,
    has_pending_province: bool = False,
) -> MessageIntent:
    """
    Phân loại tin nhắn trước search.
    Trả kind=product + reply rỗng → tiếp tục tra cứu CellphoneS.
    """
    text = _norm(user_text)
    if not text:
        return MessageIntent("clarify", _CLARIFY_REPLY)

    has_compare = bool(extract_compare_product_queries(text))
    has_urls = bool(extract_cellphones_urls(text))

    if has_pending_disambiguation or has_compare or has_urls:
        return MessageIntent("product")
    if has_pending_province and resolve_province_from_text(text) is not None:
        return MessageIntent("product")
    if is_stock_status_browse_query(text):
        return MessageIntent("product")
    if is_budget_browse_query(text):
        return MessageIntent("product")

    if is_social_message(text):
        kind = (
            "help"
            if _HELP_RE.search(text) or _HELP_REQUEST_RE.search(text)
            else "greeting"
        )
        return MessageIntent(kind, _social_reply(text))

    if (
        has_product_context
        and (is_follow_up or is_contextual_follow_up(text, conversation_context))
    ):
        return MessageIntent("product")

    if _GREETING_RE.match(text):
        return MessageIntent("greeting", _GREETING_REPLY)
    if _THANKS_RE.match(text):
        return MessageIntent("thanks", _THANKS_REPLY)
    if _HELP_RE.search(text):
        return MessageIntent("help", _HELP_REPLY)
    if _OFF_TOPIC_RE.search(text):
        return MessageIntent("off_topic", _OFF_TOPIC_REPLY)
    if _VAGUE_ASK_RE.match(text):
        return MessageIntent("clarify", _CLARIFY_REPLY)

    if _is_product_query(
        text,
        has_pending_disambiguation=False,
        has_compare=False,
        has_urls=False,
    ):
        return MessageIntent("product")

    return MessageIntent("clarify", _CLARIFY_REPLY)
