"""
Module giao tiếp với Google Gemini API.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import GEMINI_API_KEY, GEMINI_MODEL, LLM_KEYWORD_NORMALIZE, LLM_PROVIDER
from cps_bot.browse.budget_browse import (
    is_budget_browse_query,
    strip_budget_phrases_for_keywords,
    _extract_category as _budget_category_from_text,
)
from cps_bot.cps.cps_api import (
    is_color_variant_list_query,
    is_stock_status_browse_query,
    merge_follow_up_variant_into_keywords,
    needs_shop_stock_keyword_strip,
    strip_color_variant_list_phrases_for_keywords,
    strip_shop_stock_phrases_for_keywords,
    strip_stock_browse_phrases_for_keywords,
)

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
    "Tồn kho: online_stock.stock_availability / stock_available_id = trạng thái chính thức; "
    "stock_status = nhãn hiển thị; stock_quantity = số lượng online. "
    "shop_stock = cửa hàng theo tỉnh (total_shops_in_province, shops[].address/phone). "
    "Chỉ nói 'còn hàng' khi is_buyable_online=true hoặc is_in_stock=true. "
    "stock_available_id=43 → hết hàng; 56 → đăng ký nhận tin (chưa bán). "
    "Nếu shop_stock.total_shops_in_province > 0 → nêu số cửa hàng và 2–3 địa chỉ mẫu. "
    "Nếu location_hint có quận/khu vực → dùng shop_stock.shops (matched_shops_count, địa chỉ, SĐT). "
    "KHÔNG nói 'không có thông tin theo quận' khi shops[] đã có dữ liệu. "
    "KHÔNG nói 'không có tồn' khi dữ liệu báo còn hàng / đặt trước. "
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
    "Không bỏ qua member_prices, promotions, stock_status dù khách chỉ hỏi giá. "
    "Mỗi sản phẩm trong search_results có trường url — khi liệt kê SP phải kèm link url đó."
)

TRADE_IN_PROMPT_ADDON = (
    "trade_promo: promo_value/pmh = trợ giá thu cũ đổi mới (tham khảo). "
    "Chỉ nêu số liệu có trong trade_promo; không bịa giá máy cũ hay điều kiện lock/vỡ kính "
    "nếu không có trong dữ liệu — gợi ý khách mang máy tới shop để định giá."
)

INSTALLMENT_PROMPT_ADDON = (
    "Trả góp — 3 nhánh chính (khớp modal trả góp CellphoneS):\n"
    "0. installment_info (GET /payment-installment/info): finance_companies_catalog + "
    "payment_methods_catalog — dùng khi hỏi chung các hình thức/CTTC hỗ trợ.\n"
    "1. CTTC (installment.finance_companies): best_zero_percent_packages = gói 0%/tháng; "
    "calculated_packages = prepaid_amount + monthly_payment + term_months chính xác; "
    "lowest_zero_prepaid = trả trước thấp nhất trong gói 0%.\n"
    "2. Thẻ tín dụng (installment.credit_card): zero_fee_by_bank từ "
    "online-calculate/onepay — mỗi bank có short_name/full_name (từ onepay list_bank), "
    "cards[] (card_name, card_type, zero_fee_periods + all_periods; requested_term_periods "
    "có thể có phí chuyển đổi fee_amount > 0 với kỳ 9/12/15 tháng). "
    "requested_term_periods = kỳ khách hỏi. Ưu tiên OnePay.\n"
    "3. Mua trước trả sau (installment.pay_later): pay_later.details.kredivo/fundiin/momo_vts "
    "= kỳ hạn + lãi suất + tiền/tháng.\n"
    "Quy tắc trả lời:\n"
    "- Hỏi chung 'trả góp được không' / 'có những hình thức nào' → installment_info + "
    "finance_companies + lowest_zero_prepaid.\n"
    "- Hỏi CTTC cụ thể (Home Credit, MCredit…) → calculated_packages lọc đúng company_key.\n"
    "- 'trả trước ít nhất' / 'trả trước thấp nhất' → lowest_zero_prepaid.\n"
    "- '0%' / 'miễn lãi' → chỉ gói is_zero_percent=true trong best_zero_percent_packages.\n"
    "- Hỏi thẻ/ngân hàng/OnePay/chuyển đổi trả góp → credit_card.zero_fee_by_bank (onepay).\n"
    "- Kredivo/Fundiin/Momo/mua trước trả sau → pay_later.details.\n"
    "- installment.needs_clarification=true → KHÔNG trả số tiền/gói trả góp chi tiết; "
    "hỏi lại đúng missing_fields, dùng clarification_message (vd thiếu ngân hàng/kỳ hạn/loại thẻ).\n"
    "- installment.available=false → nêu reason, không bịa số tiền hay kỳ hạn.\n"
    "- installment.note: giá chưa gồm chiết khấu Smember nếu khách chưa đăng nhập."
)

INSTALLMENT_SCENARIO_HINTS = (
    "Câu hỏi trả góp — nhận dạng và trả lời theo scenario:\n"
    "- A0 (hình thức trả góp): 'có những hình thức trả góp nào' → installment_info.payment_methods_catalog "
    "+ finance_companies_catalog.\n"
    "- A1 (hỏi chung SP): 'trả góp được không', 'có gói trả góp' → finance_companies.companies + "
    "lowest_zero_prepaid.\n"
    "- A2 (CTTC cụ thể): '[Home Credit/MCredit] mấy tháng' → calculated_packages[company_key].\n"
    "- A3 (trả trước thấp nhất): 'trả trước bao nhiêu', 'trả trước ít nhất' → lowest_zero_prepaid.\n"
    "- A4 (gói 0%): 'miễn lãi', '0%' → best_zero_percent_packages (is_zero_percent=true).\n"
    "- B1 (thẻ chung): 'trả góp thẻ tín dụng' — thiếu ngân hàng/kỳ/loại thẻ → needs_clarification, hỏi lại.\n"
    "- B2 (ngân hàng cụ thể): đủ bank + term_months + card_type → zero_fee_by_bank; thiếu → hỏi thêm.\n"
    "- C1 (mua trước trả sau): 'Kredivo/Fundiin/Momo' → pay_later.details.\n"
    "- D1 (không hỗ trợ): available=false → nêu reason, gợi ý thanh toán khác."
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
    "Hàng về/đặt trước: stock_available_id=152 (is_pre_order=true) → đặt trước; "
    "không bịa ngày về cụ thể. stock_available_id=56 → đăng ký nhận tin, chưa có hàng."
)

STOCK_STATUS_PROMPT_ADDON = (
    "Trạng thái sản phẩm — dùng stock_availability (ưu tiên hơn đoán từ stock_quantity):\n"
    "43 = Hết hàng (out_of_stock) — không mua ngay.\n"
    "46 = Còn hàng (in_stock) — mua ngay, nêu stock_quantity nếu có.\n"
    "56 = Đăng ký nhận tin (subscription) — chưa có hàng, chỉ đăng ký nhận thông báo.\n"
    "152 = Đặt trước (pre_order) — đặt cọc/đặt trước, không bịa ETA.\n"
    "4164 = Drop shipping — còn bán, giao drop ship.\n"
    "4920 = Tồn ảo (virtual_stock) — còn hàng online.\n"
    "Luôn trả lời đúng status_label / display_status. "
    "KHÔNG nói 'còn hàng' khi is_out_of_stock hoặc is_subscription."
)

RECOMMENDED_PRODUCTS_PROMPT_ADDON = (
    "recommended_products[] là gợi ý phụ kiện / sản phẩm mua cùng từ CellphoneS (tối đa 5). "
    "Sau khi trả lời câu hỏi chính về primary_product, gợi ý ngắn 2–5 SP trong danh sách: "
    "tên + giá + link url. Không bịa SP ngoài recommended_products. "
    "Có thể gợi ý nhẹ ở cuối tin nhắn dù khách không hỏi mua kèm."
)

SIMILAR_PRODUCTS_PROMPT_ADDON = (
    "similar_products[] là sản phẩm tương tự từ block 'Có thể bạn cũng thích' trên PDP CellphoneS. "
    "Khi primary_product có stock_available_id=43 hoặc 56, KHÔNG tư vấn thêm khuyến mãi, "
    "giá theo hạng thành viên, thu cũ, tồn kho chi tiết, hay phụ kiện mua cùng. "
    "Chỉ nói ngắn gọn máy đang hết hàng/đăng ký nhận tin rồi gợi ý 2–5 sản phẩm trong similar_products "
    "(tên + giá + link url)."
)

COLOR_VARIANTS_PROMPT_ADDON = (
    "Khách hỏi màu khác / màu còn tồn — dùng color_sibling_variants.variants[]: "
    "mỗi phần tử là một màu sibling (cùng dung lượng/model cha). "
    "BẮT BUỘC liệt kê các màu trong variants (tên + giá + stock_status; kèm url nếu có). "
    "TUYỆT ĐỐI không nói 'không có dữ liệu màu khác' khi color_sibling_variants.count > 1. "
    "Nêu rõ màu đang xem (current_product_id) và các màu còn lại."
)

STOCK_BROWSE_PROMPT_ADDON = (
    "Khách đang tìm SP theo trạng thái tồn (stock_browse). "
    "search_results đã lọc theo company_stock_id / stock_filter_ids. "
    "Nếu primary_product.stock_browse_list_mode=true: đây là DANH SÁCH, không deep-dive 1 SP. "
    "Liệt kê tối thiểu 5–8 SP từ search_results: tên + giá + link url (bắt buộc). "
    "Mở đầu bằng tổng số SP và trạng thái tồn đang lọc. "
    "Nếu stock_browse_list_mode=false: primary_product là SP khớp từ khóa; vẫn nêu thêm SP liên quan. "
    "Không gợi ý SP ngoài danh sách đã lọc trạng thái."
)

BUDGET_BROWSE_PROMPT_ADDON = (
    "Khách đang tìm SP theo ngân sách (budget_browse). "
    "search_results[] là DANH SÁCH SP thật (name, price, url). "
    "primary_product chỉ là metadata — KHÔNG phải 1 SP. "
    "BẮT BUỘC liệt kê 5–10 SP từ search_results: tên + giá + link url. "
    "Không nói 'không có thông tin chi tiết' khi search_results không rỗng. "
    "Mở đầu nêu ngân sách khách hỏi và số SP tìm được. "
    "Không gợi ý SP ngoài danh sách hoặc vượt ngân sách."
)

CATEGORY_FILTER_BROWSE_PROMPT_ADDON = (
    "Khách đang tìm SP theo bộ lọc danh mục (category_filter_browse). "
    "search_results[] là DANH SÁCH SP thật (mỗi phần tử có name, price, url). "
    "primary_product chỉ là metadata (product_count, category_filter_url) — KHÔNG phải 1 SP. "
    "BẮT BUỘC liệt kê 5–10 SP từ search_results: tên + giá + link url. "
    "TUYỆT ĐỐI không nói 'không có thông tin chi tiết' khi search_results không rỗng. "
    "Mở đầu nêu danh mục/tiêu chí lọc (category_filter_matched) và số SP tìm được. "
    "Không gợi ý SP ngoài danh sách đã lọc."
)

REVIEWS_PROMPT_ADDON = (
    "product_reviews: average_rating, total_reviews, sample_reviews. "
    "Nêu điểm trung bình và 1–2 nhận xét tiêu biểu; không bịa review ngoài dữ liệu."
)

FAQ_PROMPT_ADDON = (
    "product_faqs: Q&A chính sách từ CellphoneS. "
    "Ưu tiên trích từ product_faqs khi khách hỏi đổi trả/bảo hành/chính sách."
)

FLASH_SALE_PROMPT_ADDON = (
    "flash_sale: chương trình flash sale (slots, giá flash_sale, thời gian). "
    "Nêu giá flash và slot còn nếu có; không bịa giá ngoài dữ liệu."
)

TRADE_DEVICE_PROMPT_ADDON = (
    "trade_exchange_products: giá thu máy cũ theo tình trạng (thu_loai_1–4, tro_gia). "
    "Giải thích các mức thu; nhắc giá thực tế phụ thuộc tình trạng tại shop."
)

STORE_LOCATOR_PROMPT_ADDON = (
    "store_locator: danh sách cửa hàng theo quận (districts, shops). "
    "Nêu tổng số CH và 3–5 địa chỉ mẫu kèm phone/google_link nếu có."
)

COMBO_PROMPT_ADDON = (
    "product_combos: gói mua kèm/combo (discount_percent, max_value). "
    "Nêu combo tiết kiệm nhất; khuyên xem chi tiết trên web."
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
    "iphone", "ipad", "macbook", "mac mini", "mac studio", "imac", "airpods", "apple watch",
    "samsung", "galaxy", "xiaomi", "redmi", "oppo", "vivo", "realme",
    "điện thoại", "dien thoai", "smartphone",
    "laptop", "tablet", "máy tính", "may tinh", "máy tính bảng", "may tinh bang",
    "màn hình", "man hinh", "tai nghe",
    "loa ", "chuột", "chuot", "bàn phím", "ban phim", "router", "modem",
    "nồi cơm", "noi com", "máy lạnh", "may lanh", "tủ lạnh", "tu lanh",
    "nồi chiên", "noi chien", "máy xay", "may xay", "máy sấy", "may say",
    "bình đun", "binh dun", "ấm siêu tốc", "am sieu toc",
    "smartwatch", "đồng hồ", "dong ho", "tivi", "camera", "máy ảnh", "may anh",
    "pin dự phòng", "pin du phong", "sạc dự phòng", "sac du phong", "power bank",
    "anker", "baseus", "ugreen",
    "quạt", "quat",
)

_VIET_TONE_RE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]",
    re.IGNORECASE,
)

# Cụm hỏi thừa — không dùng \bkhông\b (trùng "nồi chiên không dầu")
_QUESTION_NOISE_RE = re.compile(
    r"\b("
    r"có không|có hàng không|còn hàng không|co khong|con hang|"
    r"có voucher gì|có voucher gi|co voucher gi|"
    r"giá bao nhiêu|giá như thế nào|giá như nào|gia nhu the nao|gia nhu nao|"
    r"như thế nào|nhu the nao|thế nào|the nao|"
    r"bao nhiêu tiền|thêm bao nhiêu|them bao nhieu|bn tiền|có ko|có không ạ|"
    r"tư vấn|tu van|cho mình|giúp mình|xin|ạ"
    r")\b",
    re.IGNORECASE,
)
_SEARCH_PREFIX_RE = re.compile(
    r"^(?:giá|gia|báo giá|bao gia|check giá|check gia|cho hỏi|cho hoi|xin giá|xin gia)\s+",
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
_SHOP_STOCK_PRODUCT_PREFIX_RE = re.compile(
    r"^(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\s+"
    r"(?:(?:gần|gan)\s+)?(?:"
    r"(?:quận|quan|huyện|huyen|phường|phuong)\s+\d+|[qQ]\.?\s*\d+|"
    r"(?:tôi|toi|mình|minh|đây|day)"
    r")\s+"
    r"(?:còn|co(?:\s+hàng|\s+hang)?)\s+",
    re.IGNORECASE,
)
_SEARCH_NOISE_HINTS = (
    "giá ", "gia ", "báo giá", "bao gia",
    "cửa hàng", "cua hang", "chi nhánh", "chi nhanh",
    "shop nào", "shop nao", "shop gần", "shop gan", "shop quận", "shop quan",
    "có hàng", "co hang", "còn hàng", "con hang",
    "ở đâu", "o dau", "gần ", "gan ", "quận ", "quan ",
    "bao nhiêu", "bao nhieu",
    "lên đời", "len doi", "máy cũ", "may cu", "thu cũ", "thu cu",
    "trợ giá", "tro gia", "trade-in", "trade in",
    "gói bảo hành", "goi bao hanh", "bảo hành", "bao hanh",
)
_TRAILING_QUESTION_RE = re.compile(
    r"\s+(?:"
    r"có không|còn hàng không|"
    r"có voucher gì không|co voucher gi khong|"
    r"(?:(?:hôm nay|hom nay|hiện tại|hien tai|bây giờ|bay gio|hiện nay|hien nay)\s+)?"
    r"(?:giá\s+)?(?:bao nhiêu|bao nhieu)(?:\s+tiền|\s+tien)?"
    r"|giá bao nhiêu|bao nhiêu tiền"
    r")\s*\??\s*$",
    re.IGNORECASE,
)
_MEMBER_TIER_PREFIX_RE = re.compile(
    r"^(?:svip|s-vip|smember|s-member|hssv|học sinh sinh viên)\s+(?:mua\s+)?",
    re.IGNORECASE,
)
_INCOMING_STOCK_SUFFIX_RE = re.compile(
    r"\s+(?:"
    r"khi nào hàng về|khi nao hang ve|"
    r"hàng về tới shop|hang ve toi shop|"
    r"bao giờ về|bao gio ve|"
    r"khi nào về|khi nao ve"
    r").*$",
    re.IGNORECASE,
)
_MODEL_COMPOUND_NORMALIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpromax\b", re.I), "pro max"),
    (re.compile(r"\bproplus\b", re.I), "pro plus"),
    (re.compile(r"\bultraplus\b", re.I), "ultra plus"),
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
_INSTALLMENT_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"thông tin trả góp|thong tin tra gop|"
    r"trả góp|tra gop|"
    r"gói nào ưu đãi nhất|goi nao uu dai nhat|"
    r"gói ưu đãi nhất|goi uu dai nhat|"
    r"gói tốt nhất|goi tot nhat|"
    r"trả trước thấp nhất|tra truoc thap nhat|"
    r"trả trước ít nhất|tra truoc it nhat|"
    r"miễn lãi|mien lai|0%|"
    r"qua thẻ tín dụng|qua the tin dung|"
    r"qua thẻ|qua the|"
    r"qua ngân hàng|qua ngan hang|"
    r"kỳ hạn|ky han|"
    r"tháng"
    r")\b",
    re.IGNORECASE,
)
_COMBO_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"phụ kiện mua kèm|phu kien mua kem|"
    r"phụ kiện mua cùng|phu kien mua cung|"
    r"phụ kiện kèm|phu kien kem|"
    r"phụ kiện cho|phu kien cho|"
    r"mua kèm|mua kem|mua cùng|mua cung|mua chung|"
    r"mua thêm giảm|mua them giam|"
    r"combo|bundle|cross[- ]?sell"
    r")\b",
    re.IGNORECASE,
)
# Nhu cầu sử dụng — đưa vào câu hỏi Gemini, không gửi API search
_USAGE_CONTEXT_RE = re.compile(
    r"\b("
    r"dùng cho|dung cho|cho gia đình|gia đình \d+\s*người|"
    r"hộ gia đình|phù hợp|nên mua|tư vấn|"
    r"có thể mang|co the mang|mang lên máy bay|mang len may bay|"
    r"mang lên tàu|mang len tau|mang lên xe|mang len xe|"
    r"được mang|duoc mang|mang theo|mang theo"
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
    "sdp": "pin dự phòng",
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

# Câu hỏi thuộc tính SP (màu, giá, RAM…) — không nhắc tên SP mới
_ATTRIBUTE_FOLLOW_UP_RE = re.compile(
    r"\b("
    r"màu sắc|mau sac|màu gì|mau gi|có màu|co mau|"
    r"giá bán|gia ban|giá sao|gia sao|"
    r"dung lượng|dung luong|bộ nhớ|bo nho|"
    r"thông số|thong so|cấu hình|cau hinh|"
    r"pin|sạc|sac|camera|màn hình|man hinh|"
    r"quà tặng|qua tang|khuyến mãi|khuyen mai|ưu đãi|uu dai|"
    r"còn hàng|con hang|có hàng|co hang|tồn kho|ton kho|"
    r"trả góp|tra gop|bảo hành|bao hanh|"
    r"so sánh|so sanh"
    r")\b",
    re.IGNORECASE,
)

_COMPARE_LEADING_RE = re.compile(
    r"^(?:so sánh|so sanh|tư vấn|tu van|nên mua|nen mua)\s+",
    re.IGNORECASE,
)
_COMPARE_SEP_RE = re.compile(
    r"\s+(?:và|va|vs\.?|với|voi)\s+",
    re.IGNORECASE,
)
_PRIOR_PRODUCT_REF_RE = re.compile(
    r"\b(?:"
    r"sản phẩm này|san pham nay|"
    r"cái này|cai nay|cái đó|cai do|"
    r"máy này|may nay|"
    r"con này|con nay|"
    r"chiếc này|chiec nay|"
    r"sp này|sp nay|"
    r"em này|em nay|"
    r"nó có|no co"
    r")\b",
    re.IGNORECASE,
)
# Xác nhận ngắn sau khi bot hỏi tiếp (vd: "Bạn cần tư vấn thêm... không?" → "có tư vấn đi")
_AFFIRMATIVE_FOLLOW_UP_EXACT = frozenset({
    "co", "co di", "co tu van", "co tu van di", "co tu van them",
    "co nhe", "co a", "co luon", "co them",
    "tu van di", "tu van them", "tu van giup", "tu van giup em",
    "ok", "oke", "okie", "okay", "yes", "yeah", "yep",
    "duoc", "duoc a", "duoc nhe",
    "u", "uh", "uhm", "um", "vang", "da", "da a",
})

EXTRACT_KEYWORDS_PROMPT = """Trích từ khóa tìm sản phẩm trên CellphoneS (Việt Nam) từ câu khách.

