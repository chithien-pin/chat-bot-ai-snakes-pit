"""
Module giao tiếp với Google Gemini API.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_PROVIDER

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

SHOP_STOCK_PROMPT_ADDON = (
    "Tồn kho: online_stock.stock_status / stock_quantity = tồn online; "
    "shop_stock = cửa hàng theo tỉnh (total_shops_in_province, shops[].address/phone). "
    "Nếu online_stock báo 'Còn hàng' hoặc stock_quantity > 0 → SP còn tồn online. "
    "Nếu shop_stock.total_shops_in_province > 0 → nêu số cửa hàng và 2–3 địa chỉ mẫu. "
    "KHÔNG nói 'không có tồn' khi dữ liệu đã báo còn hàng. "
    "Nếu khách hỏi khu vực cụ thể mà matched_shops_count = 0, nói rõ không khớp địa chỉ. "
    "Không bịa số lượng tồn từng shop."
)

MEMBER_PRICE_PROMPT_ADDON = (
    "Trong primary_product: price = giá bán (prices.special), old_price = giá gốc (prices.root) nếu cao hơn. "
    "member_prices gồm S-New/S-Member/S-Vip (và HSSV/Giáo viên nếu có). "
    "promotions gồm km_chung, km_rieng, highlights (promotion_info + promotion_information). "
    "stock_status và stock_quantity = tồn online. "
    "Khi khách hỏi giá: nêu price và old_price, liệt kê đủ member_prices, tóm tắt KM chính. "
    "Luôn nêu stock_status nếu có. Không bịa hạng thành viên hoặc quà tặng không có trong dữ liệu."
)

PRODUCT_DATA_PROMPT_ADDON = (
    "Luôn dùng đủ các trường trong primary_product và shop_stock (nếu có). "
    "Không bỏ qua member_prices, promotions, stock_status dù khách chỉ hỏi giá."
)

TRADE_IN_PROMPT_ADDON = (
    "trade_promo: promo_value/pmh = trợ giá thu cũ đổi mới (tham khảo). "
    "Chỉ nêu số liệu có trong trade_promo; không bịa giá máy cũ hay điều kiện lock/vỡ kính "
    "nếu không có trong dữ liệu — gợi ý khách mang máy tới shop để định giá."
)

INSTALLMENT_PROMPT_ADDON = (
    "Trả góp — dùng object installment (API payment-installment):\n"
    "- finance_companies.best_zero_percent_packages: gói CTTC lãi 0%/tháng (Home Credit, MCredit…).\n"
    "- finance_companies.calculated_packages: prepaid_amount, monthly_payment, term_months chính xác.\n"
    "- lowest_zero_prepaid: trả trước thấp nhất trong gói 0% — ưu tiên khi khách hỏi 'trả trước thấp nhất'.\n"
    "- credit_card.zero_fee_by_bank: trả góp thẻ (VIB, TCB…) qua alepay/onepay.\n"
    "- pay_later.details.kredivo.terms: Kredivo/Fundiin/Momo.\n"
    "Khách hỏi Home Credit / thẻ VIB / Kredivo → chỉ trả lời nhánh tương ứng. "
    "installment.available=false → nêu reason. Không bịa số tiền."
)

WARRANTY_PROMPT_ADDON = (
    "Bảo hành: warranty_information = BH hãng; extended_warranty.warranty_packs = gói mua thêm. "
    "included_accessories = phụ kiện trong hộp. "
    "Đổi trả/hoàn tiền: chỉ trả lời nếu có trong warranty_information hoặc policy_note; "
    "không suy diễn chính sách 7 ngày/1 đổi 1 nếu thiếu dữ liệu."
)

SPECS_PROMPT_ADDON = (
    "Thông số: dùng specifications + relation/related_name (biến thể màu/dung lượng). "
    "Tươ thích phụ kiện: chỉ dựa relation/up_sell/included_accessories — không đoán tương thích."
)

COMPARE_PROMPT_ADDON = (
    "Chế độ so sánh: có compare_products[] — nêu khác biệt giá, thông số chính, KM nổi bật. "
    "Kết luận ngắn: nên chọn con nào theo nhu cầu khách (nếu hỏi tư vấn)."
)

ADVICE_PROMPT_ADDON = (
    "Tư vấn chọn mua: gợi ý theo ngân sách/nhu cầu trong câu hỏi; "
    "nếu chỉ có 1 SP trong dữ liệu, nêu ưu/nhược và gợi ý xem thêm danh mục trên web."
)

INCOMING_STOCK_PROMPT_ADDON = (
    "Hàng về/đặt trước: stock_available_id=152 hoặc product_state có 'đặt'/'pre' → "
    "nói đây là đặt trước, không có ngày về cụ thể trong API. Không bịa ETA."
)

MEMBER_TIER_HINTS = (
    "Hạng thành viên: snull_student/snew_student/smem_student/svip_student = HSSV; "
    "svip/smem/snew/snull = Smember. Khi khách hỏi SVIP/HSSV → chỉ nêu tier tương ứng trong member_prices."
)

# Client google-genai (lazy) — thay google.generativeai đã deprecated
_genai_client: Any = None


def _ensure_genai_client() -> Any:
    global _genai_client
    if _genai_client is None:
        from google import genai

        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
    return _genai_client

# Thứ tự thử model: 3.5 Flash (mới nhất) → rẻ hơn nếu 429/quota
MODEL_FALLBACKS = (
    GEMINI_MODEL,
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
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
    r"giá bao nhiêu|bao nhiêu tiền|thêm bao nhiêu|them bao nhieu|bn tiền|có ko|có không ạ|"
    r"tư vấn|tu van|cho mình|giúp mình|xin|ạ"
    r")\b",
    re.IGNORECASE,
)
_SEARCH_PREFIX_RE = re.compile(
    r"^(?:giá|gia|báo giá|bao gia|cho hỏi|cho hoi|xin giá|xin gia)\s+",
    re.IGNORECASE,
)
_SHOP_INQUIRY_SUFFIX_RE = re.compile(
    r"\s+(?:"
    r"có hàng ở cửa hàng nào|còn hàng ở cửa hàng nào|"
    r"ở cửa hàng nào|o cua hang nao|"
    r"có ở cửa hàng|còn ở cửa hàng|co o cua hang|con o cua hang|"
    r"cửa hàng nào(?: còn| có)?|cua hang nao(?: con| co)?|"
    r"chi nhánh nào(?: còn| có)?|chi nhanh nao(?: con| co)?|"
    r"shop nào(?: còn| có)?|shop nao(?: con| co)?|"
    r"ở đâu còn|o dau con|hàng ở đâu|hang o dau|"
    r"gần nhất|gan nhat"
    r").*$",
    re.IGNORECASE,
)
_SEARCH_NOISE_HINTS = (
    "giá ", "gia ", "báo giá", "bao gia",
    "cửa hàng", "cua hang", "chi nhánh", "chi nhanh",
    "shop nào", "shop nao", "có hàng", "co hang", "còn hàng", "con hang",
    "ở đâu", "o dau", "gần ", "gan ", "bao nhiêu", "bao nhieu",
    "lên đời", "len doi", "máy cũ", "may cu", "thu cũ", "thu cu",
    "trợ giá", "tro gia", "trade-in", "trade in",
    "gói bảo hành", "goi bao hanh", "bảo hành", "bao hanh",
)
_TRAILING_QUESTION_RE = re.compile(
    r"\s+(có không|còn hàng không|giá bao nhiêu|bao nhiêu tiền)\s*\??\s*$",
    re.IGNORECASE,
)
_TRADE_CONTEXT_RE = re.compile(
    r"\b(?:lên đời|len doi|từ máy cũ|tu may cu|máy cũ|may cu|"
    r"được trợ giá|duoc tro gia|trợ giá thêm|tro gia them|trade[- ]?in)\b",
    re.IGNORECASE,
)
_WARRANTY_CONTEXT_RE = re.compile(
    r"\b(?:gói bảo hành|goi bao hanh|bảo hành vip|bao hanh vip|"
    r"rơi vỡ|roi vo|apple care\+?|applecare)\b",
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
    "prm": "pro max",
    "pm": "pro max",
    "pp": "pro plus",
    "hssv": "học sinh sinh viên",
    "svip": "s-vip",
    "smem": "s-member",
    "17prm": "iphone 17 pro max",
    "16prm": "iphone 16 pro max",
    "s24u": "samsung galaxy s24 ultra",
    "s25u": "samsung galaxy s25 ultra",
    "s26u": "samsung galaxy s26 ultra",
}

_COMPARE_LEADING_RE = re.compile(
    r"^(?:so sánh|so sanh|tư vấn|tu van|nên mua|nen mua)\s+",
    re.IGNORECASE,
)
_COMPARE_SEP_RE = re.compile(
    r"\s+(?:và|va|vs\.?|với|voi)\s+",
    re.IGNORECASE,
)

EXTRACT_KEYWORDS_PROMPT = """Trích từ khóa tìm sản phẩm trên CellphoneS (Việt Nam) từ câu khách.

