"""
Module giao tiếp với Google Gemini API.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là trợ lý tư vấn sản phẩm công nghệ. Dựa trên dữ liệu sản phẩm dưới đây "
    "từ cellphones.com.vn, hãy trả lời câu hỏi của khách hàng một cách rõ ràng, "
    "ngắn gọn, đúng trọng tâm bằng tiếng Việt. "
    "Chỉ dùng thông tin có trong dữ liệu; nếu thiếu thì nói rõ là không có trong dữ liệu. "
    "Dữ liệu là kết quả tìm kiếm CellphoneS cho câu mới nhất — không bỏ qua vì ngữ cảnh cũ. "
    "Có thể dùng emoji phù hợp. Tránh markdown phức tạp (không dùng bảng). "
    "Khách có thể gõ viết tắt (vd: nckd = nồi chiên không dầu); hiểu theo ngữ cảnh câu hỏi."
)

# Cấu hình SDK một lần khi import
genai.configure(api_key=GEMINI_API_KEY)

# Thứ tự thử model (đã kiểm tra 2026-05: 1.5 = 404, 2.0/3.5 = hay 429)
MODEL_FALLBACKS = (
    GEMINI_MODEL,
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
)

# Gợi ý tên sản phẩm đầy đủ — bỏ qua bước chuẩn hóa nếu đã rõ
_PRODUCT_HINTS = (
    "iphone", "ipad", "macbook", "imac", "airpods", "apple watch",
    "samsung", "galaxy", "xiaomi", "redmi", "oppo", "vivo", "realme",
    "laptop", "tablet", "màn hình", "man hinh", "tai nghe",
    "loa ", "chuột", "chuot", "bàn phím", "ban phim", "router", "modem",
    "nồi cơm", "noi com", "máy lạnh", "may lanh", "tủ lạnh", "tu lanh",
)

_VIET_TONE_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
    re.IGNORECASE,
)

# Cụm hỏi thừa — không dùng \bkhông\b (trùng "nồi chiên không dầu")
_QUESTION_NOISE_RE = re.compile(
    r"\b("
    r"có không|có hàng không|còn hàng không|co khong|con hang|"
    r"giá bao nhiêu|bao nhiêu tiền|bn tiền|có ko|có không ạ|"
    r"tư vấn|tu van|cho mình|giúp mình|xin|ạ"
    r")\b",
    re.IGNORECASE,
)
_TRAILING_QUESTION_RE = re.compile(
    r"\s+(có không|còn hàng không|giá bao nhiêu|bao nhiêu tiền)\s*\??\s*$",
    re.IGNORECASE,
)
# Nhu cầu sử dụng — đưa vào câu hỏi Gemini, không gửi API search
_USAGE_CONTEXT_RE = re.compile(
    r"\b("
    r"dùng cho|dung cho|cho gia đình|gia đình \d+\s*người|"
    r"hộ gia đình|phù hợp|nên mua|tư vấn"
    r")\b[^.?;]*",
    re.IGNORECASE,
)

# Viết tắt phổ biến — dùng ngay, không cần gọi API
_LOCAL_ABBREV: dict[str, str] = {
    "nckd": "nồi chiên không dầu",
    "ncd": "nồi chiên không dầu",
    "ncđ": "nồi chiên không dầu",
    "tbnv": "tai nghe bluetooth",
    "tnbl": "tai nghe bluetooth",
    "sdp": "sạc dự phòng",
    "ss": "samsung",
    "ip": "iphone",
    "mb": "macbook",
    "mtb": "máy tính bảng",
    "nc": "nồi cơm điện tử",
}

EXTRACT_KEYWORDS_PROMPT = """Trích từ khóa tìm sản phẩm trên CellphoneS (Việt Nam) từ câu khách.

{context_block}Câu khách (mới nhất): {query}

Quy tắc:
- Chỉ trả về MỘT dòng từ khóa search (danh mục + hãng + model/dung lượng nếu có).
- KHÔNG gồm: có không, giá bao nhiêu, còn hàng, cho mình, xin, ạ, tư vấn, ...
- Viết tắt: nckd=nồi chiên không dầu, ss=Samsung, ip=iPhone, tbnv=tai nghe bluetooth, sdp=sạc dự phòng
- Giữ tên hãng Latin (Bear, Sony, Apple...)