{context_block}Câu khách (mới nhất): {query}

Quy tắc:
- Chỉ trả về MỘT dòng từ khóa search (danh mục + hãng + model/dung lượng/màu nếu có).
- KHÔNG gồm: có không, giá bao nhiêu, còn hàng, trả góp, thu cũ, cho mình, xin, ạ, tư vấn, ...
- Bỏ ngữ cảnh sử dụng không phải tên SP: mang lên máy bay, dùng cho gia đình, phù hợp học sinh...
- Đồng nghĩa danh mục (chuẩn hóa về tên CPS):
  • sạc dự phòng / pin sạc / power bank → pin dự phòng
  • tai nghe không dây / tws / earbuds → tai nghe (hoặc tên model nếu có)
  • điện thoại / smartphone / dt → giữ hãng + model
  • mtb / máy tính bảng → tablet hoặc tên iPad/Samsung Tab
  • nckd / nồi chiên không dầu → nồi chiên không dầu
- Viết tắt: ip=iPhone, prm/pm=Pro Max, ss=Samsung, mb=Macbook, hssv=học sinh sinh viên
- Giữ dung lượng (128gb, 256gb), màu (titan, hồng) nếu khách nêu
- Giữ tên hãng Latin (Bear, Sony, Apple, Oppo, Xiaomi...)
- "đăng ký nhận tin" (chờ mở bán) và "đặt trước" (pre-order) là HAI trạng thái KHÁC — KHÔNG đổi sang nhau
- Nếu câu chỉ hỏi danh sách theo trạng thái (đăng ký nhận tin, đặt trước, drop ship…) mà không có tên SP → trả về chuỗi rỗng