{context_block}Câu khách (mới nhất): {query}

Quy tắc:
- Chỉ trả về MỘT dòng từ khóa search (danh mục + hãng + model/dung lượng/màu nếu có).
- KHÔNG gồm: có không, giá bao nhiêu, còn hàng, trả góp, thu cũ, cho mình, xin, ạ, tư vấn, ...
- Viết tắt: ip=iPhone, prm/pm=Pro Max, ss=Samsung, mb=Macbook, hssv=học sinh sinh viên
- Giữ dung lượng (128gb, 256gb), màu (titan, hồng) nếu khách nêu
- Giữ tên hãng Latin (Bear, Sony, Apple, Oppo, Xiaomi...)

Ví dụ:
- "Giá ip 16 pro max 256gb titan tự nhiên" → iPhone 16 Pro Max 256GB Titan Tự Nhiên
- "Check giá s24 ultra 512gb" → Samsung Galaxy S24 Ultra 512GB
- "SVIP mua iPhone 17prm 256" → iPhone 17 Pro Max 256GB
- "Shop còn iPhone 16 Plus 256 màu hồng" → iPhone 16 Plus 256GB Hồng
- "Gần 288 3 tháng 3 còn iPhone 16 Pro 128 Titan sa mạc" → iPhone 16 Pro 128GB Titan Sa Mạc
- "Trả góp Home Credit iPhone 16 128gb" → iPhone 16 128GB
- "Gói BH VIP rơi vỡ iPhone 16 Pro Max" → iPhone 16 Pro Max
- Nếu câu mới là hỏi tiếp → dùng ngữ cảnh giữ đúng sản phẩm"""


def _serialize_product_data(product_data: dict[str, Any]) -> str:
    """Chuyển dict sản phẩm sang JSON dễ đọc cho model."""
    return json.dumps(product_data, ensure_ascii=False, indent=2)


def _build_analysis_prompt(
    user_question: str,
    product_data: dict[str, Any],
    conversation_context: str = "",
) -> str:
    context_section = f"{conversation_context}\n\n" if conversation_context else ""
    shop_stock = product_data.get("shop_stock")
    online_stock = product_data.get("online_stock")
    primary = product_data.get("primary_product") or {}
    scenarios = product_data.get("question_scenarios") or {}
    system = SYSTEM_PROMPT
    if shop_stock or online_stock or primary.get("stock_status"):
        system = f"{system}\n{SHOP_STOCK_PROMPT_ADDON}"
    if (
        primary.get("member_prices")
        or primary.get("promotions")
        or primary.get("promotion_info")
        or primary.get("stock_status")
        or scenarios.get("price_promotion")
    ):
        system = f"{system}\n{MEMBER_PRICE_PROMPT_ADDON}\n{MEMBER_TIER_HINTS}"
    if product_data.get("trade_promo") or scenarios.get("trade_in"):
        system = f"{system}\n{TRADE_IN_PROMPT_ADDON}"
    if scenarios.get("installment") or product_data.get("installment"):
        system = f"{system}\n{INSTALLMENT_PROMPT_ADDON}"
    if (
        scenarios.get("warranty")
        or primary.get("warranty_information")
        or product_data.get("extended_warranty")
    ):
        system = f"{system}\n{WARRANTY_PROMPT_ADDON}"
    if scenarios.get("specs") or primary.get("specifications"):
        system = f"{system}\n{SPECS_PROMPT_ADDON}"
    if product_data.get("compare_mode") or scenarios.get("compare"):
        system = f"{system}\n{COMPARE_PROMPT_ADDON}"
    if scenarios.get("advice"):
        system = f"{system}\n{ADVICE_PROMPT_ADDON}"
    if scenarios.get("incoming_stock"):
        system = f"{system}\n{INCOMING_STOCK_PROMPT_ADDON}"
    system = f"{system}\n{PRODUCT_DATA_PROMPT_ADDON}"
    return (
        f"{system}\n\n"
        f"{context_section}"
        f"=== DỮ LIỆU SẢN PHẨM ===\n{_serialize_product_data(product_data)}\n\n"
        f"=== CÂU HỎI KHÁCH HÀNG (mới nhất) ===\n{user_question}\n\n"
        "Hãy trả lời theo ngữ cảnh hội thoại (nếu khách hỏi tiếp về cùng sản phẩm):"
    )


def _trim_compare_side(text: str) -> str:
    cleaned = _strip_search_noise(_replace_abbrev_tokens(text))
    return re.sub(
        r"^(?:tư vấn|tu van|nên mua|nen mua|đang dùng|dang dung|từ|tu|lên|len|qua|sang)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()


def extract_compare_product_queries(text: str) -> list[str]:
    """
    Tách 2 sản phẩm khi khách so sánh (vd: So sánh S26 Ultra và S25 Ultra).
    Trả [] nếu không phải câu so sánh hoặc không tách được.
    """
    value = (text or "").strip()
    if not value:
        return []
    lower = value.lower()
    if not any(
        marker in lower
        for marker in ("so sánh", "so sanh", " vs ", " vs.", " và ", " va ", "với", "voi")
    ):
        return []

    body = _COMPARE_LEADING_RE.sub("", value).strip()
    parts = _COMPARE_SEP_RE.split(body, maxsplit=1)
    if len(parts) != 2:
        return []

    left = _trim_compare_side(parts[0])
    right = _trim_compare_side(parts[1])
    queries = [q for q in (left, right) if q and len(q) >= 3]
    return queries if len(queries) == 2 else []


def _extract_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not usage:
        return {}
    prompt_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
    completion_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
    total_tokens = int(getattr(usage, "total_token_count", 0) or 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _llm_provider_label() -> str:
    return "DeepSeek" if LLM_PROVIDER == "deepseek" else "Gemini"


def _generate_deepseek_meta(prompt: str) -> tuple[str | None, dict[str, Any]]:
    from deepseek_client import generate_chat

    return generate_chat(prompt)


def _generate_with_fallback_meta(prompt: str) -> tuple[str | None, dict[str, Any]]:
    """Gọi LLM (Gemini hoặc DeepSeek); trả text + metadata usage."""
    if LLM_PROVIDER == "deepseek":
        return _generate_deepseek_meta(prompt)

    tried: list[str] = []
    client = _ensure_genai_client()
    for model_name in MODEL_FALLBACKS:
        if not model_name or model_name in tried:
            continue
        tried.append(model_name)
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = (response.text or "").strip()
            if text:
                return text, {
                    "model": model_name,
                    **_extract_usage(response),
                }
        except Exception as exc:
            logger.warning("Model %s lỗi: %s", model_name, exc)
    return None, {}


def _generate_with_fallback(prompt: str) -> str | None:
    """Giữ API cũ: chỉ trả text."""
    text, _ = _generate_with_fallback_meta(prompt)
    return text


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


def _has_search_noise(text: str) -> bool:
    """Câu còn cụm hỏi giá/tồn/cửa hàng — không nên gửi thẳng API search."""
    lower = (text or "").strip().lower()
    if not lower:
        return False
    if _SEARCH_PREFIX_RE.match(lower):
        return True
    if _SHOP_INQUIRY_SUFFIX_RE.search(lower):
        return True
    return any(h in lower for h in _SEARCH_NOISE_HINTS)


def _strip_search_noise(text: str) -> str:
    """Bóc prefix giá / suffix hỏi tồn cửa hàng — chỉ giữ tên sản phẩm."""
    cleaned = (text or "").strip().rstrip("?").strip()
    cleaned = _SEARCH_PREFIX_RE.sub("", cleaned)
    cleaned = _SHOP_INQUIRY_SUFFIX_RE.sub("", cleaned)
    cleaned = _TRADE_CONTEXT_RE.sub(" ", cleaned)
    cleaned = _WARRANTY_CONTEXT_RE.sub(" ", cleaned)
    cleaned = _strip_question_noise(cleaned)
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
    if _has_search_noise(t):
        return True
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
    line = _strip_search_noise(line)
    return line


def _is_follow_up_question(text: str) -> bool:
    """
    Câu hỏi tiếp thuần (vd: "còn hàng không", "giá sao").
    Câu mới có viết tắt / danh mục / mô tả dài → KHÔNG coi là hỏi tiếp.
    """
    t = text.strip().lower()
    if _has_abbrev_tokens(text):
        return False
    if len(t) > 55 or len(t.split()) > 8:
        return False
    if any(h in t for h in _PRODUCT_HINTS):
        return False

    follow_patterns = (
        "còn hàng", "con hang", "có không", "co khong", "giá sao", "gia sao",
        "bao nhiêu", "bn tiền", "cái đó", "cai do", "thế nào", "the nao",
        "so với", "rẻ hơn", "đắt hơn",
        "quà tặng", "qua tang", "khuyến mãi", "khuyen mai", "ưu đãi", "uu dai",
        "tặng gì", "tang gi", "có gì", "co gi", "trả góp", "tra gop",
        "bảo hành", "bao hanh", "đủ không", "du khong", "phù hợp", "phu hop",
        "nên mua", "nen mua", "giảm giá", "giam gia", "pmh", "voucher",
    )
    return any(p in t for p in follow_patterns)


def _context_has_product(conversation_context: str) -> bool:
    ctx = conversation_context or ""
    return (
        "Sản phẩm đang thảo luận:" in ctx
        or "Từ khóa tìm gần nhất:" in ctx
    )


def is_contextual_follow_up(
    text: str,
    conversation_context: str = "",
) -> bool:
    """
    Câu hỏi tiếp trong cùng chủ đề SP (kể cả hỏi quà tặng/KM mà không nhắc tên SP).
    """
    if not _context_has_product(conversation_context):
        return False
    if _is_follow_up_question(text):
        return True

    t = text.strip().lower()
    if _has_abbrev_tokens(text):
        return False
    if any(h in t for h in _PRODUCT_HINTS):
        return False
    if len(t) > 60:
        return False

    # Câu ngắn hỏi thêm về SP đang thảo luận (không chứa tên SP mới)
    question_markers = ("không", "khong", "gì", "gi", "sao", "nào", "nao", "?")
    if len(t.split()) <= 10 and any(m in t for m in question_markers):
        return True
    return False


def _reuse_keywords_from_context(
    original: str,
    conversation_context: str,
) -> str | None:
    keywords = ""
    product_name = ""
    for line in conversation_context.splitlines():
        if line.startswith("Từ khóa tìm gần nhất:"):
            keywords = line.split(":", 1)[1].strip()
        elif line.startswith("Sản phẩm đang thảo luận:"):
            product_name = line.split(":", 1)[1].strip()

    if keywords:
        logger.info("Từ khóa (ngữ cảnh): %r → %r", original, keywords)
        return keywords
    if product_name:
        logger.info("Từ khóa (SP ngữ cảnh): %r → %r", original, product_name)
        return product_name
    return None


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
        _strip_usage_context(_replace_abbrev_tokens(original))
    )

    # Hỏi tiếp trong cùng chủ đề → giữ từ khóa / SP cũ, không search lại bừa
    if conversation_context and is_contextual_follow_up(original, conversation_context):
        reused = _reuse_keywords_from_context(original, conversation_context)
        if reused:
            return reused

    if _has_abbrev_tokens(original) and local_keywords:
        logger.info("Từ khóa (từ điển): %r → %r", original, local_keywords)
        return local_keywords

    local_full = _LOCAL_ABBREV.get(original.lower())
    if local_full:
        keywords = _normalize_keyword_line(local_full)
        logger.info("Từ khóa (map cả câu): %r → %r", original, keywords)
        return keywords

    if local_keywords and not _has_search_noise(local_keywords):
        logger.info("Từ khóa (bóc cục bộ): %r → %r", original, local_keywords)
        return local_keywords

    if not needs_query_expansion(original):
        keywords = local_keywords or _normalize_keyword_line(original)
        logger.info("Từ khóa (câu rõ): %r → %r", original, keywords)
        return keywords

    # Bước 2: Gemini trích từ khóa khi bóc cục bộ chưa đủ
    ctx = f"{conversation_context}\n\n" if conversation_context else ""
    prompt = EXTRACT_KEYWORDS_PROMPT.format(
        context_block=ctx,
        query=original,
    )
    extracted = _generate_with_fallback(prompt)
    if extracted:
        keywords = _normalize_keyword_line(extracted)
        if keywords:
            logger.info("Từ khóa (%s): %r → %r", _llm_provider_label(), original, keywords)
            return keywords

    logger.warning(
        "%s không trích được từ khóa, dùng bản cục bộ: %r → %r",
        _llm_provider_label(),
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
    prompt = _build_analysis_prompt(user_question, product_data, conversation_context)

    text, _ = _generate_with_fallback_meta(prompt)
    if text:
        return text

    label = _llm_provider_label()
    logger.error("Lỗi gọi %s phân tích sản phẩm", label)
    return (
        f"⚠️ Không thể kết nối {label} lúc này. "
        "Vui lòng thử lại sau ít phút."
    )


def analyze_product_with_meta(
    user_question: str,
    product_data: dict[str, Any],
    conversation_context: str = "",
) -> tuple[str, dict[str, Any]]:
    """
    Trả về (answer, metadata) để đo token/ model cho metrics.
    """
    user_question = user_question.strip()
    prompt = _build_analysis_prompt(user_question, product_data, conversation_context)

    text, meta = _generate_with_fallback_meta(prompt)
    if text:
        return text, meta

    label = _llm_provider_label()
    logger.error("Lỗi gọi %s phân tích sản phẩm", label)
    return (
        f"⚠️ Không thể kết nối {label} lúc này. "
        "Vui lòng thử lại sau ít phút.",
        meta,
    )