Ví dụ:
- "nckd bear có không?" → nồi chiên không dầu Bear
- "ip 15 pm giá bn" → iPhone 15 Pro Max
- "tư vấn laptop gaming 20 triệu" → laptop gaming
- Nếu câu mới là hỏi tiếp (vd: "còn hàng không", "giá sao", "cái đó") → dùng ngữ cảnh để giữ đúng sản phẩm"""


def _serialize_product_data(product_data: dict[str, Any]) -> str:
    """Chuyển dict sản phẩm sang JSON dễ đọc cho model."""
    return json.dumps(product_data, ensure_ascii=False, indent=2)


def _generate_with_fallback(prompt: str) -> str | None:
    """Gọi Gemini, thử lần lượt các model trong MODEL_FALLBACKS."""
    tried: list[str] = []
    for model_name in MODEL_FALLBACKS:
        if not model_name or model_name in tried:
            continue
        tried.append(model_name)
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            text = (response.text or "").strip()
            if text:
                return text
        except Exception as exc:
            logger.warning("Model %s lỗi: %s", model_name, exc)
    return None


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"\b[\wđĐ]+", text, flags=re.UNICODE)


def _has_abbrev_tokens(text: str) -> bool:
    """Có từ viết tắt trong từ điển (vd: nckd, ss, ip)."""
    for word in _tokenize_words(text):
        if word.lower() in _LOCAL_ABBREV:
            return True
    return False


def _replace_abbrev_tokens(text: str) -> str:
    """Thay từng token viết tắt trong câu (vd: nckd bear → nồi chiên không dầu bear)."""
    parts: list[str] = []
    for word in _tokenize_words(text):
        key = word.lower()
        parts.append(_LOCAL_ABBREV.get(key, word))
    return " ".join(parts) if parts else text


def _strip_question_noise(text: str) -> str:
    """Bỏ cụm hỏi thừa để search API không lệch (vd: có không)."""
    cleaned = _QUESTION_NOISE_RE.sub(" ", text)
    cleaned = _TRAILING_QUESTION_RE.sub("", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _strip_usage_context(text: str) -> str:
    """Bỏ mô tả nhu cầu — chỉ giữ tên SP cho API CellphoneS."""
    cleaned = _USAGE_CONTEXT_RE.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def needs_query_expansion(text: str) -> bool:
    """
    Heuristic: câu ngắn / viết tắt / không dấu → cần chuẩn hóa trước khi search.
    """
    t = text.strip()
    if not t:
        return False

    if _has_abbrev_tokens(t):
        return True

    lower = t.lower()
    if any(h in lower for h in _PRODUCT_HINTS):
        return False
    if re.search(r"\d", t):
        return False

    words = t.split()
    if len(words) == 1 and len(t) <= 12:
        return True
    if len(words) <= 3 and all(len(w) <= 6 for w in words) and not _VIET_TONE_RE.search(t):
        return True
    if " " not in t and len(t) <= 10 and not _VIET_TONE_RE.search(t):
        return True
    return False


def _normalize_keyword_line(text: str) -> str:
    """Một dòng từ khóa sạch cho API search."""
    line = text.strip().strip("\"'`").split("\n")[0].strip()
    return _strip_question_noise(line) or line


def _is_follow_up_question(text: str) -> bool:
    """
    Câu hỏi tiếp thuần (vd: "còn hàng không", "giá sao").
    Câu mới có viết tắt / danh mục / mô tả dài → KHÔNG coi là hỏi tiếp.
    """
    t = text.strip().lower()
    if _has_abbrev_tokens(text):
        return False
    if len(t) > 40 or len(t.split()) > 6:
        return False
    if any(h in t for h in _PRODUCT_HINTS):
        return False

    follow_patterns = (
        "còn hàng", "con hang", "có không", "co khong", "giá sao", "gia sao",
        "bao nhiêu", "bn tiền", "cái đó", "cai do", "thế nào", "the nao",
        "so với", "rẻ hơn", "đắt hơn",
    )
    return any(p in t for p in follow_patterns)


def extract_search_keywords(
    user_text: str,
    conversation_context: str = "",
) -> str:
    """
    Bóc tách từ khóa sản phẩm từ câu khách — chỉ chuỗi này được gửi API CellphoneS.
    """
    original = user_text.strip()
    if not original:
        return ""

    # Bước 1: luôn bóc từ khóa từ CÂU MỚI trước (không ưu tiên context)
    local_keywords = _normalize_keyword_line(
        _strip_usage_context(
            _strip_question_noise(_replace_abbrev_tokens(original))
        )
    )

    # Chỉ hỏi tiếp ngắn mới dùng từ khóa cũ (sau khi đã xác nhận không phải câu mới)
    if conversation_context and _is_follow_up_question(original):
        for line in conversation_context.splitlines():
            if line.startswith("Từ khóa tìm gần nhất:"):
                prev = line.split(":", 1)[1].strip()
                if prev:
                    logger.info("Từ khóa (hỏi tiếp): %r → %r", original, prev)
                    return prev
            if line.startswith("Sản phẩm đang thảo luận:"):
                prev = line.split(":", 1)[1].strip()
                if prev:
                    logger.info("Từ khóa (hỏi tiếp SP): %r → %r", original, prev)
                    return prev

    if _has_abbrev_tokens(original) and local_keywords:
        logger.info("Từ khóa (từ điển): %r → %r", original, local_keywords)
        return local_keywords

    local_full = _LOCAL_ABBREV.get(original.lower())
    if local_full:
        keywords = _normalize_keyword_line(local_full)
        logger.info("Từ khóa (map cả câu): %r → %r", original, keywords)
        return keywords

    if not needs_query_expansion(original):
        keywords = _normalize_keyword_line(original)
        logger.info("Từ khóa (câu rõ): %r → %r", original, keywords)
        return keywords

    # Bước 2: Gemini chỉ trích từ khóa (không câu hỏi đầy đủ)
    ctx = f"{conversation_context}\n\n" if conversation_context else ""
    prompt = EXTRACT_KEYWORDS_PROMPT.format(
        context_block=ctx,
        query=original,
    )
    extracted = _generate_with_fallback(prompt)
    if extracted:
        keywords = _normalize_keyword_line(extracted)
        if keywords:
            logger.info("Từ khóa (Gemini): %r → %r", original, keywords)
            return keywords

    logger.warning(
        "Gemini không trích được từ khóa, dùng bản cục bộ: %r → %r",
        original,
        local_keywords,
    )
    return local_keywords or original


def prepare_search_query(user_text: str) -> tuple[str, bool]:
    """Tương thích cũ — trả về (từ_khóa_search, đã_gọi_gemini)."""
    keywords = extract_search_keywords(user_text)
    used_gemini = needs_query_expansion(user_text) and _has_abbrev_tokens(user_text) is False
    return keywords, used_gemini


def expand_search_query(user_text: str) -> str:
    """API tương thích — trả về từ khóa search."""
    return extract_search_keywords(user_text)


def analyze_product(
    user_question: str,
    product_data: dict[str, Any],
    conversation_context: str = "",
) -> str:
    """
    Gọi Gemini với system prompt + dữ liệu sản phẩm + câu hỏi người dùng.
    """
    user_question = user_question.strip()
    data_text = _serialize_product_data(product_data)

    context_section = f"{conversation_context}\n\n" if conversation_context else ""
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{context_section}"
        f"=== DỮ LIỆU SẢN PHẨM ===\n{data_text}\n\n"
        f"=== CÂU HỎI KHÁCH HÀNG (mới nhất) ===\n{user_question}\n\n"
        "Hãy trả lời theo ngữ cảnh hội thoại (nếu khách hỏi tiếp về cùng sản phẩm):"
    )

    text = _generate_with_fallback(prompt)
    if text:
        return text

    logger.error("Lỗi gọi Gemini phân tích sản phẩm")
    return (
        "⚠️ Không thể kết nối Gemini lúc này. "
        "Vui lòng thử lại sau ít phút."
    )