Ví dụ:
- "Giá ip 16 pro max 256gb titan tự nhiên" → iPhone 16 Pro Max 256GB Titan Tự Nhiên
- "Sạc dự phòng Anker 10000mah mang lên máy bay" → pin dự phòng Anker 10000mAh
- "Check giá s24 ultra 512gb" → Samsung Galaxy S24 Ultra 512GB
- "SVIP mua iPhone 17prm 256" → iPhone 17 Pro Max 256GB
- "Shop còn iPhone 16 Plus 256 màu hồng" → iPhone 16 Plus 256GB Hồng
- "Gần 288 3 tháng 3 còn iPhone 16 Pro 128 Titan sa mạc" → iPhone 16 Pro 128GB Titan Sa Mạc
- "Trả góp Home Credit iPhone 16 128gb" → iPhone 16 128GB
- "Gói BH VIP rơi vỡ iPhone 16 Pro Max" → iPhone 16 Pro Max
- "Mua nồi chiên tầm 8 lít, giá 600k" → nồi chiên 8 lít
- "Giá macbook neo vàng 512g" → MacBook Neo 512GB Vàng (KHÔNG đổi Neo thành Air/Pro)
- QUAN TRỌNG: Giữ nguyên tên dòng model — MacBook Neo ≠ MacBook Air ≠ MacBook Pro; không suy diễn đổi dòng
- QUAN TRỌNG: câu mới nhắc danh mục/SP khác ngữ cảnh cũ → CHỈ trích từ câu mới, BỎ QUA ngữ cảnh
- Chỉ dùng ngữ cảnh khi câu mới là hỏi tiếp thuần (vd: "còn hàng không", "giá sao") về ĐÚNG SP đang thảo luận"""

CLASSIFY_MESSAGE_PROMPT = """Phân loại tin nhắn gửi tới chatbot tư vấn CellphoneS (cellphones.com.vn — điện thoại, laptop, phụ kiện, giá, KM, tồn kho).

Tin nhắn: {query}

Trả về ĐÚNG MỘT từ (không giải thích, không dấu chấm):
product | off_topic | greeting | thanks | help | clarify

- product: tra cứu/tư vấn SP công nghệ bán tại CellphoneS (giá, KM, tồn, trả góp, BH, so sánh, dùng SP thế nào)
- off_topic: KHÔNG liên quan CellphoneS — thời tiết, thể thao, chính trị, crypto, nấu ăn, bài tập; hỏi tech stack/model AI của bot; nhờ viết code/lập trình; phân tích chủ đề không phải SP CellphoneS
- greeting: chào hỏi
- thanks: cảm ơn, tạm biệt
- help: hỏi bot làm được gì / hướng dẫn
- clarify: quá mơ hồ, thiếu tên SP

Ví dụ:
"giá iPhone 17" → product
"sạc dự phòng mang lên máy bay được không" → product
"bạn dùng công nghệ gì" → off_topic
"viết code python giùm" → off_topic
"phân tích kinh tế VN" → off_topic
"xin chào" → greeting"""


def _serialize_product_data(product_data: dict[str, Any]) -> str:
    """Chuyển dict sản phẩm sang JSON dễ đọc cho model."""
    return json.dumps(product_data, ensure_ascii=False, indent=2)


def _build_analysis_prompt(
    user_question: str,
    product_data: dict[str, Any],
    conversation_context: str = "",
) -> str:
    def _primary_is_unavailable(primary: dict[str, Any]) -> bool:
        try:
            if int(primary.get("stock_available_id") or 0) in (43, 56):
                return True
        except (TypeError, ValueError):
            pass
        status = str(primary.get("stock_status") or "").lower()
        return "hết hàng" in status or "đăng ký nhận tin" in status

    context_section = f"{conversation_context}\n\n" if conversation_context else ""
    shop_stock = product_data.get("shop_stock")
    online_stock = product_data.get("online_stock")
    primary = product_data.get("primary_product") or {}
    scenarios = product_data.get("question_scenarios") or {}
    unavailable_primary = _primary_is_unavailable(primary)
    system = SYSTEM_PROMPT
    if shop_stock or online_stock or primary.get("stock_status"):
        system = f"{system}\n{SHOP_STOCK_PROMPT_ADDON}"
    if (
        scenarios.get("stock_status")
        or scenarios.get("incoming_stock")
        or scenarios.get("shop_stock")
        or primary.get("stock_availability")
        or (online_stock or {}).get("stock_availability")
    ):
        system = f"{system}\n{STOCK_STATUS_PROMPT_ADDON}"
    if scenarios.get("stock_browse") or primary.get("stock_filter_ids"):
        system = f"{system}\n{STOCK_BROWSE_PROMPT_ADDON}"
    if primary.get("budget_browse_list_mode") or scenarios.get("budget_browse"):
        system = f"{system}\n{BUDGET_BROWSE_PROMPT_ADDON}"
    if primary.get("category_filter_list_mode") or scenarios.get("category_filter_browse"):
        system = f"{system}\n{CATEGORY_FILTER_BROWSE_PROMPT_ADDON}"
    if (
        not unavailable_primary
        and (
        primary.get("member_prices")
        or primary.get("promotions")
        or primary.get("promotion_info")
        or primary.get("stock_status")
        or scenarios.get("price_promotion")
        )
    ):
        system = f"{system}\n{MEMBER_PRICE_PROMPT_ADDON}\n{MEMBER_TIER_HINTS}"
    if not unavailable_primary and (product_data.get("trade_promo") or scenarios.get("trade_in")):
        system = f"{system}\n{TRADE_IN_PROMPT_ADDON}"
    if scenarios.get("installment") or product_data.get("installment"):
        system = f"{system}\n{INSTALLMENT_PROMPT_ADDON}\n{INSTALLMENT_SCENARIO_HINTS}"
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
    if product_data.get("product_reviews") or scenarios.get("reviews"):
        system = f"{system}\n{REVIEWS_PROMPT_ADDON}"
    if product_data.get("product_faqs") or scenarios.get("faq_policy"):
        system = f"{system}\n{FAQ_PROMPT_ADDON}"
    if product_data.get("flash_sale") or scenarios.get("flash_sale"):
        system = f"{system}\n{FLASH_SALE_PROMPT_ADDON}"
    if not unavailable_primary and (
        product_data.get("trade_exchange_products") or scenarios.get("trade_in_device")
    ):
        system = f"{system}\n{TRADE_DEVICE_PROMPT_ADDON}"
    if product_data.get("store_locator") or scenarios.get("store_locator"):
        system = f"{system}\n{STORE_LOCATOR_PROMPT_ADDON}"
    if not unavailable_primary and (product_data.get("product_combos") or scenarios.get("combo")):
        system = f"{system}\n{COMBO_PROMPT_ADDON}"
    if product_data.get("color_sibling_variants") or scenarios.get("color_variants"):
        system = f"{system}\n{COLOR_VARIANTS_PROMPT_ADDON}"
    if product_data.get("recommended_products"):
        system = f"{system}\n{RECOMMENDED_PRODUCTS_PROMPT_ADDON}"
    if product_data.get("similar_products"):
        system = f"{system}\n{SIMILAR_PRODUCTS_PROMPT_ADDON}"
    system = f"{system}\n{PRODUCT_DATA_PROMPT_ADDON}"
    try:
        from cps_bot.feedback.feedback_training import build_training_prompt_addon

        training_addon = build_training_prompt_addon()
        if training_addon:
            system = f"{system}{training_addon}"
    except Exception:
        pass
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


_COMPARE_FROM_TO_RE = re.compile(
    r"từ\s+(.+?)\s+lên\s+(.+?)(?:\s+thì|\s+thì có|\s*,|\s*$)",
    re.IGNORECASE,
)
_SWITCH_PRODUCT_RE = re.compile(
    r"(?:đang dùng|dang dung|đang xài|dang xai)\s+(.+?)\s+(?:có nên\s+)?đổi qua\s+(.+?)(?:\s+không|\s*$)",
    re.IGNORECASE,
)


def extract_compare_product_queries(text: str) -> list[str]:
    """
    Tách 2 sản phẩm khi khách so sánh (vd: So sánh S26 Ultra và S25 Ultra).
    Trả [] nếu không phải câu so sánh hoặc không tách được.
    """
    value = (text or "").strip()
    if not value:
        return []
    lower = value.lower()

    from_to = _COMPARE_FROM_TO_RE.search(value)
    if from_to:
        left = _trim_compare_side(from_to.group(1))
        right = _trim_compare_side(from_to.group(2))
        queries = [q for q in (left, right) if q and len(q) >= 3]
        if len(queries) == 2:
            return queries

    switch = _SWITCH_PRODUCT_RE.search(value)
    if switch:
        left = _trim_compare_side(switch.group(1))
        right = _trim_compare_side(switch.group(2))
        queries = [q for q in (left, right) if q and len(q) >= 3]
        if len(queries) == 2:
            return queries

    strict_markers = ("so sánh", "so sanh", " vs ", " vs.", "nên mua", "nen mua", "đổi qua", "doi qua")
    if not any(marker in lower for marker in strict_markers):
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
    return {
        "deepseek": "DeepSeek",
        "byteplus": "BytePlus",
    }.get(LLM_PROVIDER, "Gemini")


def llm_provider_display_name() -> str:
    """Tên hiển thị khi bot đang phân tích (vd: Gemini AI, BytePlus)."""
    labels = {
        "deepseek": "DeepSeek",
        "byteplus": "BytePlus",
    }
    return labels.get(LLM_PROVIDER, "Gemini AI")


def _generate_deepseek_meta(prompt: str) -> tuple[str | None, dict[str, Any]]:
    from cps_bot.llm.deepseek_client import generate_chat

    return generate_chat(prompt)


def _generate_byteplus_meta(prompt: str) -> tuple[str | None, dict[str, Any]]:
    from cps_bot.llm.byteplus_client import generate_chat

    return generate_chat(prompt)


def _generate_with_fallback_meta(prompt: str) -> tuple[str | None, dict[str, Any]]:
    """Gọi LLM (Gemini, DeepSeek hoặc BytePlus); trả text + metadata usage."""
    if LLM_PROVIDER == "deepseek":
        return _generate_deepseek_meta(prompt)
    if LLM_PROVIDER == "byteplus":
        return _generate_byteplus_meta(prompt)

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


_VALID_INTENT_KINDS = frozenset({
    "product", "off_topic", "greeting", "thanks", "help", "clarify",
})


def classify_message_scope(user_text: str) -> str | None:
    """LLM phân loại intent — product vs off_topic vs social."""
    text = (user_text or "").strip()
    if not text:
        return None
    raw = _generate_with_fallback(CLASSIFY_MESSAGE_PROMPT.format(query=text))
    if not raw:
        return None
    kind = raw.strip().lower().split()[0].strip(".,;:\"'")
    if kind in _VALID_INTENT_KINDS:
        return kind
    logger.warning("LLM intent không hợp lệ: %r", raw[:80])
    return None


def _has_cps_search_signal(text: str) -> bool:
    """Câu có dấu hiệu cần tra cứu SP trên CellphoneS."""
    from cps_bot.cps.cps_api import classify_question_scenarios

    lower = (text or "").lower()
    if any(h in lower for h in _PRODUCT_HINTS):
        return True
    if any(classify_question_scenarios(text).values()):
        return True
    if is_budget_browse_query(text) or is_stock_status_browse_query(text):
        return True
    if re.search(r"\b(?:iphone|ipad|galaxy|macbook|redmi|oppo|vivo)\s*\d", lower):
        return True
    return False


_SYNONYM_USAGE_RE = re.compile(
    r"\b(?:"
    r"có thể|co the|được|duoc|nên|nen|dùng|dung|mang|phù hợp|phu hop|"
    r"mang lên|mang len|lên máy bay|len may bay|"
    r"tư vấn|tu van|gợi ý|goi y|nên mua|nen mua"
    r")\b",
    re.IGNORECASE,
)


def _can_skip_llm_keyword_normalize(
    original: str,
    local_keywords: str,
    conversation_context: str = "",
) -> bool:
    """
    Keyword cục bộ đủ tốt — skip LLM normalize (latency).
    Câu mơ hồ / đồng nghĩa / cần expand vẫn trả False.
    """
    if not local_keywords or not _local_keywords_usable(original, local_keywords):
        return False
    if needs_query_expansion(original):
        if _has_abbrev_tokens(original):
            return False
        # Noise giá/tồn đã bóc sạch → keyword cục bộ đủ, skip LLM
        if not (_has_search_noise(original) and not _has_search_noise(local_keywords)):
            return False
    if len((original or "").split()) >= 4 and _SYNONYM_USAGE_RE.search(original):
        return False
    if conversation_context and (
        is_contextual_follow_up(original, conversation_context)
        or is_affirmative_follow_up(original)
    ):
        if not _mentions_new_product(original):
            return False
    return True


def should_llm_normalize_keywords(
    text: str,
    conversation_context: str = "",
) -> bool:
    """
    Dùng LLM chuẩn hóa từ khóa (đồng nghĩa, bỏ ngữ cảnh) thay vì chỉ rule cục bộ.
    """
    if not LLM_KEYWORD_NORMALIZE:
        return False
    t = (text or "").strip()
    if not t:
        return False
    if (
        conversation_context
        and (
            is_contextual_follow_up(t, conversation_context)
            or is_affirmative_follow_up(t)
        )
        and not _mentions_new_product(t)
    ):
        return False
    if references_prior_product(t):
        return False
    if _has_abbrev_tokens(t) or needs_query_expansion(t):
        return True
    if _has_cps_search_signal(t):
        return True
    if len(t.split()) >= 4 and re.search(
        r"\b(?:có thể|co the|được|duoc|nên|nen|dùng|dung|mang|phù hợp|phu hop)\b",
        t,
        re.I,
    ):
        return True
    return False


def _llm_keywords_preserve_model_identity(original: str, keywords: str) -> bool:
    """
    LLM không được đổi dòng/model/danh mục (MacBook Neo → Air, iPhone → Galaxy…).
    """
    from cps_bot.browse.product_lines import (
        product_context_conflict,
        required_model_phrases,
    )
    from cps_bot.browse.product_map import _fold, _tokenize

    if product_context_conflict(original, keywords):
        return False

    orig_f = _fold(original)
    kw_f = _fold(keywords)
    if not orig_f or not kw_f:
        return True

    for phrase in required_model_phrases(original):
        if phrase not in kw_f:
            return False

    distinct = frozenset({"neo", "plus", "ultra", "se", "fold", "flip", "fe", "note"})
    orig_tokens = _tokenize(original)
    for token in distinct:
        if token in orig_tokens and token not in kw_f:
            return False

    if re.search(r"\bmac\s+mini\b", orig_f, re.I) and not re.search(r"\bmac\s+mini\b", kw_f, re.I):
        return False

    return True


def _llm_keywords_acceptable(keywords: str, original: str) -> bool:
    """Chấp nhận keyword từ LLM — kể cả khi đổi đồng nghĩa (sạc dự phòng → pin dự phòng)."""
    if not _llm_keywords_preserve_model_identity(original, keywords):
        logger.warning(
            "LLM keyword bị từ chối — đổi model/dòng: %r → %r",
            original[:80],
            keywords[:80],
        )
        return False
    if _keywords_match_query(keywords, original):
        return True
    kw = (keywords or "").strip().lower()
    if not kw or len(kw) < 2:
        return False
    blocked = (
        "python", "javascript", "typescript", "java ", "golang",
        "thời tiết", "thoi tiet", "bitcoin", "crypto", "bóng đá", "bong da",
    )
    if any(b in kw for b in blocked):
        return False
    if any(h in kw for h in _PRODUCT_HINTS):
        return True
    if _has_cps_search_signal(original) and len(kw.split()) >= 2:
        return True
    return False


def _extract_keywords_via_llm(
    original: str,
    conversation_context: str,
    *,
    new_topic: bool,
) -> str | None:
    use_ctx = (
        conversation_context
        and not new_topic
        and is_contextual_follow_up(original, conversation_context)
    )
    ctx = f"{conversation_context}\n\n" if use_ctx else ""
    prompt = EXTRACT_KEYWORDS_PROMPT.format(context_block=ctx, query=original)
    extracted = _generate_with_fallback(prompt)
    if not extracted:
        return None
    keywords = _normalize_keyword_line(extracted)
    if keywords and _llm_keywords_acceptable(keywords, original):
        logger.info(
            "Từ khóa (%s): %r → %r",
            _llm_provider_label(),
            original,
            keywords,
        )
        return keywords
    if keywords:
        logger.warning(
            "%s keyword bị từ chối: %r → %r",
            _llm_provider_label(),
            original,
            keywords,
        )
    return None


def _tokenize_words(text: str) -> list[str]:
    return re.findall(r"\b[\wđĐ]+", text, flags=re.UNICODE)


_IP_SHORTHAND_RE = re.compile(r"\bip\d{1,2}\b", re.IGNORECASE)
_FOLLOW_UP_QUESTION_TAIL_RE = re.compile(
    r"\b(?:không|khong|gì|sao|nào|nao)\b|\?",
    re.IGNORECASE,
)


def _has_abbrev_tokens(text: str) -> bool:
    """Có từ viết tắt trong từ điển (vd: nckd, ss, ip) hoặc ip15/ip16."""
    if _IP_SHORTHAND_RE.search(text or ""):
        return True
    for word in _tokenize_words(text):
        if word.lower() in _LOCAL_ABBREV:
            return True
    return False


def _replace_abbrev_tokens(text: str) -> str:
    """Thay từng token viết tắt trong câu (vd: nckd bear → nồi chiên không dầu bear)."""
    lower = (text or "").lower()
    parts: list[str] = []
    for word in _tokenize_words(text):
        key = word.lower()
        if key in ("17prm", "16prm", "17pm", "16pm") and re.search(
            r"\b(?:iphone|ip)\b", lower
        ):
            parts.append(f"{key[:2]} pro max")
            continue
        parts.append(_LOCAL_ABBREV.get(key, word))
    return " ".join(parts) if parts else text


def _normalize_model_compounds(text: str) -> str:
    """Chuẩn hóa tên model dính liền: promax → pro max; ip16 → iphone 16."""
    s = text or ""
    s = re.sub(r"\bip(\d{1,2})\b", r"iphone \1", s, flags=re.IGNORECASE)
    for pattern, replacement in _MODEL_COMPOUND_NORMALIZERS:
        s = pattern.sub(replacement, s)
    return re.sub(r"\s+", " ", s).strip()


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
    cleaned = _MEMBER_TIER_PREFIX_RE.sub("", cleaned)
    cleaned = _SHOP_STOCK_PRODUCT_PREFIX_RE.sub("", cleaned)
    cleaned = _SEARCH_PREFIX_RE.sub("", cleaned)
    cleaned = _SHOP_INQUIRY_SUFFIX_RE.sub("", cleaned)
    cleaned = _INCOMING_STOCK_SUFFIX_RE.sub("", cleaned)
    cleaned = _TRADE_CONTEXT_RE.sub(" ", cleaned)
    cleaned = _WARRANTY_CONTEXT_RE.sub(" ", cleaned)
    cleaned = _INSTALLMENT_CONTEXT_RE.sub(" ", cleaned)
    cleaned = _COMBO_CONTEXT_RE.sub(" ", cleaned)
    cleaned = re.sub(
        r"^(?:tìm|tim)\s+(?:cửa hàng|cua hang|shop)\s+(?:gần nhất|gan nhat)\s+"
        r"(?:có đủ|co du|có|có)\s+combo\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(r"^(?:mã|ma)\s+", "", cleaned, flags=re.I)
    cleaned = re.sub(r"^(?:máy|may)\s+", "", cleaned, flags=re.I)
    cleaned = _strip_question_noise(cleaned)
    cleaned = re.sub(r"\s+còn\s*$", "", cleaned, flags=re.I)
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


def _keyword_tokens(text: str) -> set[str]:
    normalized = re.sub(
        r"[^\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]",
        " ",
        (text or "").lower(),
    )
    stop = {
        "mua", "tim", "tìm", "cho", "có", "co", "không", "khong", "và", "va",
        "the", "là", "la", "của", "cua", "một", "mot", "cái", "cai",
    }
    return {
        t
        for t in normalized.split()
        if len(t) >= 2 and t not in stop
    }


def _keywords_match_query(keywords: str, original: str) -> bool:
    """LLM keyword phải liên quan câu mới — tránh hallucinate từ ngữ cảnh cũ."""
    kw = (keywords or "").strip().lower()
    if not kw:
        return False
    orig_lower = (original or "").lower()
    if _budget_category_from_text(original):
        cat = _budget_category_from_text(original)
        if cat and cat in kw:
            return True
    for hint in _PRODUCT_HINTS:
        if hint in orig_lower and hint in kw:
            if not _llm_keywords_preserve_model_identity(original, keywords):
                return False
            return True
    overlap = _keyword_tokens(kw) & _keyword_tokens(original)
    if overlap:
        return True
    if _has_abbrev_tokens(original):
        for word in _tokenize_words(original):
            expanded = _LOCAL_ABBREV.get(word.lower(), "")
            if expanded and any(t in kw for t in expanded.split() if len(t) >= 3):
                return True
    return False


def _local_keywords_usable(original: str, keywords: str) -> bool:
    if not keywords or len(keywords.strip()) < 2:
        return False
    if _has_search_noise(keywords):
        return False
    lower = keywords.lower()
    if any(h in lower for h in _PRODUCT_HINTS):
        return True
    if _budget_category_from_text(original):
        return True
    return bool(_keyword_tokens(keywords) & _keyword_tokens(original))


def _normalize_keyword_line(text: str) -> str:
    """Một dòng từ khóa sạch cho API search."""
    line = text.strip().strip("\"'`").split("\n")[0].strip()
    line = _normalize_model_compounds(line)
    line = _strip_search_noise(line)
    return _normalize_model_compounds(line)


def _mentions_new_product(text: str) -> bool:
    """Câu có nhắc sản phẩm / model mới (khác ngữ cảnh đang thảo luận)."""
    from cps_bot.browse.product_lines import is_inbox_accessory_question, mentions_product_line

    raw = text or ""
    if is_inbox_accessory_question(raw):
        return False
    if is_budget_browse_query(raw):
        return True
    if _has_abbrev_tokens(raw):
        return True
    if mentions_product_line(raw):
        return True
    for candidate in (raw, _normalize_model_compounds(raw)):
        lower = candidate.lower()
        if any(h in lower for h in _PRODUCT_HINTS):
            return True
        if re.search(r"\b(?:iphone|ipad|galaxy|macbook|redmi|oppo|vivo)\s*\d", lower):
            return True
        if re.search(r"\b\d{1,2}\s*(?:pro|plus|ultra|max|prm|pm)\b", lower):
            return True
    return False


def is_installment_only_follow_up(text: str) -> bool:
    """
    Câu chỉ hỏi trả góp/thanh toán, không nhắc tên SP — giữ ngữ cảnh SP session.
    Vd: sau Xiaomi 17T → "hsbc 12 tháng VISA".
    """
    from cps_bot.cps.cps_installment import is_installment_query

    t = (text or "").strip()
    if not t or not is_installment_query(t):
        return False
    if _mentions_new_product(text):
        return False
    lower = t.lower()
    if any(h in lower for h in _PRODUCT_HINTS):
        return False
    if re.search(r"\b(?:iphone|ipad|galaxy|macbook|redmi|oppo|vivo|xiaomi)\s*\d", lower):
        return False
    return True


def _is_follow_up_question(text: str) -> bool:
    """
    Câu hỏi tiếp thuần (vd: "còn hàng không", "giá sao").
    Câu mới có viết tắt / danh mục / mô tả dài → KHÔNG coi là hỏi tiếp.
    """
    from cps_bot.browse.product_lines import is_inbox_accessory_question

    t = text.strip().lower()
    if is_inbox_accessory_question(text):
        return True
    if is_affirmative_follow_up(text):
        return True
    if is_installment_only_follow_up(text):
        return True
    if _has_abbrev_tokens(text):
        return False
    if _mentions_new_product(text):
        return False
    if len(t) > 55 or len(t.split()) > 8:
        return False
    if any(h in t for h in _PRODUCT_HINTS):
        return False

    follow_patterns = (
        "còn hàng", "con hang", "có không", "co khong", "giá sao", "gia sao",
        "giá bán", "gia ban", "màu sắc", "mau sac", "màu gì", "mau gi",
        "màu nào", "mau nao", "màu khác", "mau khac",
        "các màu", "cac mau", "màu của", "mau cua",
        "bao nhiêu", "bn tiền", "cái đó", "cai do", "thế nào", "the nao",
        "so với", "rẻ hơn", "đắt hơn",
        "quà tặng", "qua tang", "khuyến mãi", "khuyen mai", "ưu đãi", "uu dai",
        "tặng gì", "tang gi", "có gì", "co gi", "trả góp", "tra gop",
        "bảo hành", "bao hanh", "đủ không", "du khong", "phù hợp", "phu hop",
        "nên mua", "nen mua", "giảm giá", "giam gia", "pmh", "voucher",
        "có bản", "co ban", "bản 14", "ban 14", "bản 16", "ban 16",
    )
    if any(p in t for p in follow_patterns):
        return True
    return bool(_ATTRIBUTE_FOLLOW_UP_RE.search(text))


def _context_has_product(conversation_context: str) -> bool:
    ctx = conversation_context or ""
    return (
        "Sản phẩm đang thảo luận:" in ctx
        or "Từ khóa tìm gần nhất:" in ctx
    )


def references_prior_product(text: str) -> bool:
    """Câu tham chiếu SP vừa thảo luận (sản phẩm này, cái đó...)."""
    return bool(_PRIOR_PRODUCT_REF_RE.search(text or ""))


def is_affirmative_follow_up(text: str) -> bool:
    """
    Khách đồng ý / nhờ tư vấn tiếp cùng SP (vd: bot hỏi KM/phụ kiện → "có tư vấn đi").
    Không nhắc tên SP mới — chỉ xác nhận ngắn.
    """
    raw = (text or "").strip()
    if not raw:
        return False
    if _mentions_new_product(raw):
        return False
    if references_prior_product(raw):
        return False
    if _ATTRIBUTE_FOLLOW_UP_RE.search(raw):
        return False
    if len(raw.split()) > 6:
        return False
    folded = re.sub(r"[^\w\s]", "", _fold(raw))
    folded = re.sub(r"\s+", " ", folded).strip()
    if not folded:
        return False
    if folded in _AFFIRMATIVE_FOLLOW_UP_EXACT:
        return True
    if folded.startswith("co ") and folded.endswith(" di"):
        return True
    if folded.startswith("tu van ") and folded.endswith(" di"):
        return True
    if re.fullmatch(r"ok(?:\s+(?:nhe|a|di|luon))?", folded):
        return True
    return False


def _fold(text: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


_IPHONE_GEN_RE = re.compile(r"\biphone\s*(\d{1,2})\b", re.IGNORECASE)
_GALAXY_GEN_RE = re.compile(
    r"\b(?:samsung\s+)?galaxy\s*s?(\d{1,2})\b",
    re.IGNORECASE,
)
_STANDALONE_GEN_TIER_RE = re.compile(
    r"\b(\d{1,2})\s*(?:pro\s*max|pro\s*plus|pro|plus|ultra|max|prm|pm|e)\b",
    re.IGNORECASE,
)
_BRAND_HINT_RE = re.compile(
    r"\b(?:iphone|ipad|macbook|galaxy|samsung|xiaomi|redmi|oppo|vivo|realme)\b",
    re.IGNORECASE,
)


def _extract_model_generations(text: str) -> dict[str, set[str]]:
    """Trích thế hệ model theo brand — dùng so khớp ngữ cảnh."""
    value = _normalize_model_compounds(text or "").lower()
    gens: dict[str, set[str]] = {
        "iphone": set(_IPHONE_GEN_RE.findall(value)),
        "galaxy": set(_GALAXY_GEN_RE.findall(value)),
    }
    if not gens["iphone"] and not gens["galaxy"] and _BRAND_HINT_RE.search(value) is None:
        for match in _STANDALONE_GEN_TIER_RE.finditer(value):
            gens.setdefault("standalone", set()).add(match.group(1))
    return {k: v for k, v in gens.items() if v}


def _prior_session_text(last_keywords: str, last_product_name: str) -> str:
    return f"{last_keywords or ''} {last_product_name or ''}".strip()


def _session_hints_from_context(conversation_context: str) -> tuple[str, str]:
    """Trích last_keywords / product_name từ format_context_block."""
    keywords = ""
    product_name = ""
    for line in (conversation_context or "").splitlines():
        if line.startswith("Sản phẩm đang thảo luận:"):
            product_name = line.split(":", 1)[1].strip()
        elif line.startswith("Từ khóa tìm gần nhất:"):
            keywords = line.split(":", 1)[1].strip()
    return keywords, product_name


def _session_conflict(
    text: str,
    *,
    last_keywords: str = "",
    last_product_name: str = "",
    prior_text: str = "",
) -> bool:
    """
    True nếu câu mới xung đột với session (dòng/model/màn hình).
    Gom product_context_conflict + models_conflict + screen_size_conflict.
    """
    query = (text or "").strip()
    if not query:
        return False

    prior = (prior_text or _prior_session_text(last_keywords, last_product_name)).strip()
    session_text = _prior_session_text(last_keywords, last_product_name)

    if prior:
        from cps_bot.browse.product_lines import product_context_conflict

        if product_context_conflict(query, prior):
            return True

    if session_text and models_conflict_with_session(
        query,
        last_keywords=last_keywords,
        last_product_name=last_product_name,
    ):
        return True

    if session_text:
        from cps_bot.cps.cps_api import screen_size_conflicts_with_session

        if screen_size_conflicts_with_session(
            query,
            last_keywords=last_keywords,
            last_product_name=last_product_name,
        ):
            return True

    return False


def models_conflict_with_session(
    text: str,
    *,
    last_keywords: str = "",
    last_product_name: str = "",
) -> bool:
    """
    True nếu câu mới gợi ý model/generation khác session (vd. iphone 17 -> iphone 15).
  """
    from cps_bot.browse.product_lines import product_context_conflict

    query = (text or "").strip()
    prior = _prior_session_text(last_keywords, last_product_name)
    if not query or not prior:
        return False

    if product_context_conflict(query, prior):
        return True

    new_gens = _extract_model_generations(query)
    prior_gens = _extract_model_generations(prior)
    if not new_gens:
        return False

    for brand in ("iphone", "galaxy"):
        if new_gens.get(brand) and prior_gens.get(brand):
            if not (new_gens[brand] & prior_gens[brand]):
                return True

    if new_gens.get("standalone") and prior_gens.get("iphone"):
        if not (new_gens["standalone"] & prior_gens["iphone"]):
            return True

    new_brands = {m.group(0).lower() for m in _BRAND_HINT_RE.finditer(query)}
    prior_brands = {m.group(0).lower() for m in _BRAND_HINT_RE.finditer(prior)}
    if new_brands and prior_brands and not (new_brands & prior_brands):
        if new_gens:
            return True
    return False


def identity_compatible_with_session(
    text: str,
    *,
    last_keywords: str = "",
    last_product_name: str = "",
) -> bool:
    """Fail-safe fetch layer — không pin product_id nếu câu mới lệch model."""
    query = (text or "").strip()
    if not query:
        return False
    if _session_conflict(
        query,
        last_keywords=last_keywords,
        last_product_name=last_product_name,
    ):
        return False
    from cps_bot.cps.cps_api import is_color_variant_query

    if is_color_variant_query(query):
        return True
    if is_affirmative_follow_up(query):
        return True
    if _mentions_new_product(query) and not references_prior_product(query):
        return False
    return True


def should_reuse_product_identity(
    text: str,
    conversation_context: str = "",
    *,
    last_keywords: str = "",
    last_product_name: str = "",
) -> bool:
    """
    Chỉ reuse product_id/url session khi chắc chắn đang hỏi tiếp cùng SP.
    Khác với reuse keyword ngữ cảnh — chặt hơn để tránh pin nhầm model.
    """
    query = (text or "").strip()
    prior = _prior_session_text(last_keywords, last_product_name)
    if not query or not prior:
        return False

    if _session_conflict(
        query,
        last_keywords=last_keywords,
        last_product_name=last_product_name,
    ):
        return False

    from cps_bot.cps.cps_api import is_color_variant_query

    if is_color_variant_query(query):
        return True

    if references_prior_product(query):
        return True

    if is_affirmative_follow_up(query):
        return True

    if is_installment_only_follow_up(query):
        return True

    if _mentions_new_product(query):
        return False

    if is_contextual_follow_up(query, conversation_context):
        return True

    return False


def try_color_follow_up_search_keywords(
    user_question: str,
    *,
    last_keywords: str = "",
    last_product_name: str = "",
    conversation_context: str = "",
) -> str | None:
    """Follow-up hỏi màu — reuse keyword session, skip LLM router/extract."""
    from cps_bot.cps.cps_api import is_color_variant_list_query

    text = (user_question or "").strip()
    if not text or not is_color_variant_list_query(text):
        return None

    kw = (last_keywords or "").strip()
    pname = (last_product_name or "").strip()
    if not kw and conversation_context:
        return _reuse_keywords_from_context(text, conversation_context)

    if not kw:
        return None
    if not identity_compatible_with_session(
        text,
        last_keywords=kw,
        last_product_name=pname,
    ):
        return None
    logger.info("Từ khóa (follow-up màu): %r → %r", text, kw)
    return kw


def _try_reuse_context_keywords(
    original: str,
    conversation_context: str,
) -> str | None:
    from cps_bot.browse.product_lines import context_product_text, product_context_conflict

    if not conversation_context or not _context_has_product(conversation_context):
        return None
    ctx_product = context_product_text(conversation_context)
    if product_context_conflict(original, ctx_product):
        return None
    from cps_bot.cps.cps_api import is_color_variant_query

    if is_color_variant_query(original):
        reused = _reuse_keywords_from_context(original, conversation_context)
        if reused:
            return reused
    if references_prior_product(original):
        return _reuse_keywords_from_context(original, conversation_context)
    if is_affirmative_follow_up(original):
        return _reuse_keywords_from_context(original, conversation_context)
    if _mentions_new_product(original):
        return None
    if is_contextual_follow_up(original, conversation_context):
        return _reuse_keywords_from_context(original, conversation_context)
    return None


def is_contextual_follow_up(
    text: str,
    conversation_context: str = "",
) -> bool:
    """
    Câu hỏi tiếp trong cùng chủ đề SP (kể cả hỏi quà tặng/KM mà không nhắc tên SP).
    """
    from cps_bot.browse.product_lines import context_product_text

    if is_budget_browse_query(text):
        return False
    if not _context_has_product(conversation_context):
        return False
    ctx_product = context_product_text(conversation_context)
    kw, pname = _session_hints_from_context(conversation_context)
    if _session_conflict(
        text,
        last_keywords=kw,
        last_product_name=pname,
        prior_text=ctx_product or pname,
    ):
        return False
    from cps_bot.cps.cps_api import is_color_variant_query

    if is_color_variant_query(text):
        return True
    if is_affirmative_follow_up(text):
        return True
    if is_installment_only_follow_up(text):
        return True
    if _mentions_new_product(text):
        return False
    if references_prior_product(text):
        return True
    if _is_follow_up_question(text):
        return True

    t = text.strip().lower()
    if _has_abbrev_tokens(text):
        return False
    if len(t) > 80:
        return False

    if len(t.split()) <= 10 and _FOLLOW_UP_QUESTION_TAIL_RE.search(t):
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
        merged = merge_follow_up_variant_into_keywords(keywords, original)
        logger.info("Từ khóa (ngữ cảnh): %r → %r", original, merged)
        return merged
    if product_name:
        merged = merge_follow_up_variant_into_keywords(product_name, original)
        logger.info("Từ khóa (SP ngữ cảnh): %r → %r", original, merged)
        return merged
    return None


def extract_search_keywords(
    user_text: str,
    conversation_context: str = "",
    *,
    use_llm: bool = True,
) -> str:
    """
    Bóc tách từ khóa sản phẩm từ câu khách — chỉ chuỗi này được gửi API CellphoneS.
    Luôn ưu tiên câu mới; chỉ reuse ngữ cảnh khi hỏi tiếp thuần.
    """
    original = user_text.strip()
    if not original:
        return ""

    from cps_bot.browse.product_term_synonyms import normalize_product_terms

    original = normalize_product_terms(original)

    if is_stock_status_browse_query(original):
        keywords = strip_stock_browse_phrases_for_keywords(original)
        logger.info("Từ khóa (stock browse): %r → %r", original, keywords)
        return keywords

    if is_color_variant_list_query(original):
        keywords = strip_color_variant_list_phrases_for_keywords(original)
        keywords = _normalize_keyword_line(
            _strip_search_noise(_replace_abbrev_tokens(keywords))
        ) if keywords else keywords
        if keywords:
            logger.info("Từ khóa (color list): %r → %r", original, keywords)
            return keywords

    from cps_bot.cps.cps_api import is_combo_accessory_query

    if is_combo_accessory_query(original):
        keywords = _normalize_keyword_line(
            _strip_search_noise(_replace_abbrev_tokens(original))
        )
        if keywords:
            logger.info("Từ khóa (combo/phụ kiện): %r → %r", original, keywords)
            return keywords

    from cps_bot.browse.category_filter_browse import (
        build_category_filter_url,
        is_category_filter_browse_query,
        resolve_category_filter_request,
        resolve_filter_price,
    )

    if is_category_filter_browse_query(original):
        req = resolve_category_filter_request(original)
        if req:
            filter_url = build_category_filter_url(req, resolve_filter_price(original))
            logger.info("Từ khóa (category filter): %r → %r", original, filter_url)
            return filter_url

    if is_budget_browse_query(original):
        keywords = strip_budget_phrases_for_keywords(original)
        logger.info("Từ khóa (budget browse): %r → %r", original, keywords)
        return keywords

    color_session_kw = try_color_follow_up_search_keywords(
        original,
        conversation_context=conversation_context,
    )
    if color_session_kw:
        return color_session_kw

    if conversation_context and is_affirmative_follow_up(original):
        reused = _try_reuse_context_keywords(original, conversation_context)
        if reused:
            return reused

    new_topic = _mentions_new_product(original)

    reused = _try_reuse_context_keywords(original, conversation_context)
    if reused:
        return reused

    if needs_shop_stock_keyword_strip(original):
        keywords = strip_shop_stock_phrases_for_keywords(original)
        keywords = _normalize_keyword_line(
            _replace_abbrev_tokens(keywords)
        ) if keywords else keywords
        logger.info("Từ khóa (shop stock): %r → %r", original, keywords)
        return keywords

    local_keywords = _normalize_keyword_line(
        _strip_usage_context(_strip_search_noise(_replace_abbrev_tokens(original)))
    )

    local_full = _LOCAL_ABBREV.get(original.lower())
    if local_full:
        local_keywords = _normalize_keyword_line(local_full)

    if _has_abbrev_tokens(original) and local_keywords:
        logger.info("Từ khóa (từ điển): %r → %r", original, local_keywords)
        return local_keywords

    if _can_skip_llm_keyword_normalize(original, local_keywords, conversation_context):
        logger.info("Từ khóa (bóc cục bộ, skip LLM): %r → %r", original, local_keywords)
        return local_keywords

    if use_llm and should_llm_normalize_keywords(original, conversation_context):
        llm_kw = _extract_keywords_via_llm(
            original,
            conversation_context,
            new_topic=new_topic,
        )
        if llm_kw:
            return llm_kw

    if _local_keywords_usable(original, local_keywords):
        logger.info("Từ khóa (bóc cục bộ): %r → %r", original, local_keywords)
        return local_keywords

    if not needs_query_expansion(original) and local_keywords and not _has_search_noise(local_keywords):
        if not references_prior_product(original):
            logger.info("Từ khóa (câu rõ): %r → %r", original, local_keywords)
            return local_keywords

    reused = _try_reuse_context_keywords(original, conversation_context)
    if reused:
        return reused

    # LLM fallback (câu viết tắt / không dấu / chưa qua bước normalize ở trên)
    if use_llm:
        llm_kw = _extract_keywords_via_llm(
            original,
            conversation_context,
            new_topic=new_topic,
        )
        if llm_kw:
            return llm_kw

    if local_keywords:
        logger.info("Từ khóa (fallback cục bộ): %r → %r", original, local_keywords)
        return local_keywords

    fallback = _normalize_keyword_line(original) or original
    logger.info("Từ khóa (fallback câu gốc): %r → %r", original, fallback)
    return fallback


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
