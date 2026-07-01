"""
Client GraphQL CellphoneS (CPS) — resolve URL → product_id → chi tiết sản phẩm.
"""
from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from config import (
    CPS_API_BASE_URL,
    CPS_GRAPHQL_DASHBOARD_ENDPOINT,
    CPS_GRAPHQL_URL_ENDPOINT,
    CPS_GRAPHQL_V2_ENDPOINT,
    CPS_GRAPHQL_V2_PRODUCTION,
    CPS_PROVINCE_ID,
    CPS_RECOMMENDATION_ENABLED,
    CPS_RECOMMENDATION_MAX_PRODUCTS,
    PRODUCT_MAP_PATH,
    SERPAPI_API_KEY,
    SERPAPI_ENABLED,
    SERPAPI_ENDPOINT,
    SERPAPI_FALLBACK_TO_CPS_SEARCH,
)
from cps_bot.browse.budget_browse import (
    filter_results_by_budget,
    is_budget_browse_query,
    parse_budget_constraint,
    strip_budget_phrases_for_keywords,
)
from cps_bot.cps.scraper import (
    _format_price,
    _full_url,
    graphql_product_url,
    normalize_search_result,
    normalize_search_results,
    product_url_from_record,
    search_products,
    search_results_need_advanced,
)

logger = logging.getLogger(__name__)

CELLPHONES_URL_RE = re.compile(
    r"https?://(?:www\.)?cellphones\.com\.vn/[^\s<>\"']+\.html",
    re.IGNORECASE,
)

# Kho online / depot — loại khỏi danh sách cửa hàng trưng bày (theo cps-nuxt-standard)
ONLINE_SHOP_EXTERNAL_IDS = frozenset({1280, 1281, 103, 156})

from cps_bot.cps.cps_provinces import (
    PROVINCE_COMPANY_ID,
    PROVINCE_ID_TO_NAME,
    PROVINCE_NAME_ALIASES,
    company_id_for_province,
    province_name,
    resolve_province_from_text,
)

# stock_available_id — cps-nuxt-standard/helper/function/constants/stock-available.js
STOCK_AVAILABLE_OUT_OF_STOCK = 43
STOCK_AVAILABLE_IN_STOCK = 46
STOCK_AVAILABLE_SUBSCRIPTION = 56
STOCK_AVAILABLE_PRE_ORDER = 152
STOCK_AVAILABLE_DROP_SHIPPING = 4164
STOCK_AVAILABLE_VIRTUAL_STOCK = 4920

STOCK_STATUS_CODES: dict[int, str] = {
    STOCK_AVAILABLE_OUT_OF_STOCK: "out_of_stock",
    STOCK_AVAILABLE_IN_STOCK: "in_stock",
    STOCK_AVAILABLE_SUBSCRIPTION: "subscription",
    STOCK_AVAILABLE_PRE_ORDER: "pre_order",
    STOCK_AVAILABLE_DROP_SHIPPING: "drop_shipping",
    STOCK_AVAILABLE_VIRTUAL_STOCK: "virtual_stock",
}

STOCK_STATUS_LABELS_VI: dict[int, str] = {
    STOCK_AVAILABLE_OUT_OF_STOCK: "Hết hàng",
    STOCK_AVAILABLE_IN_STOCK: "Còn hàng",
    STOCK_AVAILABLE_SUBSCRIPTION: "Đăng ký nhận tin",
    STOCK_AVAILABLE_PRE_ORDER: "Đặt trước",
    STOCK_AVAILABLE_DROP_SHIPPING: "Còn hàng (Drop shipping)",
    STOCK_AVAILABLE_VIRTUAL_STOCK: "Còn hàng online",
}

UNAVAILABLE_STOCK_IDS: tuple[int, ...] = (
    STOCK_AVAILABLE_OUT_OF_STOCK,
    STOCK_AVAILABLE_SUBSCRIPTION,
)

# SP có thể mua / đặt qua web (không gồm hết hàng & đăng ký nhận tin)
STOCK_BUYABLE_IDS = frozenset({
    STOCK_AVAILABLE_IN_STOCK,
    STOCK_AVAILABLE_PRE_ORDER,
    STOCK_AVAILABLE_DROP_SHIPPING,
    STOCK_AVAILABLE_VIRTUAL_STOCK,
})

# Filter danh mục GraphQL — SP còn bán / đặt trước / tồn ảo / drop ship
CATEGORY_LISTABLE_STOCK_IDS = [
    STOCK_AVAILABLE_IN_STOCK,
    STOCK_AVAILABLE_PRE_ORDER,
    STOCK_AVAILABLE_VIRTUAL_STOCK,
    STOCK_AVAILABLE_DROP_SHIPPING,
]

_ACCESSORY_PATH_HINTS = (
    "op-lung", "op lung", "bao-da", "kinh-cuong-luc", "mieng-dan", "cap-", "sac-",
    "tai-nghe", "chuot-", "ban-phim",
)

_PAGE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9",
}

_PRICE_QUESTION_RE = re.compile(
    r"\b("
    r"giá|gia|bao nhiêu|bao nhieu|giảm|giam|khuyến mãi|khuyen mai|"
    r"ưu đãi|uu dai|voucher|pmh|kredivo|vib|vnpay|quẹt thẻ|quet the|"
    r"hssv|học sinh|hoc sinh|sinh viên|sinh vien|svip|s-member|smember|"
    r"giá cuối|gia cuoi|trợ giá|tro gia"
    r")\b",
    re.IGNORECASE,
)
_TRADE_IN_QUESTION_RE = re.compile(
    r"\b("
    r"thu cũ|thu cu|trade[- ]?in|đổi mới|doi moi|lên đời|len doi|"
    r"trợ giá thu cũ|tro gia thu cu|đổi máy|doi may|máy cũ|may cu"
    r")\b",
    re.IGNORECASE,
)
_INSTALLMENT_QUESTION_RE = re.compile(
    r"\b("
    r"trả góp|tra gop|trả trước|tra truoc|gói trả góp|goi tra gop|"
    r"home credit|homecredit|kredivo|fundiin|mcredit|fecredit|"
    r"cttc|"
    r"kỳ hạn|ky han|"
    r"miễn lãi|mien lai|chuyển đổi trả góp|chuyen doi tra gop|"
    r"thẻ tín dụng|the tin dung|techcombank|tcb|alepay|onepay|"
    r"vib|vnpay|hsbc|bidv|vietcombank|vcb|acb|vpbank|tpbank|msb|eximbank|vietinbank|"
    r"visa|mastercard|jcb|amex|american express|"
    r"mua trước trả sau|mua truoc tra sau|"
    r"momo vts|"
    r"hd saison|hd-saison|shinhan|lotte finance|mirae|acs|jaccs|"
    r"lãi suất|lai suat|phí chuyển đổi|phi chuyen doi|"
    r"trả góp 0%|tra gop 0%|0 phan tram|lãi 0|lai 0|"
    r"thẻ visa|the visa|mastercard|thẻ mb|the mb|the vib|the tcb"
    r")\b",
    re.IGNORECASE,
)
_WARRANTY_QUESTION_RE = re.compile(
    r"\b("
    r"bảo hành|bao hanh|apple care|applecare|đổi trả|doi tra|"
    r"đổi mới|1 đổi 1|hoàn tiền|hoan tien|gói bảo hành|goi bao hanh|"
    r"rơi vỡ|roi vo|vip"
    r")\b",
    re.IGNORECASE,
)
_COMPARE_QUESTION_RE = re.compile(
    r"\b(so sánh|so sanh|vs\.?|với|voi|khác biệt|khac biet|nên mua|nen mua|đổi qua|doi qua)\b",
    re.IGNORECASE,
)
_SPECS_QUESTION_RE = re.compile(
    r"\b("
    r"thông số|thong so|spec|megapixel|mp|hz|pin|sạc|sac|watt|w\b|"
    r"tương thích|tuong thich|dùng chung|dung chung|apple pencil|"
    r"card đồ họa|card do hoa|chip|camera|zoom"
    r")\b",
    re.IGNORECASE,
)
_ADVICE_QUESTION_RE = re.compile(
    r"\b("
    r"tư vấn|tu van|chọn|chon|phân vân|phan van|tầm giá|tam gia|"
    r"mua tặng|mua tang|phù hợp|phu hop|nên|nen"
    r")\b",
    re.IGNORECASE,
)
_REVIEWS_QUESTION_RE = re.compile(
    r"\b("
    r"review|đánh giá|danh gia|rating|"
    r"review sao|mấy sao|may sao|bao nhiêu sao|bao nhieu sao|"
    r"có tốt không|co tot khong|"
    r"người dùng nói|nguoi dung noi|feedback"
    r")\b",
    re.IGNORECASE,
)
_FAQ_POLICY_RE = re.compile(
    r"\b("
    r"chính sách|chinh sach|đổi trả|doi tra|"
    r"1 đổi 1|hoàn tiền|hoan tien|"
    r"quy định|quy dinh|faq"
    r")\b",
    re.IGNORECASE,
)
_FLASH_SALE_RE = re.compile(
    r"\b("
    r"flash sale|flashsale|giá sốc|gia soc|"
    r"sale giờ vàng|khung giờ|slot"
    r")\b",
    re.IGNORECASE,
)
_TRADE_DEVICE_RE = re.compile(
    r"\b("
    r"máy cũ thu|may cu thu|thu máy|thu may|"
    r"iphone \d+ cũ|thu bao nhiêu|thu bao nhieu|"
    r"giá thu|gia thu|thu loại|thu loai"
    r")\b",
    re.IGNORECASE,
)
_STORE_LOCATOR_RE = re.compile(
    r"\b("
    r"cửa hàng ở|cua hang o|shop ở|shop o|"
    r"địa chỉ shop|dia chi shop|"
    r"giờ mở cửa|gio mo cua|"
    r"cellphones ở|cellphones o|"
    r"danh sách shop|danh sach shop|"
    r"có mấy shop|co may shop"
    r")\b",
    re.IGNORECASE,
)
_COMBO_QUESTION_RE = re.compile(
    r"\b("
    r"combo|mua kèm|mua kem|"
    r"mua thêm giảm|mua them giam|"
    r"bundle|cross[- ]?sell"
    r")\b",
    re.IGNORECASE,
)
_INCOMING_STOCK_RE = re.compile(
    r"\b(hàng về|hang ve|khi nào về|khi nao ve|bao giờ về|bao gio ve|"
    r"pre[- ]?order|đặt trước|dat truoc)\b",
    re.IGNORECASE,
)
_STOCK_STATUS_QUESTION_RE = re.compile(
    r"\b("
    r"còn hàng|con hang|hết hàng|het hang|tạm hết|tam het|"
    r"hết hàng chưa|het hang chua|"
    r"có hàng|co hang|"
    r"còn máy|con may|còn con|con con|"
    r"còn bán|con ban|còn sale|con sale|"
    r"còn không|con khong|có không|co khong|"
    r"còn ko|con ko|còn k\b|con k\b|co ko|co k\b|"
    r"tình trạng hàng|tinh trang hang|trạng thái hàng|trang thai hang|"
    r"có bán không|co ban khong|có hàng không|co hang khong|"
    r"out of stock|in stock|"
    r"đăng ký nhận tin|dang ky nhan tin|"
    r"đặt trước được|dat truoc duoc|mua được không|mua duoc khong|"
    r"lấy được|lay duoc|nhận tại shop|nhan tai shop|lấy tại shop|lay tai shop|"
    r"check tồn|check stock|kiểm tra tồn|kiem tra ton|"
    r"tồn kho|ton kho|tồn tại|ton tai"
    r")\b",
    re.IGNORECASE,
)
_DISTRICT_STOCK_INTENT_RE = re.compile(
    r"\b(?:có|co|còn|con)\s+h[àa]ng\b",
    re.IGNORECASE,
)
# "còn iphone không", "shop quận 1 còn máy không" — có từ xen giữa còn/có và không
_DISTRICT_TAIL_AVAILABILITY_RE = re.compile(
    r"\b(?:còn|co|có|con)\b.+\b(?:không|khong|ko|k)\??\s*$",
    re.IGNORECASE,
)
_SHOP_DISTRICT_STOCK_RE = re.compile(
    r"\b(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\b"
    r".+\b(?:quận|quan|q\.?\s*\d{1,2}|q\d{1,2})\b",
    re.IGNORECASE,
)
_COLOR_VARIANT_LIST_RE = re.compile(
    r"\b("
    r"màu nào khác|mau nao khac|"
    r"màu khác|mau khac|"
    r"còn màu khác|con mau khac|"
    r"có màu khác|co mau khac|"
    r"còn màu nào|con mau nao|"
    r"các màu|cac mau|"
    r"màu của|mau cua|"
    r"những màu nào|nhung mau nao|"
    r"những màu|nhung mau|"
    r"danh sách màu|danh sach mau|"
    r"liệt kê màu|liet ke mau|"
    r"màu gì còn|mau gi con|"
    r"có màu nào|co mau nao|"
    r"màu sắc nào|mau sac nao|"
    r"màu sắc|mau sac|"
    r"còn tồn.*màu|con ton.*mau|"
    r"màu nào còn|mau nao con|"
    r"còn những màu|con nhung mau"
    r")\b",
    re.IGNORECASE,
)
_STOCK_STATUS_CHECK_ONLY_RE = re.compile(
    r"còn hàng không|co hang khong|có hàng không|"
    r"hết hàng chưa|het hang chua|"
    r"tình trạng hàng|trang thai hang|"
    r"có bán không|co ban khong|mua được không|mua duoc khong",
    re.IGNORECASE,
)

_STOCK_BROWSE_KEYWORD_STRIP_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"đăng ký nhận tin|dang ky nhan tin", re.I),
    re.compile(r"đặt trước|dat truoc|pre[- ]?order", re.I),
    re.compile(r"drop\s*ship(?:ping)?", re.I),
    re.compile(r"tồn ảo|ton ao|virtual\s*stock", re.I),
    re.compile(
        r"các sản phẩm|cac san pham|danh sách|danh sach|ds\s|list\s|"
        r"sản phẩm|san pham|mặt hàng|mat hang",
        re.I,
    ),
    re.compile(
        r"(?:đang\s+)?hết hàng|(?:đang\s+)?het hang|"
        r"(?:đang\s+)?còn hàng|(?:đang\s+)?con hang",
        re.I,
    ),
    re.compile(
        r"tìm|tim|xem|cho mình|cho minh|giúp mình|giup minh|"
        r"liệt kê|liet ke|show|gợi ý|goi y",
        re.I,
    ),
)

_STOCK_ID_FROM_TEXT: list[tuple[re.Pattern[str], int]] = [
    (
        re.compile(r"đặt trước|dat truoc|pre[- ]?order", re.I),
        STOCK_AVAILABLE_PRE_ORDER,
    ),
    (
        re.compile(r"đăng ký nhận tin|dang ky nhan tin", re.I),
        STOCK_AVAILABLE_SUBSCRIPTION,
    ),
    (
        re.compile(r"drop\s*ship(?:ping)?", re.I),
        STOCK_AVAILABLE_DROP_SHIPPING,
    ),
    (
        re.compile(r"tồn ảo|ton ao|virtual\s*stock", re.I),
        STOCK_AVAILABLE_VIRTUAL_STOCK,
    ),
    (
        re.compile(
            r"(?:sản phẩm|san pham|máy|may|hàng|hang)\s+(?:đang\s+)?hết hàng|"
            r"(?:danh sách|ds|list)\s+hết hàng|(?:danh sách|ds)\s+het hang",
            re.I,
        ),
        STOCK_AVAILABLE_OUT_OF_STOCK,
    ),
    (
        re.compile(
            r"(?:sản phẩm|san pham|máy|may|hàng|hang)\s+(?:đang\s+)?còn hàng|"
            r"(?:danh sách|ds|list)\s+còn hàng|(?:danh sách|ds)\s+con hang",
            re.I,
        ),
        STOCK_AVAILABLE_IN_STOCK,
    ),
]
_SHOP_STOCK_QUESTION_RE = re.compile(
    r"\b("
    r"cửa hàng|cua hang|chi nhánh|chi nhanh|cn nào|cn nao|"
    r"shop nào|shop nao|shop mình|shop minh|shop còn|shop con|"
    r"ở đâu còn|o dau con|gần đây|gan day|lân cận|lan can|"
    r"gần tôi|gan toi|gần mình|gan minh|gần nhất|gan nhat|"
    r"cửa hàng gần|cua hang gan|shop gần|shop gan|"
    r"xem chi nhánh|co hang o|hàng ở đâu|hang o dau|"
    r"mua ở đâu|mua o dau|lấy ở đâu|lay o dau|"
    r"còn ở shop|còn shop|con shop|shop nào còn|shop nao con|"
    r"còn tồn|con ton|"
    r"tồn kho|ton kho|tồn tại|ton tai|kiểm tra tồn|kiem tra ton|"
    r"nhận tại shop|nhan tai shop|pickup|pick up"
    r")\b",
    re.IGNORECASE,
)
_NEAR_STREET_RE = re.compile(
    r"(?:gần|gan)\s+"
    r"(\d{1,4}\s+[\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ/.\s-]{2,45}?)"
    r"(?:\s+(?:có|co|còn|con|shop|tìm|tim)\b|[?.!,]|$)",
    re.IGNORECASE,
)
_DISTRICT_HINT_RE = re.compile(
    r"(?:gần|gan\s+)?"
    r"(quận|quan|huyện|huyen|phường|phuong)\s+"
    r"(\d{1,2}|[\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]{2,20})"
    r"(?=\s+(?:shop|có|co|còn|con|ở|o|tìm|tim|không|khong)\b|[?.!,]|\s|$)",
    re.IGNORECASE,
)
# Quận/huyện không cần theo sau bởi "shop/còn" — vd. "tồn kho tại Quận 10 HCM"
_DISTRICT_HINT_LOOSE_RE = re.compile(
    r"\b(quận|quan|huyện|huyen|phường|phuong)\s+(\d{1,2})\b",
    re.IGNORECASE,
)
# Hỏi tiếp ngắn theo quận: "ở quận 10 có không?", "Q10 còn không"
_DISTRICT_AVAILABILITY_RE = re.compile(
    r"\b(có|co|còn|con)\s*(?:hàng|hang\s+)?(?:không|khong|ko|k)\b",
    re.IGNORECASE,
)
# Q.9, Q9, q5 — cách viết phổ biến trên địa chỉ shop CellphoneS
_DISTRICT_ABBREV_RE = re.compile(
    r"\b[qQ]\.?\s*(\d{1,2})\b|\b[qQ](\d{1,2})\b",
)
_WARD_ABBREV_RE = re.compile(
    r"\b[pP]\.?\s*([\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]{2,30})\b",
)

SHOPS_STOCK_QUERY = """
query SHOP_STOCK($productId: Int!, $provinceId: Int!) {
  shops_stock(productId: $productId, provinceId: $provinceId) {
    district_id
    district_name
    province_id
    province_name
    shops {
      id
      external_id
      district_id
      province_id
      address
      phone
      near
      google_link
    }
  }
}
"""

URL_INFO_QUERY = """
query URL_INFO($path: String!) {
  url_info(request_path: $path) {
    id
    category_id
    product_id
  }
}
"""

PRODUCT_DETAIL_QUERY = """
query getProductDataDetail($id: ID!, $provinceId: Int!) {
  product(id: $id, provinceId: $provinceId) {
    general {
      attributes
      name
      child_product
      parent_id
      relation
      related_name
      url_path
      product_id
      sku
      manufacturer
      up_sell
      categories {
        categoryId
        name
        uri
        level
      }
    }
    filterable {
      short_name
      promotion_information
      promotion_pack
      price
      prices
      special_price
      thumbnail
      product_state
      short_description
      stock
      stock_available_id
      company_stock_id
      company_stock_quantity
      display_price
      promotion_info
      product_condition
      included_accessories
      warranty_information
      member_promotion
      is_installment
      default {
        product_id
      }
    }
    specification {
      basic
      full_by_group
    }
  }
}
"""

TRADE_PROMO_QUERY = """
query tradePromo($productId: Int!, $categoryIds: [String!]!, $companyId: Int!) {
  trade_promo(
    productId: $productId
    categoryIds: $categoryIds
    companyId: $companyId
  ) {
    product_id
    promo_value
    pmh
  }
}
"""

EXTENDED_WARRANTY_QUERY = """
query warranty($productId: Int!, $categories: [Int!]!, $productPrice: Float!) {
  extended_warranty(
    warranty_product: {
      product_id: $productId
      categories: $categories
      product_price: $productPrice
    }
  ) {
    product_id
    warranty_url
    warranty_packs {
      pack_id
      pack_code
      pack_title
      pack_tooltip
      value
    }
  }
}
"""

INSTOCK_PROVINCES_QUERY = """
query InstockProvince($productId: Int!, $companyId: Int!) {
  instock_provinces(product_id: $productId, company_id: $companyId) {
    id
  }
}
"""

PRODUCTS_BY_CATEGORY_QUERY = """
query GetProductsByCateId($cateId: String!, $provinceId: Int!, $size: Int!, $page: Int!) {
  products(
    filter: {
      static: {
        categories: [$cateId],
        province_id: $provinceId,
        stock: { from: 1 },
        company_stock_id: [46, 152, 4920, 4164]
      }
    },
    page: $page,
    size: $size,
    sort: [{view: desc}]
  ) {
    general {
      product_id
      name
      sku
      manufacturer
      url_key
      url_path
      categories {
        categoryId
        name
        uri
      }
    }
    filterable {
      stock_available_id
      stock
      price
      special_price
      display_price
      promotion_information
      thumbnail
      short_description
      product_state
      promotion_info
    }
  }
}
"""

PRODUCTS_BY_STOCK_QUERY_TEMPLATE = """
query GetProductsByStockId($provinceId: Int!, $size: Int!, $page: Int!) {
  products(
    filter: {
      static: {
        province_id: $provinceId,
        stock: { from: 1 },
        company_stock_id: __COMPANY_STOCK_IDS__
      }
    },
    page: $page,
    size: $size,
    sort: [{view: desc}]
  ) {
    general {
      product_id
      name
      sku
      manufacturer
      url_key
      url_path
      categories {
        categoryId
        name
        uri
      }
    }
    filterable {
      stock_available_id
      stock
      price
      special_price
      display_price
      promotion_information
      thumbnail
      short_description
      product_state
      promotion_info
    }
  }
}
"""


def _build_products_by_stock_query(company_stock_ids: list[int]) -> str:
    """Render query products theo company_stock_id dạng literal để tránh lỗi variable type."""
    ids_literal = "[" + ", ".join(str(int(i)) for i in company_stock_ids) + "]"
    return PRODUCTS_BY_STOCK_QUERY_TEMPLATE.replace("__COMPANY_STOCK_IDS__", ids_literal)


def extract_cellphones_urls(text: str) -> list[str]:
    return CELLPHONES_URL_RE.findall(text or "")


def _is_cellphones_product_url(url: str) -> bool:
    value = (url or "").strip()
    return bool(CELLPHONES_URL_RE.fullmatch(value))


def _serp_url_score(url: str) -> int:
    """
    Chấm điểm URL Serp để ưu tiên URL SKU trước danh mục.
    Điểm cao hơn = thử resolve trước.
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()
    if not path.endswith(".html"):
        return -100

    score = 0
    # Root product path thường chính xác nhất: /<slug>.html
    if "/" not in path:
        score += 100
    else:
        score -= 20

    # Penalize các URL thường là danh mục/filter
    noisy_parts = (
        "catalogsearch",
        "nha-thong-minh",
        "may-hut-bui",
        "robot-hut-bui",
        "dien-thoai",
        "laptop",
    )
    if any(part in path for part in noisy_parts):
        score -= 40

    # Ưu tiên URL có slug dài (thường là SKU cụ thể hơn)
    score += min(len(path), 80) // 10
    return score


def extract_request_path(url_or_path: str) -> str:
    """Chuẩn hóa URL/path thành request_path cho url_info API."""
    value = (url_or_path or "").strip()
    if not value:
        return ""
    if value.startswith("http"):
        path = urlparse(value).path
    else:
        path = value if value.startswith("/") else f"/{value}"
    return path.lstrip("/")


def _keyword_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9đ]+", (text or "").lower()))


def _strip_html(value: str) -> str:
    if not value:
        return ""
    if "<" not in value:
        return unescape(value).strip()
    return BeautifulSoup(value, "lxml").get_text(" ", strip=True)


def _parse_specifications(specification: dict[str, Any] | None) -> dict[str, str]:
    specs: dict[str, str] = {}
    if not specification:
        return specs

    for item in specification.get("basic") or []:
        if not isinstance(item, dict):
            continue
        label = _strip_html(str(item.get("label") or ""))
        value = _strip_html(str(item.get("value") or ""))
        if label and value:
            specs[label] = value

    for group in specification.get("full_by_group") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("value") or []:
            if not isinstance(item, dict):
                continue
            label = _strip_html(str(item.get("label") or ""))
            value = _strip_html(str(item.get("value") or ""))
            if label and value:
                specs[label] = value
    return specs


def parse_stock_availability(filterable: dict[str, Any]) -> dict[str, Any]:
    """
    Chuẩn hóa trạng thái SP từ GraphQL filterable (stock_available_id + stock + product_state).
    Tham chiếu stock-available.js trên frontend CellphoneS.
    """
    product_state = _strip_html(str(filterable.get("product_state") or ""))

    said: int | None = None
    try:
        if filterable.get("stock_available_id") is not None:
            said = int(filterable["stock_available_id"])
    except (TypeError, ValueError):
        said = None

    stock_qty: int | None = None
    if filterable.get("stock") is not None:
        try:
            stock_qty = int(filterable["stock"])
        except (TypeError, ValueError):
            stock_qty = None

    status_code = STOCK_STATUS_CODES.get(said, "unknown") if said is not None else "unknown"
    status_label = STOCK_STATUS_LABELS_VI.get(said, "") if said is not None else ""

    display_parts: list[str] = []
    if product_state:
        display_parts.append(product_state)
    elif status_label:
        display_parts.append(status_label)

    if said == STOCK_AVAILABLE_IN_STOCK:
        if stock_qty is not None and stock_qty > 0:
            qty_text = f"Còn hàng ({stock_qty})"
            if product_state:
                display_parts.append(f"Số lượng: {stock_qty}")
            else:
                display_parts = [qty_text]
        elif not display_parts:
            display_parts.append("Còn hàng")
    elif said == STOCK_AVAILABLE_PRE_ORDER:
        if stock_qty is not None and stock_qty > 0:
            display_parts.append(f"SL đặt trước: {stock_qty}")
        elif not display_parts:
            display_parts.append("Đặt trước")
    elif said == STOCK_AVAILABLE_OUT_OF_STOCK:
        if not product_state:
            display_parts = ["Hết hàng"]
        if stock_qty is not None and stock_qty <= 0 and product_state:
            display_parts.append("Hết hàng")
    elif said == STOCK_AVAILABLE_SUBSCRIPTION:
        if not product_state:
            display_parts = ["Đăng ký nhận tin"]
    elif said == STOCK_AVAILABLE_DROP_SHIPPING:
        if stock_qty is not None and stock_qty > 0:
            display_parts.append(f"Còn hàng Drop shipping ({stock_qty})")
        elif not product_state:
            display_parts.append("Còn hàng (Drop shipping)")
    elif said == STOCK_AVAILABLE_VIRTUAL_STOCK:
        if stock_qty is not None and stock_qty > 0:
            display_parts.append(f"Còn hàng online ({stock_qty})")
        elif not product_state:
            display_parts.append("Còn hàng online")

    if (
        stock_qty is not None
        and stock_qty <= 0
        and said not in (
            STOCK_AVAILABLE_PRE_ORDER,
            STOCK_AVAILABLE_SUBSCRIPTION,
            STOCK_AVAILABLE_OUT_OF_STOCK,
        )
        and not product_state
    ):
        display_parts.append("Tạm hết hàng")

    display_status = " — ".join(dict.fromkeys(p for p in display_parts if p))
    if not display_status:
        display_status = status_label or "Không rõ"

    is_out_of_stock = said == STOCK_AVAILABLE_OUT_OF_STOCK or (
        stock_qty is not None and stock_qty <= 0 and said == STOCK_AVAILABLE_IN_STOCK
    )
    is_subscription = said == STOCK_AVAILABLE_SUBSCRIPTION
    is_pre_order = said == STOCK_AVAILABLE_PRE_ORDER
    is_in_stock = said in (
        STOCK_AVAILABLE_IN_STOCK,
        STOCK_AVAILABLE_VIRTUAL_STOCK,
        STOCK_AVAILABLE_DROP_SHIPPING,
    )
    is_buyable_online = (
        said in STOCK_BUYABLE_IDS
        and not is_out_of_stock
        and not is_subscription
    )
    if stock_qty is not None and stock_qty > 0 and said in STOCK_BUYABLE_IDS:
        is_buyable_online = True

    return {
        "stock_available_id": said,
        "status_code": status_code,
        "status_label": status_label,
        "product_state": product_state,
        "stock_quantity": stock_qty,
        "display_status": display_status,
        "is_in_stock": is_in_stock,
        "is_pre_order": is_pre_order,
        "is_out_of_stock": is_out_of_stock,
        "is_subscription": is_subscription,
        "is_buyable_online": is_buyable_online,
    }


def is_unavailable_product_detail(detail: dict[str, Any]) -> bool:
    """True nếu SP ở trạng thái hết hàng/đăng ký nhận tin."""
    stock = detail.get("stock_availability") or {}
    if stock.get("is_out_of_stock") or stock.get("is_subscription"):
        return True
    try:
        return int(detail.get("stock_available_id")) in UNAVAILABLE_STOCK_IDS
    except (TypeError, ValueError):
        return False


def _format_stock_status(filterable: dict[str, Any]) -> str:
    return parse_stock_availability(filterable)["display_status"]


# Nhãn hạng thành viên — tham chiếu cps-nuxt-standard/helper/function/prices.js
PRICE_TIER_LABELS: dict[str, str] = {
    "root": "Giá gốc",
    "special": "Giá khuyến mãi",
    "snull": "S-Null",
    "snew": "S-New",
    "smem": "S-Member",
    "svip": "S-Vip",
    "snull_student": "S-Null (HSSV)",
    "snew_student": "S-New (HSSV)",
    "smem_student": "S-Member (HSSV)",
    "svip_student": "S-Vip (HSSV)",
    "snull_teacher": "S-Null (Giáo viên)",
    "snew_teacher": "S-New (Giáo viên)",
    "smem_teacher": "S-Member (Giáo viên)",
    "svip_teacher": "S-Vip (Giáo viên)",
}

PRICE_TIER_ORDER: tuple[str, ...] = (
    "root",
    "special",
    "snull",
    "snew",
    "smem",
    "svip",
    "snull_student",
    "snew_student",
    "smem_student",
    "svip_student",
    "snull_teacher",
    "snew_teacher",
    "smem_teacher",
    "svip_teacher",
)

MEMBER_PRICE_TIERS: tuple[str, ...] = tuple(
    k for k in PRICE_TIER_ORDER if k not in ("root", "special")
)


def _price_amount(value: Any) -> float | None:
    if value is None:
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _parse_price_tier(tier_key: str, entry: Any) -> dict[str, Any] | None:
    """Map IProductPrice → dict hiển thị (value + chiet_khau như Prices.priceWithChietKhau)."""
    if not isinstance(entry, dict):
        return None

    value = _price_amount(entry.get("value"))
    chiet_khau = _price_amount(entry.get("chiet_khau")) or 0.0
    discount_value = _price_amount(entry.get("discount_value")) or 0.0

    if value is None and chiet_khau <= 0 and discount_value <= 0:
        return None

    # value = giá hiển thị; chiet_khau/discount_value là metadata giảm giá.
    final_value = value
    if final_value is None or final_value <= 0:
        return None

    tier: dict[str, Any] = {
        "tier": tier_key,
        "label": PRICE_TIER_LABELS.get(tier_key, tier_key),
        "value": int(final_value),
        "price": _format_price(final_value),
    }
    if chiet_khau > 0:
        tier["chiet_khau"] = int(chiet_khau)
        tier["chiet_khau_formatted"] = _format_price(chiet_khau)
    if value is not None and chiet_khau > 0:
        tier["base_value"] = int(value)
        tier["base_price"] = _format_price(value)
    if discount_value > 0:
        tier["discount_value"] = int(discount_value)
        tier["discount_formatted"] = _format_price(discount_value)
    discount_id = entry.get("discount_id")
    if discount_id not in (None, 0, "0"):
        tier["discount_id"] = discount_id
    return tier


def _price_tier_value(prices_raw: Any, tier_key: str) -> float | None:
    if not isinstance(prices_raw, dict):
        return None
    entry = prices_raw.get(tier_key)
    if not isinstance(entry, dict):
        return None
    return _price_amount(entry.get("value"))


def _resolve_standard_prices(filterable: dict[str, Any]) -> tuple[float | None, float | None]:
    """
    Giá chuẩn từ filterable.prices.root / .special (theo cps-nuxt-standard).
    Fallback: price, special_price, display_price (chỉ khi > 0).
    """
    prices_raw = filterable.get("prices") or {}
    root_val = _price_tier_value(prices_raw, "root")
    special_val = _price_tier_value(prices_raw, "special")

    if root_val is None:
        root_val = _price_amount(filterable.get("price"))
    if special_val is None:
        special_val = _price_amount(filterable.get("special_price"))
    if special_val is None:
        special_val = _price_amount(filterable.get("display_price"))

    sale_price = special_val if special_val is not None else root_val
    old_price_val: float | None = None
    if root_val is not None and sale_price is not None and root_val > sale_price:
        old_price_val = root_val
    return sale_price, old_price_val


def _parse_member_prices(prices_raw: Any) -> list[dict[str, Any]]:
    """Parse filterable.prices — chỉ hạng thành viên (bỏ root/special)."""
    if not isinstance(prices_raw, dict):
        return []

    tiers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tier_key in MEMBER_PRICE_TIERS:
        parsed = _parse_price_tier(tier_key, prices_raw.get(tier_key))
        if parsed:
            tiers.append(parsed)
            seen.add(tier_key)

    for tier_key, entry in prices_raw.items():
        if tier_key in seen or tier_key in ("root", "special"):
            continue
        parsed = _parse_price_tier(str(tier_key), entry)
        if parsed:
            tiers.append(parsed)
    return tiers


def _parse_promotion_pack_section(section: Any) -> list[dict[str, Any]]:
    """Parse km_chung / km_rieng trong promotion_pack."""
    if not isinstance(section, dict):
        return []

    promos: list[dict[str, Any]] = []
    for promo_id, promo in section.items():
        if not isinstance(promo, dict):
            continue
        gifts = [
            str(item.get("name")).strip()
            for item in (promo.get("items") or [])
            if isinstance(item, dict) and item.get("name")
        ]
        row: dict[str, Any] = {
            "id": str(promo.get("promotionpack_id") or promo_id),
            "description": _strip_html(str(promo.get("description") or "")),
        }
        promo_value = _price_amount(promo.get("value"))
        if promo_value is not None:
            row["value"] = int(promo_value)
            row["value_formatted"] = _format_price(promo_value)
        if gifts:
            row["gifts"] = gifts
        notes = _strip_html(str(promo.get("notes") or ""))
        if notes:
            row["notes"] = notes
        if row.get("description") or row.get("gifts") or row.get("value_formatted"):
            promos.append(row)
    return promos


def _parse_promotion_pack(promotion_pack_raw: Any) -> dict[str, Any]:
    """Parse filterable.promotion_pack → km_chung + km_rieng."""
    if not isinstance(promotion_pack_raw, dict):
        return {"km_chung": [], "km_rieng": []}
    return {
        "km_chung": _parse_promotion_pack_section(promotion_pack_raw.get("km_chung")),
        "km_rieng": _parse_promotion_pack_section(promotion_pack_raw.get("km_rieng")),
    }


def _build_promotions(filterable: dict[str, Any]) -> dict[str, Any]:
    """Gộp promotion_pack + promotion_info + promotion_information."""
    promos = _parse_promotion_pack(filterable.get("promotion_pack"))
    highlights: list[dict[str, str]] = []

    for key, source in (
        ("promotion_info", "Trả góp / thông tin KM"),
        ("promotion_information", "Khuyến mãi website"),
    ):
        text = _strip_html(str(filterable.get(key) or ""))
        if text:
            highlights.append({"source": source, "description": text})

    if highlights:
        promos["highlights"] = highlights
    return promos


def _resolve_category_url(categories_raw: Any) -> str:
    """URL danh mục đúng path (vd: /mobile/apple/iphone-17.html)."""
    cats = [
        c
        for c in (categories_raw or [])
        if isinstance(c, dict)
        and str(c.get("uri") or "").strip() not in ("", "default-category")
    ]
    if not cats:
        return ""

    uris = {str(c.get("uri") or "").strip("/") for c in cats}
    by_level = sorted(cats, key=lambda c: int(c.get("level") or 0))
    deepest_uri = str(by_level[-1].get("uri") or "").strip("/")

    segments: list[str] = []
    for key in ("mobile", "laptop", "may-tinh", "tablet", "apple", "samsung", "xiaomi"):
        if key in uris:
            segments.append(key)
    if deepest_uri and deepest_uri not in segments:
        segments.append(deepest_uri)

    path = "/".join(dict.fromkeys(segments))
    if path and not path.endswith(".html"):
        path += ".html"
    return _full_url(path) if path else ""


def _filterable_is_sparse(product: dict[str, Any] | None) -> bool:
    """Staging API thường thiếu giá member + promotion_pack."""
    if not product:
        return True
    filterable = product.get("filterable") or {}
    prices = filterable.get("prices") or {}
    if isinstance(prices, dict):
        member_tiers = [k for k in prices if k not in ("root", "special")]
        if member_tiers:
            return False

    pack = filterable.get("promotion_pack") or {}
    if isinstance(pack, dict) and (pack.get("km_chung") or pack.get("km_rieng")):
        return False
    if filterable.get("promotion_information"):
        return False
    return True


def normalize_product_detail(
    product: dict[str, Any] | None,
    *,
    url: str = "",
    url_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Map response CPS v2 → format bot/Gemini đang dùng."""
    if not product:
        return {
            "name": "",
            "price": "",
            "old_price": "",
            "description": "",
            "specifications": {},
            "stock_status": "Không truy cập được",
            "url": url,
            "thumbnail": "",
            "product_id": "",
            "category_id": "",
        }

    general = product.get("general") or {}
    filterable = product.get("filterable") or {}
    specification = product.get("specification") or {}

    url_path = (general.get("url_path") or "").strip()
    # Luôn ưu tiên url_path từ GraphQL — không dùng URL Serp/search resolve
    product_url = _full_url(url_path) if url_path else (url or "")

    sale_price, old_price_val = _resolve_standard_prices(filterable)

    thumbnail = filterable.get("thumbnail") or ""
    if thumbnail and not str(thumbnail).startswith("http"):
        thumbnail = _full_url(str(thumbnail))

    categories = [
        cat.get("name")
        for cat in (general.get("categories") or [])
        if isinstance(cat, dict) and cat.get("name")
    ]
    category_url = _resolve_category_url(general.get("categories"))

    stock_raw = filterable.get("stock")
    stock_qty: int | None = None
    if stock_raw is not None:
        try:
            stock_qty = int(stock_raw)
        except (TypeError, ValueError):
            stock_qty = None

    category_objs = [
        c for c in (general.get("categories") or []) if isinstance(c, dict)
    ]
    category_ids = [
        str(c.get("categoryId"))
        for c in category_objs
        if c.get("categoryId") is not None
    ]

    warranty_info = _strip_html(str(filterable.get("warranty_information") or ""))
    included_acc = _strip_html(str(filterable.get("included_accessories") or ""))
    member_promo = _strip_html(str(filterable.get("member_promotion") or ""))
    product_condition = _strip_html(str(filterable.get("product_condition") or ""))

    try:
        company_stock_qty = int(filterable.get("company_stock_quantity") or 0)
    except (TypeError, ValueError):
        company_stock_qty = None

    stock_avail = parse_stock_availability(filterable)

    default_pid = ""
    default_block = filterable.get("default")
    if isinstance(default_block, dict) and default_block.get("product_id") is not None:
        default_pid = str(default_block.get("product_id")).strip()

    general_pid = str(
        general.get("product_id")
        or (url_info or {}).get("product_id")
        or ""
    ).strip()

    return {
        "name": general.get("name") or filterable.get("short_name") or "",
        "price": _format_price(sale_price),
        "price_value": int(sale_price) if sale_price is not None else None,
        "old_price": _format_price(old_price_val) if old_price_val else "",
        "description": _strip_html(
            str(
                filterable.get("short_description")
                or filterable.get("promotion_information")
                or ""
            )
        ),
        "specifications": _parse_specifications(specification),
        "stock_status": stock_avail["display_status"],
        "stock_quantity": stock_qty,
        "stock_available_id": stock_avail["stock_available_id"],
        "stock_availability": stock_avail,
        "company_stock_quantity": company_stock_qty,
        "url": product_url,
        "url_path": url_path,
        "thumbnail": thumbnail,
        "product_id": general_pid,
        "default_product_id": default_pid or general_pid,
        "category_id": str(
            (url_info or {}).get("category_id")
            or (category_ids[0] if category_ids else "")
            or ""
        ),
        "category_ids": category_ids,
        "sku": general.get("sku") or "",
        "manufacturer": general.get("manufacturer") or "",
        "categories": categories,
        "category_url": category_url,
        "promotion_info": _strip_html(str(filterable.get("promotion_info") or "")),
        "member_prices": _parse_member_prices(filterable.get("prices")),
        "promotions": _build_promotions(filterable),
        "warranty_information": warranty_info,
        "included_accessories": included_acc,
        "member_promotion": member_promo,
        "product_condition": product_condition,
        "relation": general.get("relation") or "",
        "related_name": general.get("related_name") or "",
        "up_sell": general.get("up_sell") or [],
        "child_product": general.get("child_product") or [],
        "parent_id": str(general.get("parent_id") or "").strip(),
        "is_installment": filterable.get("is_installment"),
    }


async def _graphql(
    client: httpx.AsyncClient,
    endpoint: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
    from cps_bot.core.api_trace import record_from_context

    op = _extract_gql_operation(query)
    record_from_context(
        name="GraphQL shops_stock" if op == "SHOP_STOCK" else "",
        operation=op,
        endpoint=endpoint,
        graphql_query=query,
        variables=variables,
    )
    response = await client.post(
        endpoint,
        json={"query": query, "variables": variables},
        headers={"Content-Type": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        logger.warning("GraphQL errors (%s): %s", endpoint, payload["errors"])
    return payload


def _extract_gql_operation(query: str) -> str:
    import re

    match = re.search(r"\b(query|mutation)\s+(\w+)", query or "")
    return match.group(2) if match else "anonymous"


async def url_info(request_path: str) -> dict[str, Any] | None:
    path = extract_request_path(request_path)
    if not path:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_URL_ENDPOINT,
            URL_INFO_QUERY,
            {"path": path},
        )
    return payload.get("data", {}).get("url_info")


async def get_product_by_id(
    product_id: str | int,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    pid = str(product_id).strip()
    if not pid:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            PRODUCT_DETAIL_QUERY,
            {
                "id": pid,
                "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
            },
        )
        product = payload.get("data", {}).get("product")
        if (
            product
            and _filterable_is_sparse(product)
            and CPS_GRAPHQL_V2_ENDPOINT.rstrip("/") != CPS_GRAPHQL_V2_PRODUCTION.rstrip("/")
        ):
            fallback = await _graphql(
                client,
                CPS_GRAPHQL_V2_PRODUCTION,
                PRODUCT_DETAIL_QUERY,
                {
                    "id": pid,
                    "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
                },
            )
            rich = fallback.get("data", {}).get("product")
            if rich and not _filterable_is_sparse(rich):
                logger.info(
                    "Dùng GraphQL production cho product_id=%s (staging thiếu giá member/KM)",
                    pid,
                )
                return rich
    return product


async def get_products_by_category_id(
    category_id: str | int,
    *,
    province_id: int | None = None,
    size: int = 12,
    page: int = 1,
) -> list[dict[str, Any]]:
    cate = str(category_id).strip()
    if not cate:
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            PRODUCTS_BY_CATEGORY_QUERY,
            {
                "cateId": cate,
                "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
                "size": size,
                "page": page,
            },
        )
    return payload.get("data", {}).get("products") or []


async def get_products_by_stock_id(
    company_stock_ids: list[int] | int,
    *,
    province_id: int | None = None,
    size: int = 24,
    page: int = 1,
) -> list[dict[str, Any]]:
    """
    Danh sách SP theo trạng thái tồn — filter GraphQL giống query cate
    nhưng bỏ categories, truyền company_stock_id.
    """
    if isinstance(company_stock_ids, int):
        ids = [company_stock_ids]
    else:
        ids = [int(i) for i in company_stock_ids if i is not None]
    if not ids:
        return []

    query = _build_products_by_stock_query(ids)
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            query,
            {
                "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
                "size": size,
                "page": page,
            },
        )
    return payload.get("data", {}).get("products") or []


def resolve_stock_filter_ids(text: str) -> list[int]:
    """Trích company_stock_id từ câu tìm SP theo trạng thái."""
    ids: list[int] = []
    seen: set[int] = set()
    for pattern, stock_id in _STOCK_ID_FROM_TEXT:
        if pattern.search(text or "") and stock_id not in seen:
            ids.append(stock_id)
            seen.add(stock_id)
    return ids


def is_stock_status_browse_query(text: str) -> bool:
    """
    True khi khách muốn tìm/danh sách SP theo trạng thái (đặt trước, đăng ký nhận tin…),
    không phải hỏi trạng thái của 1 SP đã biết tên.
    """
    if not resolve_stock_filter_ids(text):
        return False
    lower = (text or "").lower()
    if _STOCK_STATUS_CHECK_ONLY_RE.search(lower):
        if not re.search(
            r"đặt trước|dat truoc|pre[- ]?order|đăng ký nhận tin|dang ky nhan tin",
            lower,
        ):
            return False
    return True


def strip_stock_browse_phrases_for_keywords(text: str) -> str:
    """Bóc cụm trạng thái tồn / browse để giữ tên SP (nếu có)."""
    s = (text or "").strip()
    for pattern in _STOCK_BROWSE_KEYWORD_STRIP_RES:
        s = pattern.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _graphql_product_to_search_record(item: dict[str, Any]) -> dict[str, Any]:
    general = item.get("general") or {}
    filterable = item.get("filterable") or {}
    url_path = str(general.get("url_path") or "")
    sale_price, _ = _resolve_standard_prices(filterable)
    thumb = filterable.get("thumbnail") or ""
    if thumb and not str(thumb).startswith("http"):
        thumb = _full_url(str(thumb))
    stock_avail = parse_stock_availability(filterable)
    return normalize_search_result(
        {
            "name": general.get("name") or "",
            "price": _format_price(sale_price),
            "url_path": url_path,
            "url_key": general.get("url_key") or "",
            "url": graphql_product_url(general),
            "thumbnail": thumb,
            "product_id": str(general.get("product_id") or ""),
            "stock_available_id": stock_avail.get("stock_available_id"),
            "stock_status": stock_avail.get("display_status") or "",
        }
    )


async def _fetch_product_by_stock_filter(
    keywords: str,
    user_message: str,
    *,
    province_id: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Tìm SP qua GraphQL products + company_stock_id (không categories)."""
    if not is_stock_status_browse_query(user_message):
        return None
    stock_ids = resolve_stock_filter_ids(user_message)
    if not stock_ids:
        return None

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    products = await get_products_by_stock_id(
        stock_ids,
        province_id=pid_province,
        size=24,
    )
    if not products:
        return None

    search_results = [_graphql_product_to_search_record(p) for p in products[:12]]
    keyword_tokens = _keyword_tokens(keywords)
    list_mode = not keyword_tokens

    if list_mode:
        detail = _build_stock_browse_summary(stock_ids, search_results, pid_province)
        return search_results, detail

    selected = _pick_best_category_product(
        products,
        request_path="",
        keywords=keywords,
    )
    if not selected:
        detail = _build_stock_browse_summary(stock_ids, search_results, pid_province)
        return search_results, detail

    product_id = (selected.get("general") or {}).get("product_id")
    if not product_id:
        detail = _build_stock_browse_summary(stock_ids, search_results, pid_province)
        return search_results, detail

    product = await get_product_by_id(product_id, province_id=pid_province)
    if not product:
        detail = _build_stock_browse_summary(stock_ids, search_results, pid_province)
        return search_results, detail

    url_path = str((selected.get("general") or {}).get("url_path") or "")
    detail = normalize_product_detail(
        product,
        url=_full_url(url_path) if url_path else "",
    )
    detail["stock_filter_ids"] = stock_ids
    detail["stock_browse_list_mode"] = False
    return search_results, detail


def _build_stock_browse_summary(
    stock_ids: list[int],
    search_results: list[dict[str, Any]],
    province_id: int,
) -> dict[str, Any]:
    """Payload tóm tắt khi khách browse theo trạng thái — không deep-dive 1 SP."""
    labels = [
        STOCK_STATUS_LABELS_VI.get(sid, str(sid)) for sid in stock_ids
    ]
    prov_name = PROVINCE_ID_TO_NAME.get(province_id, "")
    return {
        "name": f"Danh sách sản phẩm — {', '.join(labels)}",
        "price": "",
        "old_price": "",
        "description": (
            f"Có {len(search_results)} sản phẩm khớp trạng thái "
            f"{', '.join(labels)}"
            + (f" tại {prov_name}" if prov_name else "")
            + "."
        ),
        "specifications": {},
        "stock_status": labels[0] if labels else "",
        "url": "",
        "thumbnail": "",
        "product_id": "",
        "stock_filter_ids": stock_ids,
        "stock_browse_list_mode": True,
        "product_count": len(search_results),
    }


def _build_budget_browse_summary(
    constraint: Any,
    search_results: list[dict[str, Any]],
    province_id: int,
) -> dict[str, Any]:
    """Payload tóm tắt khi khách browse theo ngân sách — danh sách SP."""
    label = constraint.label if hasattr(constraint, "label") else ""
    category = getattr(constraint, "category", "") or "sản phẩm"
    prov_name = PROVINCE_ID_TO_NAME.get(province_id, "")
    return {
        "name": f"{category.title()} {label}".strip(),
        "price": "",
        "old_price": "",
        "description": (
            f"Có {len(search_results)} sản phẩm {category}"
            + (f" trong tầm {label}" if label else "")
            + (f" tại {prov_name}" if prov_name else "")
            + "."
        ),
        "specifications": {},
        "stock_status": "",
        "url": "",
        "thumbnail": "",
        "product_id": "",
        "budget_browse_list_mode": True,
        "budget_label": label,
        "budget_category": category,
        "product_count": len(search_results),
    }


async def _fetch_products_by_budget_browse(
    keywords: str,
    user_message: str,
    *,
    province_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Tìm SP theo danh mục + lọc giá từ câu hỏi."""
    if not is_budget_browse_query(user_message):
        return None

    constraint = parse_budget_constraint(user_message)
    if not constraint:
        return None

    search_kw = (
        keywords.strip()
        or constraint.category
        or strip_budget_phrases_for_keywords(user_message)
        or "điện thoại"
    )
    results = await search_products(search_kw, province_id=province_id, limit=24)

    filtered = filter_results_by_budget(results, constraint)
    if not filtered:
        return None

    detail = _build_budget_browse_summary(constraint, filtered[:12], province_id)
    return filtered[:12], detail


def _pick_best_category_product(
    products: list[dict[str, Any]],
    *,
    request_path: str,
    keywords: str,
) -> dict[str, Any] | None:
    if not products:
        return None
    path_tokens = _keyword_tokens(request_path.replace(".html", "").replace("-", " "))
    keyword_tokens = _keyword_tokens(keywords)
    query_tokens = path_tokens | keyword_tokens

    def score(item: dict[str, Any]) -> int:
        general = item.get("general") or {}
        text = " ".join(
            [
                str(general.get("name") or ""),
                str(general.get("sku") or ""),
                str(general.get("url_key") or ""),
                str(general.get("url_path") or ""),
            ]
        )
        item_tokens = _keyword_tokens(text.replace("-", " "))
        overlap = len(query_tokens & item_tokens)
        # ưu tiên item có giá hiển thị/stock
        filterable = item.get("filterable") or {}
        quality = 0
        if filterable.get("display_price") is not None:
            quality += 2
        if filterable.get("stock") not in (None, 0, "0"):
            quality += 1
        return overlap * 10 + quality

    ranked = sorted(products, key=score, reverse=True)
    return ranked[0]


def _extract_iphone_generation(keywords: str) -> str | None:
    match = re.search(r"iphone\s*(\d{1,2})\b", (keywords or "").lower())
    return match.group(1) if match else None


def _query_iphone_variant_tiers(keywords: str) -> set[str]:
    lower = (keywords or "").lower()
    tiers: set[str] = set()
    if re.search(r"\bpro\s*max\b|\bpromax\b", lower):
        tiers.add("pro max")
    elif re.search(r"\bpro\b", lower):
        tiers.add("pro")
    if re.search(r"\bplus\b", lower):
        tiers.add("plus")
    if re.search(r"\bultra\b", lower):
        tiers.add("ultra")
    return tiers


def _apply_generation_match_score(
    points: int,
    *,
    keywords: str,
    text: str,
) -> int:
    gen = _extract_iphone_generation(keywords)
    if not gen:
        return points

    if re.search(rf"iphone[\s-]*{gen}\b", text):
        points += 45
    else:
        wrong = re.search(r"iphone[\s-]*(\d{1,2})\b", text)
        if wrong and wrong.group(1) != gen:
            points -= 100

    tiers = _query_iphone_variant_tiers(keywords)
    if tiers:
        if "pro max" in tiers and "pro max" in text:
            points += 20
        elif "pro" in tiers and re.search(r"\bpro\b", text) and "pro max" not in text:
            points += 15
        if "plus" in tiers and "plus" in text:
            points += 15
        if "ultra" in tiers and "ultra" in text:
            points += 15
    else:
        if "pro max" in text or re.search(r"\biphone\s*\d{1,2}\s*pro\b", text):
            points -= 25
        if re.search(r"\bplus\b", text):
            points -= 45
        if re.search(r"\bultra\b", text):
            points -= 35

    return points


def _is_camera_gimbal_query(keywords: str) -> bool:
    lower = (keywords or "").lower()
    if re.search(r"\b(?:dji|osmo|gimbal|may anh|máy ảnh|camera)\b", lower):
        return True
    return bool(re.search(r"\bpocket\s*\d+\b", lower))


def _pick_best_search_result(
    results: list[dict[str, Any]],
    keywords: str,
) -> dict[str, Any] | None:
    """Chọn SP khớp từ khóa nhất — tránh ốp lưng/phụ kiện, ưu tiên Pro/Plus/Max."""
    if not results:
        return None
    if len(results) == 1:
        return results[0]

    kw_tokens = _keyword_tokens(keywords.replace("-", " "))
    kw_text = keywords.lower()
    camera_query = _is_camera_gimbal_query(kw_text)

    def score(item: dict[str, Any]) -> int:
        name = str(item.get("name") or "").lower()
        path = str(item.get("url_path") or item.get("url") or "").lower()
        text = f"{name} {path}"
        item_tokens = _keyword_tokens(text.replace("-", " "))
        points = len(kw_tokens & item_tokens) * 10

        for token in kw_tokens:
            if len(token) >= 2 and token in text:
                points += 4

        if any(h in path for h in _ACCESSORY_PATH_HINTS):
            points -= 80

        if "pro" in kw_tokens:
            if "-pro" in path or "pro-" in path or path.endswith("-pro.html"):
                points += 25
            elif "pro" not in path:
                points -= 15
        elif "pro" in path and "pro" not in kw_text:
            points -= 8

        if "5g" in kw_tokens and "5g" in path:
            points += 15
        elif "5g" not in kw_tokens and "5g" in path:
            points -= 10

        if camera_query:
            if any(h in path for h in ("may-anh", "camera", "dji", "osmo", "gimbal")):
                points += 30
            if path.startswith("dien-thoai-"):
                points -= 35
        elif path.startswith("dien-thoai-") or path.endswith(".html"):
            points += 5

        points = _apply_generation_match_score(
            points,
            keywords=keywords,
            text=text,
        )

        return points

    return max(results, key=score)


def _is_product_map_query(keywords: str) -> bool:
    from cps_bot.browse.product_map import _is_map_query

    return _is_map_query(keywords)


def _product_terms_for_resolution(keywords: str, user_message: str) -> str:
    """Tách tên SP từ câu hỏi — dùng khi keywords là filter URL."""
    kw = (keywords or "").strip()
    if _is_product_map_query(kw):
        return kw
    msg = (user_message or "").strip()
    if not msg:
        return kw
    from cps_bot.llm.gemini_client import _normalize_keyword_line, _strip_search_noise

    terms = _normalize_keyword_line(_strip_search_noise(msg))
    if terms and _is_product_map_query(terms):
        return terms
    return kw


def _api_search_terms(keywords: str, user_message: str) -> str:
    """Chuỗi gửi CPS search — không dùng filter URL làm query."""
    terms = _product_terms_for_resolution(keywords, user_message)
    if _is_product_map_query(terms):
        return terms
    msg = (user_message or "").strip()
    if msg:
        from cps_bot.llm.gemini_client import _normalize_keyword_line, _strip_search_noise

        cleaned = _normalize_keyword_line(_strip_search_noise(msg))
        if cleaned:
            return cleaned
    return terms


async def _apply_session_product_fallback(
    *,
    fallback_pid: str,
    fallback_url: str,
    session_parent_pid: str,
    session_last_product_name: str,
    user_message: str,
    keywords: str,
    stats: dict[str, Any],
) -> dict[str, Any]:
    """Pin product_id/url session — chỉ sau khi search/map không ra kết quả."""
    detail: dict[str, Any] = {}
    province_id = resolve_province_from_text(user_message) or CPS_PROVINCE_ID
    if fallback_pid:
        try:
            stats["cps_product_detail_calls"] += 1
            product = await get_product_by_id(fallback_pid, province_id=province_id)
            if product:
                detail = normalize_product_detail(
                    product,
                    url=fallback_url or "",
                    url_info={"product_id": fallback_pid},
                )
                if session_parent_pid and not detail.get("parent_id"):
                    detail["parent_id"] = session_parent_pid
                stats["resolve_source"] = "session_fallback_product_id"
                follow_hints = _extract_variant_hints(user_message) or _extract_variant_hints(
                    keywords
                )
                if follow_hints:
                    variant_query = merge_follow_up_variant_into_keywords(
                        keywords,
                        user_message,
                    )
                    detail = await resolve_product_variant(
                        variant_query or keywords,
                        detail,
                        province_id=province_id,
                    )
        except Exception as exc:
            logger.warning("CPS fetch product_id=%s thất bại: %s", fallback_pid, exc)
        return detail

    if fallback_url:
        try:
            stats["cps_url_info_calls"] += 1
            stats["cps_product_detail_calls"] += 1
            detail = await fetch_product_from_url(fallback_url, keywords=keywords)
            if detail:
                stats["resolve_source"] = "session_fallback_url"
                variant_query = merge_follow_up_variant_into_keywords(
                    keywords,
                    user_message,
                )
                detail = await resolve_product_variant(
                    variant_query or keywords,
                    detail,
                    province_id=province_id,
                )
        except Exception as exc:
            logger.warning("CPS fetch thất bại (%s): %s", fallback_url, exc)
    return detail


async def _fetch_product_from_map(
    keywords: str,
    *,
    province_id: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Resolve product_id từ file map → GraphQL detail."""
    from cps_bot.browse.product_map import resolve_product_from_map

    hit = resolve_product_from_map(keywords)
    if not hit:
        return None

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    product = await get_product_by_id(hit.product_id, province_id=pid_province)
    if not product:
        logger.warning(
            "Product map hit %s (%s) nhưng GraphQL không trả detail",
            hit.product_id,
            hit.name,
        )
        return None

    detail = normalize_product_detail(product)
    detail["product_map_matched_name"] = hit.name
    detail["product_map_score"] = hit.score
    detail["product_map_confidence"] = hit.confidence
    if keywords:
        detail = await resolve_product_variant(keywords, detail, province_id=pid_province)

    search_record = normalize_search_result(
        {
            "name": detail.get("name") or hit.name,
            "price": detail.get("price", ""),
            "url": detail.get("url", ""),
            "url_path": detail.get("url_path", ""),
            "product_id": str(detail.get("product_id") or hit.product_id),
            "stock_status": detail.get("stock_status", ""),
        }
    )
    logger.info(
        "Product map: %r → id=%s score=%d confidence=%.2f (%s)",
        keywords,
        hit.product_id,
        hit.score,
        hit.confidence,
        hit.name[:60],
    )
    return [search_record], detail


_VARIANT_STORAGE_RE = re.compile(
    r"\b(64|128|256|512|1024)\s*(?:gb|g)\b|\b(1|2)\s*tb\b",
    re.IGNORECASE,
)
_SCREEN_INCH_VARIANT_RE = re.compile(
    r"\b(?:b[âa]n\s+)?(13|14|15|16|17)\s*(?:inch|\"|in)\b|\b(13|14|15|16|17)inch\b",
    re.IGNORECASE,
)
_MACBOOK_BARE_SCREEN_RE = re.compile(
    r"\b(?:macbook\s+)?(?:pro|air)\s+(13|14|15|16|17)\b"
    r"|\b(13|14|15|16|17)\s+m[1-5]\b",
    re.IGNORECASE,
)
_VARIANT_COLOR_HINTS: tuple[tuple[str, ...], ...] = (
    ("titan", "titan tự nhiên", "titan tu nhien", "natural titanium"),
    ("titan đen", "titan den", "black titanium", "đen titan"),
    ("titan trắng", "titan trang", "white titanium", "trắng titan"),
    ("titan sa mạc", "titan sa mac", "desert titanium"),
    ("cam vũ trụ", "cam vu tru", "cosmic orange", "màu cam vũ trụ"),
    ("cam", "màu cam", "orange"),
    ("xanh đậm", "xanh dam", "deep blue", "màu xanh đậm"),
    ("xanh dương", "xanh duong", "blue", "màu xanh dương"),
    ("xanh mỏng két", "xanh mong ket", "mỏng két", "mong ket", "màu xanh mỏng két"),
    ("xanh lưu ly", "xanh luu ly", "ultramarine", "màu xanh lưu ly"),
    ("xanh lá", "xanh la", "green", "màu xanh lá", "xanh la cay"),
    ("hồng", "hong", "pink", "màu hồng"),
    ("tím", "tim", "purple", "titan tím", "màu tím"),
    ("vàng", "vang", "gold", "màu vàng"),
    ("đen", "den", "black", "màu đen"),
    ("trắng", "trang", "white", "màu trắng"),
    ("bạc", "bac", "silver", "màu bạc"),
    ("xanh", "màu xanh"),
)
_COLOR_PRIMARY_HINTS = frozenset(group[0] for group in _VARIANT_COLOR_HINTS)


def _normalize_screen_inch_hint(raw: str) -> str:
    return f"{raw}inch"


def _extract_screen_inch_sizes(text: str) -> list[str]:
    """Kích thước màn hình laptop (13–17 inch) trong câu hỏi."""
    sizes: list[str] = []
    seen: set[str] = set()
    lower = (text or "").lower()
    for match in _SCREEN_INCH_VARIANT_RE.finditer(lower):
        val = match.group(1) or match.group(2)
        if val and val not in seen:
            seen.add(val)
            sizes.append(_normalize_screen_inch_hint(val))
    for match in _MACBOOK_BARE_SCREEN_RE.finditer(lower):
        val = match.group(1) or match.group(2)
        if val and val not in seen:
            seen.add(val)
            sizes.append(_normalize_screen_inch_hint(val))
    return sizes


def screen_inches_in_text(text: str) -> set[str]:
    return {hint.replace("inch", "") for hint in _extract_screen_inch_sizes(text)}


def is_screen_size_variant_query(text: str) -> bool:
    return bool(_extract_screen_inch_sizes(text))


def screen_size_conflicts_with_session(
    query: str,
    *,
    last_keywords: str = "",
    last_product_name: str = "",
) -> bool:
    """True khi câu hỏi tiếp đổi kích thước inch khác SP đang thảo luận."""
    q_sizes = screen_inches_in_text(query)
    if not q_sizes:
        return False
    prior = f"{last_keywords or ''} {last_product_name or ''}".strip()
    prior_sizes = screen_inches_in_text(prior)
    if not prior_sizes:
        return False
    return not (q_sizes & prior_sizes)


def _extract_variant_hints(keywords: str) -> list[str]:
    hints: list[str] = []
    lower = (keywords or "").lower()
    for match in _VARIANT_STORAGE_RE.finditer(lower):
        if match.group(2):
            hints.append(f"{match.group(2)}tb")
            continue
        val = match.group(1).lower()
        hints.append(f"{val}gb")

    best_color: tuple[int, str] | None = None
    for aliases in _VARIANT_COLOR_HINTS:
        primary = aliases[0]
        for alias in aliases:
            if alias in lower:
                if best_color is None or len(alias) > best_color[0]:
                    best_color = (len(alias), primary)
                break
    if best_color:
        hints.append(best_color[1])

    for inch in _extract_screen_inch_sizes(lower):
        hints.append(inch)

    return hints


def _split_variant_hints(hints: list[str]) -> tuple[list[str], list[str], list[str]]:
    color = [h for h in hints if h in _COLOR_PRIMARY_HINTS]
    screen = [
        h for h in hints
        if h.endswith("inch") and h[:-4].isdigit()
    ]
    storage = [
        h for h in hints
        if h not in _COLOR_PRIMARY_HINTS and h not in screen
    ]
    return color, storage, screen


def merge_follow_up_variant_into_keywords(
    keywords: str,
    follow_up_text: str,
) -> str:
    """
    Hỏi tiếp đổi màu/dung lượng/kích thước inch — cập nhật từ khóa ngữ cảnh.
    Vd. ngữ cảnh 'iPhone 17 Pro 1TB Xanh' + 'màu bạc còn hàng không' → ... 1TB Bạc
    Vd. 'MacBook Pro M5' + 'có bản 16inch không' → MacBook Pro 16 inch M5
    """
    base = (keywords or "").strip()
    if not base:
        return base
    follow_hints = _extract_variant_hints(follow_up_text or "")
    if not follow_hints:
        return base
    new_color, new_storage, new_screen = _split_variant_hints(follow_hints)
    if not new_color and not new_storage and not new_screen:
        return base

    result = base
    base_hints = _extract_variant_hints(base)
    base_color, base_storage, base_screen = _split_variant_hints(base_hints)

    def _color_label(primary: str) -> str:
        return " ".join(part.capitalize() for part in primary.split())

    if new_color and (not base_color or new_color[0] != base_color[0]):
        if base_color:
            for aliases in _VARIANT_COLOR_HINTS:
                if aliases[0] == base_color[0]:
                    for alias in sorted(aliases, key=len, reverse=True):
                        result = re.sub(
                            rf"(?<!\w){re.escape(alias)}(?!\w)",
                            " ",
                            result,
                            flags=re.IGNORECASE,
                        )
        result = re.sub(r"\s+", " ", result).strip()
        label = _color_label(new_color[0])
        if label.lower() not in result.lower():
            result = f"{result} {label}".strip()

    if new_storage and (not base_storage or new_storage[0] != base_storage[0]):
        result = _VARIANT_STORAGE_RE.sub(" ", result)
        result = re.sub(r"\s+", " ", result).strip()
        label = (
            new_storage[0].upper()
            if new_storage[0].endswith("tb")
            else new_storage[0]
        )
        if label.lower() not in result.lower():
            result = f"{result} {label}".strip()

    if new_screen and (not base_screen or new_screen[0] != base_screen[0]):
        result = _SCREEN_INCH_VARIANT_RE.sub(" ", result)
        result = re.sub(r"\s+", " ", result).strip()
        inch_val = new_screen[0].replace("inch", "")
        if inch_val not in screen_inches_in_text(result):
            result = f"{result} {inch_val} inch".strip()

    return re.sub(r"\s+", " ", result).strip()


def _variant_hint_score(name: str, hints: list[str]) -> int:
    if not hints:
        return 0
    text = name.lower()
    score = 0
    for hint in hints:
        hint_lower = hint.lower()
        if hint_lower in _COLOR_PRIMARY_HINTS and " " in hint_lower:
            if hint_lower in text or hint_lower.replace(" ", "") in text.replace(" ", ""):
                score += 10
            continue
        if hint_lower in text or hint_lower.replace(" ", "") in text.replace(" ", ""):
            score += 10
        elif hint.endswith("gb") and hint[:-2] in text:
            score += 8
    return score


def _collect_up_sell_ids(detail: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    up_sell = detail.get("up_sell") or []
    if isinstance(up_sell, list):
        for item in up_sell:
            if isinstance(item, dict):
                raw = item.get("product_id") or item.get("id")
            else:
                raw = item
            try:
                pid = int(raw)
            except (TypeError, ValueError):
                continue
            if pid not in ids:
                ids.append(pid)
    current = detail.get("product_id")
    try:
        current_int = int(current) if current else 0
    except (TypeError, ValueError):
        current_int = 0
    if current_int and current_int not in ids:
        ids.insert(0, current_int)
    return ids


def is_color_variant_list_query(text: str) -> bool:
    """Hỏi danh sách màu / màu sibling của cùng biến thể dung lượng."""
    return bool(_COLOR_VARIANT_LIST_RE.search(text or ""))


def is_color_variant_query(text: str) -> bool:
    """Alias rõ nghĩa — dùng ở enrich, session fallback, fast reply."""
    return is_color_variant_list_query(text)


def _filter_products_by_model_tier(
    keywords: str,
    products: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not products:
        return products
    lower = (keywords or "").lower()
    tiers = _query_iphone_variant_tiers(keywords)
    filtered: list[dict[str, Any]] = []
    for item in products:
        name = str((item.get("general") or {}).get("name") or "").lower()
        padded = f" {name} "
        if tiers:
            if "pro max" in tiers and "pro max" not in name:
                continue
            if "pro" in tiers and (" pro " not in padded or "pro max" in name):
                continue
            if "plus" in tiers and "plus" not in name:
                continue
            if "ultra" in tiers and "ultra" not in name:
                continue
        else:
            if "plus" in name and "plus" not in lower:
                continue
            if "pro max" in name and "pro max" not in lower and "promax" not in lower:
                continue
            if re.search(r"\biphone\s*\d{1,2}\s*pro\b", name) and "pro" not in lower:
                continue
            if "ultra" in name and "ultra" not in lower:
                continue
        filtered.append(item)
    return filtered if filtered else products


async def _resolve_color_parent_product_id(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> int | None:
    """SKU cha chứa child_product (màu) — từ parent_id hoặc fetch lại product."""
    try:
        current_id = int(detail.get("product_id") or 0)
    except (TypeError, ValueError):
        current_id = 0

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID

    parent_raw = detail.get("parent_id")
    if parent_raw not in (None, "", 0, "0"):
        try:
            parent_id = int(parent_raw)
            if parent_id > 0:
                return parent_id
        except (TypeError, ValueError):
            pass

    if not current_id:
        return None

    product = await get_product_by_id(current_id, province_id=pid_province)
    if not product:
        return None

    general = product.get("general") or {}
    try:
        parent_id = int(general.get("parent_id") or 0)
    except (TypeError, ValueError):
        parent_id = 0
    if parent_id > 0:
        return parent_id

    stored_children = general.get("child_product") or []
    if len(stored_children) > 1:
        return current_id

    return None


async def _load_child_product_ids(
    parent_id: int,
    *,
    province_id: int | None = None,
) -> list[int]:
    """Lấy child_product của SKU cha (màu sibling)."""
    if parent_id <= 0:
        return []

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID

    child_ids = await _fetch_child_product_ids(parent_id, province_id=pid_province)
    if len(child_ids) > 1:
        return child_ids

    product = await get_product_by_id(parent_id, province_id=pid_province)
    if not product:
        return child_ids

    raw_children = (product.get("general") or {}).get("child_product") or []
    parsed: list[int] = []
    for raw in raw_children:
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            continue
        if cid not in parsed:
            parsed.append(cid)
    return parsed if len(parsed) > 1 else child_ids


async def _resolve_sibling_color_product_ids(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> list[int]:
    """Danh sách product_id các màu (child_product) cùng SKU cha."""
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID

    parent_id = await _resolve_color_parent_product_id(
        detail,
        province_id=pid_province,
    )
    if parent_id:
        child_ids = await _load_child_product_ids(
            parent_id,
            province_id=pid_province,
        )
        if len(child_ids) > 1:
            return child_ids

    try:
        current_id = int(detail.get("product_id") or 0)
    except (TypeError, ValueError):
        return []

    stored: list[int] = []
    for raw in detail.get("child_product") or []:
        try:
            stored.append(int(raw))
        except (TypeError, ValueError):
            continue
    if len(stored) > 1:
        return stored

    for parent_candidate in _collect_up_sell_ids(detail):
        siblings = await _load_child_product_ids(
            parent_candidate,
            province_id=pid_province,
        )
        if current_id in siblings and len(siblings) > 1:
            return siblings

    return []


async def fetch_color_sibling_variants(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    """Lấy giá/tồn các màu sibling (child_product) của SKU cha."""
    if not detail or _is_browse_list_detail(detail):
        return None

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    sibling_ids = await _resolve_sibling_color_product_ids(
        detail,
        province_id=pid_province,
    )
    if len(sibling_ids) <= 1:
        return None

    products = await get_products_by_ids(sibling_ids, province_id=pid_province)
    if not products:
        return None

    variants: list[dict[str, Any]] = []
    for item in products:
        general = item.get("general") or {}
        filterable = item.get("filterable") or {}
        stock_avail = parse_stock_availability(filterable)
        sale_price, _ = _resolve_standard_prices(filterable)
        name = str(general.get("name") or "").strip()
        if not name:
            continue
        variants.append(
            {
                "product_id": str(general.get("product_id") or ""),
                "name": name,
                "price": _format_price(sale_price),
                "stock_status": stock_avail.get("display_status") or "",
                "stock_available_id": stock_avail.get("stock_available_id"),
                "stock_quantity": filterable.get("stock"),
                "url": graphql_product_url(general),
            }
        )

    if len(variants) <= 1:
        return None

    variants.sort(key=lambda row: row.get("name") or "")
    parent_id = await _resolve_color_parent_product_id(
        detail,
        province_id=pid_province,
    )
    return {
        "variants": variants,
        "count": len(variants),
        "current_product_id": str(detail.get("product_id") or ""),
        "parent_product_id": str(parent_id or ""),
    }


def _build_products_by_ids_query(product_ids: list[int]) -> str:
    ids_literal = ", ".join(f'"{i}"' for i in product_ids)
    return f"""
query GetProductsByIds($provinceId: Int!) {{
  products(
    filter: {{
      static: {{
        is_parent: ["false", "true"],
        province_id: $provinceId,
        product_id: [{ids_literal}],
        stock: {{ from: 0 }}
      }}
    }},
    size: {len(product_ids)}
  ) {{
    general {{
      product_id
      name
      url_path
      sku
      attributes
    }}
    filterable {{
      stock_available_id
      price
      special_price
      display_price
      thumbnail
    }}
  }}
}}
"""


async def get_products_by_ids(
    product_ids: list[int],
    *,
    province_id: int | None = None,
) -> list[dict[str, Any]]:
    ids = [int(i) for i in product_ids if i is not None]
    if not ids:
        return []
    query = _build_products_by_ids_query(ids)
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            query,
            {"provinceId": province_id if province_id is not None else CPS_PROVINCE_ID},
        )
    return payload.get("data", {}).get("products") or []


_RECOMMENDATION_HEADERS = {
    "accept": "application/json",
    "x-client-type": "web",
}


def _recommendation_product_id(detail: dict[str, Any]) -> str:
    """ID gửi recommendation API — ưu tiên parent/default (giống trang chi tiết)."""
    for key in ("parent_id", "default_product_id", "product_id"):
        val = str(detail.get(key) or "").strip()
        if val:
            return val
    return ""


_SIMILAR_CATEGORY_GROUPS: tuple[tuple[set[str], str], ...] = (
    ({"132", "927", "861", "169", "758", "201", "158", "588", "207", "495", "426", "781", "981", "1392"}, "132"),
    ({"944", "420", "725", "279", "368", "275", "280", "369", "2185", "2184"}, "944"),
    ({"5", "224", "212", "308", "208", "387", "23", "1119", "1120", "1530"}, "5"),
    ({"88", "596", "597", "716", "798", "857", "885", "995", "1296", "1297", "1403", "1741", "1742"}, "88"),
    ({"384", "1494"}, "384"),
)


def _box_same_product_categories(detail: dict[str, Any]) -> list[str]:
    """
    Map nhóm category giống `BoxSameProduct.vue`.
    Fallback: category_id đầu tiên hiện có trên detail.
    """
    category_ids = {
        str(cid).strip()
        for cid in (detail.get("category_ids") or [])
        if str(cid).strip()
    }
    primary = str(detail.get("category_id") or "").strip()
    if primary:
        category_ids.add(primary)
    for group_ids, mapped in _SIMILAR_CATEGORY_GROUPS:
        if category_ids & group_ids:
            return [mapped]
    if primary:
        return [primary]
    if category_ids:
        return [sorted(category_ids)[0]]
    return []


def _similar_price_range(detail: dict[str, Any]) -> tuple[int, int] | None:
    price_value = _price_amount(detail.get("price_value"))
    if not price_value or price_value <= 0:
        return None
    low = int(price_value * 0.9)
    high = int(price_value * 1.1)
    return max(low, 0), max(high, low)


async def fetch_recommended_products(
    product_id: str | int,
    *,
    province_id: int | None = None,
    max_products: int | None = None,
) -> list[dict[str, Any]]:
    """Gợi ý phụ kiện / sản phẩm mua cùng từ recommendation API."""
    if not CPS_RECOMMENDATION_ENABLED:
        return []

    pid = str(product_id).strip()
    if not pid:
        return []

    limit = max_products if max_products is not None else CPS_RECOMMENDATION_MAX_PRODUCTS
    limit = max(1, min(int(limit), 10))

    url = f"{CPS_API_BASE_URL}/recommendation/v1/recommend"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url,
                params={"product_id": pid},
                headers=_RECOMMENDATION_HEADERS,
            )
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.warning("Recommendation API lỗi product_id=%s: %s", pid, exc)
        return []

    raw_items = body.get("data") or []
    rec_ids: list[int] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            rec_pid = int(item.get("product_id"))
        except (TypeError, ValueError):
            continue
        if rec_pid not in rec_ids:
            rec_ids.append(rec_pid)
        if len(rec_ids) >= limit:
            break

    if not rec_ids:
        return []

    products = await get_products_by_ids(rec_ids, province_id=province_id)
    by_id: dict[int, dict[str, Any]] = {}
    for item in products:
        if not isinstance(item, dict):
            continue
        try:
            gid = int((item.get("general") or {}).get("product_id"))
        except (TypeError, ValueError):
            continue
        by_id[gid] = item

    records: list[dict[str, Any]] = []
    for rid in rec_ids:
        gql_item = by_id.get(rid)
        if gql_item:
            records.append(_graphql_product_to_search_record(gql_item))
    return records


async def fetch_similar_products(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Sản phẩm tương tự theo logic `BoxSameProduct.vue`."""
    categories = _box_same_product_categories(detail)
    price_range = _similar_price_range(detail)
    current_pid = str(detail.get("product_id") or "")
    if not categories or not price_range:
        return []

    low_price, high_price = price_range
    cat_literal = "[" + ", ".join(f'"{cid}"' for cid in categories) + "]"
    query = f"""
query SimilarProducts($provinceId: Int!) {{
  products(
    filter: {{
      static: {{
        is_parent: ["true"]
        categories: {cat_literal}
        province_id: $provinceId
        filter_price: {{
          from: {low_price}, to: {high_price}
        }}
      }}
    }}
    sort: [{{view: desc}}]
    size: {max(1, min(int(limit), 10))}
  ) {{
    filterable {{
      price
      special_price
      stock
      thumbnail
      promotion_pack
      sticker
      product_id
      filter_price
      stock_available_id
      display_price
      display_root_price
      delivery_badge
    }}
    general {{
      url_path
      doc_quyen
      url_key
      manufacturer
      name
      product_id
      review {{
        total_count
        average_rating
      }}
    }}
  }}
}}
"""
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            query,
            {"provinceId": pid_province},
        )
    products = payload.get("data", {}).get("products") or []
    rows: list[dict[str, Any]] = []
    for item in products:
        if not isinstance(item, dict):
            continue
        general = item.get("general") or {}
        filterable = item.get("filterable") or {}
        pid = str(general.get("product_id") or "")
        stock_qty = filterable.get("stock")
        try:
            stock_int = int(stock_qty) if stock_qty is not None else 0
        except (TypeError, ValueError):
            stock_int = 0
        if not pid or pid == current_pid or stock_int <= 0:
            continue
        rows.append(_graphql_product_to_search_record(item))
    return rows[: max(1, min(int(limit), 10))]


async def _fetch_child_product_ids(
    product_id: str | int,
    *,
    province_id: int | None = None,
) -> list[int]:
    """Lấy child_product từ parent SKU (cần is_parent=true — product(id) không trả field này)."""
    pid = str(product_id or "").strip()
    if not pid:
        return []
    query = f"""
query ChildProductIds($provinceId: Int!) {{
  products(
    filter: {{
      static: {{
        is_parent: ["true"],
        province_id: $provinceId,
        product_id: ["{pid}"],
        stock: {{ from: 0 }}
      }}
    }},
    size: 1
  ) {{
    general {{
      child_product
    }}
  }}
}}
"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            query,
            {"provinceId": province_id if province_id is not None else CPS_PROVINCE_ID},
        )
    products = payload.get("data", {}).get("products") or []
    if not products:
        return []
    raw_children = (products[0].get("general") or {}).get("child_product") or []
    ids: list[int] = []
    for raw in raw_children:
        try:
            cid = int(raw)
        except (TypeError, ValueError):
            continue
        if cid not in ids:
            ids.append(cid)
    return ids


async def _resolve_variant_from_ids(
    detail: dict[str, Any],
    candidate_ids: list[int],
    score_hints: list[str],
    *,
    province_id: int,
    keywords: str = "",
) -> dict[str, Any] | None:
    if not score_hints or len(candidate_ids) <= 1:
        return None

    products = await get_products_by_ids(candidate_ids, province_id=province_id)
    if keywords:
        products = _filter_products_by_model_tier(keywords, products)
    if not products:
        return None

    best_item: dict[str, Any] | None = None
    best_score = _variant_hint_score(detail.get("name") or "", score_hints)

    for item in products:
        general = item.get("general") or {}
        name = str(general.get("name") or "")
        score = _variant_hint_score(name, score_hints)
        if score > best_score:
            best_score = score
            best_item = item

    if not best_item or best_score <= 0:
        return None

    product_id = (best_item.get("general") or {}).get("product_id")
    if not product_id:
        return None

    product = await get_product_by_id(product_id, province_id=province_id)
    if not product:
        return None

    url_path = str((best_item.get("general") or {}).get("url_path") or "")
    resolved = normalize_product_detail(
        product,
        url=_full_url(url_path) if url_path else detail.get("url") or "",
    )
    resolved["variant_resolved_from"] = detail.get("product_id")
    return resolved


def _default_filterable_product_id(product: dict[str, Any] | None) -> str:
    """product_id biến thể mặc định từ filterable.default (giá/tồn/KM chuẩn)."""
    if not product:
        return ""
    filterable = product.get("filterable") or {}
    default = filterable.get("default")
    if isinstance(default, dict) and default.get("product_id") is not None:
        return str(default.get("product_id")).strip()
    general = product.get("general") or {}
    return str(general.get("product_id") or "").strip()


def is_commerce_detail_query(text: str) -> bool:
    """Câu hỏi cần giá/tồn/KM chính xác theo biến thể (default hoặc màu)."""
    value = text or ""
    if not value.strip():
        return False
    scenarios = classify_question_scenarios(value)
    return any(
        scenarios.get(key)
        for key in (
            "price_promotion",
            "stock_status",
            "shop_stock",
            "installment",
            "flash_sale",
            "incoming_stock",
            "combo",
        )
    )


def _is_browse_list_detail(detail: dict[str, Any]) -> bool:
    return bool(
        detail.get("category_filter_list_mode")
        or detail.get("stock_browse_list_mode")
        or detail.get("budget_browse_list_mode")
    )


async def resolve_commerce_product_detail(
    detail: dict[str, Any],
    *,
    keywords: str = "",
    user_message: str = "",
    province_id: int | None = None,
) -> dict[str, Any]:
    """
    Giá/tồn/KM: lấy detail parent trước → refetch theo filterable.default.product_id.
    Nếu user hỏi màu/dung lượng → refetch đúng biến thể đó (resolve_product_variant).
    """
    if not detail or _is_browse_list_detail(detail):
        return detail

    query_text = (user_message or keywords or "").strip()
    if is_color_variant_list_query(query_text):
        return detail
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID

    hints = _extract_variant_hints(query_text)
    color_hints, storage_hints, _screen_hints = _split_variant_hints(hints)

    if hints:
        before_id = str(detail.get("product_id") or "")
        detail = await resolve_product_variant(
            query_text,
            detail,
            province_id=pid_province,
        )
        after_id = str(detail.get("product_id") or "")
        if color_hints or (storage_hints and before_id != after_id):
            return detail

    if not is_commerce_detail_query(query_text):
        return detail

    kw_color, kw_storage, _kw_screen = _split_variant_hints(
        _extract_variant_hints(keywords)
    )
    if not hints and (kw_color or kw_storage):
        return await resolve_product_variant(
            keywords,
            detail,
            province_id=pid_province,
        )

    default_id = str(detail.get("default_product_id") or "").strip()
    if not default_id:
        current_id = detail.get("product_id")
        if current_id:
            parent = await get_product_by_id(current_id, province_id=pid_province)
            default_id = _default_filterable_product_id(parent)

    current_id = str(detail.get("product_id") or "").strip()
    if default_id and default_id != current_id:
        product = await get_product_by_id(default_id, province_id=pid_province)
        if product:
            resolved = normalize_product_detail(
                product,
                url=detail.get("url") or "",
                url_info={
                    "product_id": default_id,
                    "category_id": detail.get("category_id", ""),
                },
            )
            resolved["default_product_id"] = default_id
            resolved["commerce_resolved_from"] = current_id
            logger.info(
                "Commerce detail: refetch default variant %s → %s (query=%r)",
                current_id,
                default_id,
                query_text[:80],
            )
            return resolved

    return detail


async def resolve_product_variant(
    keywords: str,
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> dict[str, Any]:
    """Chọn biến thể màu (child_product) hoặc dung lượng (up_sell) khớp từ khóa."""
    hints = _extract_variant_hints(keywords)
    if not hints:
        return detail

    color_hints, storage_hints, _screen_hints = _split_variant_hints(hints)
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    current_name = detail.get("name") or ""

    if _variant_hint_score(current_name, hints) >= len(hints) * 10:
        return detail

    resolved = detail

    if storage_hints and _variant_hint_score(current_name, storage_hints) < len(
        storage_hints
    ) * 10:
        storage_match = await _resolve_variant_from_ids(
            resolved,
            _collect_up_sell_ids(resolved),
            storage_hints,
            province_id=pid_province,
            keywords=keywords,
        )
        if storage_match:
            resolved = storage_match

    if color_hints and _variant_hint_score(
        resolved.get("name") or "", color_hints
    ) < len(color_hints) * 10:
        parent_id = await _resolve_color_parent_product_id(
            resolved,
            province_id=pid_province,
        )
        child_ids = (
            await _load_child_product_ids(parent_id, province_id=pid_province)
            if parent_id
            else []
        )
        if child_ids:
            color_match = await _resolve_variant_from_ids(
                resolved,
                child_ids,
                color_hints,
                province_id=pid_province,
                keywords=keywords,
            )
            if color_match:
                resolved = color_match
                resolved["child_product"] = child_ids
                if parent_id:
                    resolved["parent_id"] = str(parent_id)

    return resolved


def _parse_shop_stock_from_nuxt(html: str) -> list[dict[str, Any]]:
    """
    Parse listShopStock từ __NUXT__ trên trang SP.
    Fallback khi API shops_stock trả rỗng (thường gặp trên production).
    """
    match = re.search(r"window\.__NUXT__\s*=\s*(.*?);</script>", html, re.S)
    if not match:
        return []

    raw = match.group(1)
    start = raw.find("listShopStock:[")
    if start < 0:
        return []

    region = raw[start : start + 300000]
    districts: list[dict[str, Any]] = []
    for part in re.split(r"\},\{district_id:", region):
        district_match = re.search(r'district_name:"([^"]+)"', part)
        if not district_match:
            continue
        district_name = district_match.group(1)
        shops: list[dict[str, Any]] = []
        for shop_match in re.finditer(
            r'address:"([^"]+)"(?:,phone:"([^"]*)")?(?:,near:"([^"]*)")?',
            part,
        ):
            near = shop_match.group(3) or ""
            if near in {"e", "a", "b", "c", "d", "f", "g", "h", "i", "j", "k"}:
                near = ""
            shops.append(
                {
                    "address": shop_match.group(1),
                    "phone": shop_match.group(2) or "",
                    "near": near,
                }
            )
        if shops:
            districts.append({"district_name": district_name, "shops": shops})
    return districts


async def fetch_shop_stock_from_product_page(
    url_path: str,
    *,
    province_id: int | None = None,
) -> list[dict[str, Any]]:
    """Lấy tồn cửa hàng từ trang SP (NUXT listShopStock)."""
    path = (url_path or "").strip().lstrip("/")
    if not path:
        return []

    page_url = _full_url(path)
    province_name = PROVINCE_ID_TO_NAME.get(
        province_id if province_id is not None else CPS_PROVINCE_ID,
        "",
    )

    try:
        async with httpx.AsyncClient(
            headers=_PAGE_FETCH_HEADERS,
            timeout=30.0,
            follow_redirects=True,
        ) as client:
            response = await client.get(page_url)
            response.raise_for_status()
            districts = _parse_shop_stock_from_nuxt(response.text)
    except Exception as exc:
        logger.warning("Không parse được tồn cửa hàng từ %s: %s", page_url, exc)
        return []

    if not districts:
        return []

    logger.info(
        "Tồn cửa hàng từ trang SP: %s — %d quận, %d shop",
        path,
        len(districts),
        sum(len(d.get("shops") or []) for d in districts),
    )
    for district in districts:
        district["province_name"] = province_name
        district["province_id"] = province_id if province_id is not None else CPS_PROVINCE_ID
    return districts


async def fetch_product_from_url(url: str, *, keywords: str = "") -> dict[str, Any]:
    """URL CellphoneS → detail chuẩn hóa."""
    info = await url_info(url)
    if not info:
        raise ValueError(f"Không resolve được URL info: {url}")

    product: dict[str, Any] | None = None
    product_id = info.get("product_id")
    if product_id:
        product = await get_product_by_id(product_id)
        if not product:
            raise ValueError(f"Không lấy được chi tiết product_id={product_id}")
    elif info.get("category_id"):
        cate_products = await get_products_by_category_id(info["category_id"])
        selected = _pick_best_category_product(
            cate_products,
            request_path=extract_request_path(url),
            keywords=keywords,
        )
        if not selected:
            raise ValueError(
                f"Không tìm được sản phẩm theo category_id={info['category_id']}"
            )
        product = {
            "general": selected.get("general") or {},
            "filterable": selected.get("filterable") or {},
            "specification": {},
        }
    else:
        raise ValueError(f"URL info không có product_id/category_id: {url}")

    return normalize_product_detail(
        product,
        url=_full_url(extract_request_path(url)),
        url_info=info,
    )


def _build_category_filter_summary(
    req: Any,
    search_results: list[dict[str, Any]],
    province_id: int,
    *,
    filter_url: str = "",
) -> dict[str, Any]:
    from cps_bot.browse.category_filter_browse import describe_category_filter

    prov_name = PROVINCE_ID_TO_NAME.get(province_id, "")
    filter_desc = describe_category_filter(req)
    resolved_url = (filter_url or "").strip()
    if not resolved_url:
        from cps_bot.browse.category_filter_browse import build_category_filter_url

        resolved_url = build_category_filter_url(req, None)
    return {
        "name": f"Danh sách {filter_desc}",
        "price": "",
        "old_price": "",
        "description": (
            f"Có {len(search_results)} sản phẩm khớp bộ lọc {filter_desc}"
            + (f" tại {prov_name}" if prov_name else "")
            + "."
        ),
        "specifications": {},
        "stock_status": "",
        "url": resolved_url,
        "category_url": resolved_url,
        "thumbnail": "",
        "product_id": "",
        "category_filter_list_mode": True,
        "category_filter_id": req.category_id,
        "category_filter_name": req.category_name,
        "category_filter_matched": req.matched_filters,
        "category_filter_url": resolved_url,
        "product_count": len(search_results),
    }


def _append_api_call(stats: dict[str, Any], **entry: Any) -> None:
    from cps_bot.core.api_trace import record_api_call

    record_api_call(stats, **entry)


async def _fetch_products_by_category_filter(
    keywords: str,
    user_message: str,
    *,
    province_id: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
    """Browse SP qua GraphQL category + dynamic attribute filter."""
    from cps_bot.browse.category_filter_browse import (
        build_category_filter_url,
        is_category_filter_browse_query,
        resolve_category_filter_request,
        resolve_filter_price,
    )
    from cps_bot.cps.cps_category_filter import get_products_by_category_filter

    query_text = user_message or keywords
    if not is_category_filter_browse_query(query_text):
        return None

    req = resolve_category_filter_request(query_text)
    if not req:
        return None

    filter_price = resolve_filter_price(user_message)
    filter_url = build_category_filter_url(req, filter_price)
    products: list[dict[str, Any]] = []

    if req.dynamic_filter or filter_price:
        products = await get_products_by_category_filter(
            req.category_id,
            req.dynamic_filter or "",
            province_id=province_id,
            size=12,
            filter_price=filter_price,
        )
    elif req.is_subcategory_menu:
        products = await get_products_by_category_id(
            req.category_id,
            province_id=province_id,
            size=12,
        )

    if not products:
        return None

    search_results = [_graphql_product_to_search_record(p) for p in products[:12]]
    detail = _build_category_filter_summary(
        req,
        search_results,
        province_id,
        filter_url=filter_url,
    )
    return search_results, detail


async def fetch_product_for_query(
    keywords: str,
    *,
    user_message: str = "",
    fallback_url: str = "",
    fallback_product_id: str | int = "",
    session_fallback_parent_id: str | int = "",
    session_last_keywords: str = "",
    session_last_product_name: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """
    Tìm sản phẩm theo link trong tin nhắn, URL session cũ, hoặc quick_search.
    Chi tiết lấy qua CPS GraphQL (không scrape HTML).
    """
    from cps_bot.core.api_trace import api_trace_scope

    stats: dict[str, Any] = {
        "serpapi_calls": 0,
        "search_products_calls": 0,
        "cps_url_info_calls": 0,
        "cps_product_detail_calls": 0,
        "category_filter_calls": 0,
        "api_calls_detail": [],
        "resolve_source": "",
    }

    async with api_trace_scope(stats):
        return await _fetch_product_for_query_body(
            keywords,
            user_message=user_message,
            fallback_url=fallback_url,
            fallback_product_id=fallback_product_id,
            session_fallback_parent_id=session_fallback_parent_id,
            session_last_keywords=session_last_keywords,
            session_last_product_name=session_last_product_name,
            stats=stats,
        )


async def _fetch_product_for_query_body(
    keywords: str,
    *,
    user_message: str = "",
    fallback_url: str = "",
    fallback_product_id: str | int = "",
    session_fallback_parent_id: str | int = "",
    session_last_keywords: str = "",
    session_last_product_name: str = "",
    stats: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    target_url = ""
    for url in extract_cellphones_urls(user_message):
        target_url = url
        stats["resolve_source"] = "user_url"
        break

    search_results: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}

    from cps_bot.llm.gemini_client import identity_compatible_with_session

    identity_ok = identity_compatible_with_session(
        user_message or keywords,
        last_keywords=session_last_keywords,
        last_product_name=session_last_product_name,
    )

    fallback_pid = str(fallback_product_id or "").strip()
    if not identity_ok and (fallback_pid or fallback_url):
        logger.info(
            "Bỏ session fallback product/url — câu mới không khớp model session (%r)",
            (user_message or keywords)[:80],
        )
        fallback_pid = ""
        fallback_url = ""

    color_list_query = is_color_variant_list_query(user_message or keywords)
    session_parent_pid = str(session_fallback_parent_id or "").strip()

    if not target_url and fallback_pid and color_list_query and session_parent_pid:
        detail = {
            "product_id": fallback_pid,
            "parent_id": session_parent_pid,
            "name": session_last_product_name or "",
            "url": fallback_url or "",
        }
        stats["resolve_source"] = "session_color_list_context"
        logger.info(
            "Hỏi danh sách màu — dùng parent_id=%s (variant hiện tại=%s), bỏ refetch child",
            session_parent_pid,
            fallback_pid,
        )

    if not detail and target_url:
        try:
            stats["cps_url_info_calls"] += 1
            stats["cps_product_detail_calls"] += 1
            detail = await fetch_product_from_url(target_url, keywords=keywords)
            if detail:
                variant_query = merge_follow_up_variant_into_keywords(
                    keywords,
                    user_message,
                )
                province_id = resolve_province_from_text(user_message)
                detail = await resolve_product_variant(
                    variant_query or keywords,
                    detail,
                    province_id=province_id,
                )
        except Exception as exc:
            logger.warning("CPS fetch thất bại (%s): %s", target_url, exc)
            return [], {}, stats
    elif not detail:
        province_id = resolve_province_from_text(user_message) or CPS_PROVINCE_ID
        map_terms = _product_terms_for_resolution(keywords, user_message)
        search_terms = _api_search_terms(keywords, user_message)
        prioritize_product_detail = not _is_category_filter_browse_query(
            user_message or keywords
        )
        stock_hit = await _fetch_product_by_stock_filter(
            keywords,
            user_message,
            province_id=province_id,
        )
        if stock_hit:
            search_results, detail = stock_hit
            stats["resolve_source"] = "stock_status_filter"
            stats["stock_filter_ids"] = detail.get("stock_filter_ids") or []
            if not detail.get("stock_browse_list_mode"):
                stats["cps_product_detail_calls"] += 1

        if not detail:
            if prioritize_product_detail and map_terms and _is_product_map_query(map_terms):
                map_hit = await _fetch_product_from_map(
                    map_terms,
                    province_id=province_id,
                )
                if map_hit:
                    search_results, detail = map_hit
                    stats["resolve_source"] = "product_map"
                    stats["product_map_id"] = detail.get("product_id", "")
                    stats["product_map_score"] = detail.get("product_map_score", 0)
                    stats["product_map_confidence"] = detail.get("product_map_confidence", 0)
                    _append_api_call(
                        stats,
                        name="Product map",
                        operation="product_map",
                        endpoint=PRODUCT_MAP_PATH,
                        query=map_terms,
                        product_id=detail.get("product_id", ""),
                        matched_name=detail.get("product_map_matched_name", ""),
                    )

        if not detail:
            category_filter_hit = await _fetch_products_by_category_filter(
                keywords,
                user_message,
                province_id=province_id,
            )
            if category_filter_hit:
                search_results, detail = category_filter_hit
                stats["resolve_source"] = "category_filter"
                stats["category_filter_id"] = detail.get("category_filter_id") or ""
                stats["category_filter_calls"] = 1
                filter_url = str(detail.get("category_filter_url") or "")
                stats["resolved_filter_url"] = filter_url
                _append_api_call(
                    stats,
                    name="GraphQL products (category filter)",
                    operation="GetProductsByCategoryFilter",
                    endpoint=CPS_GRAPHQL_V2_ENDPOINT,
                    filter_url=filter_url,
                    category_id=detail.get("category_filter_id") or "",
                    matched_filters=detail.get("category_filter_matched") or [],
                )

        if not detail:
            budget_hit = await _fetch_products_by_budget_browse(
                keywords,
                user_message,
                province_id=province_id,
            )
            if budget_hit:
                search_results, detail = budget_hit
                stats["resolve_source"] = "budget_browse"
                stats["budget_label"] = detail.get("budget_label") or ""
                stats["search_products_calls"] += 1
                search_kw = (
                    keywords.strip()
                    or detail.get("budget_category")
                    or strip_budget_phrases_for_keywords(user_message)
                )
                _append_api_call(
                    stats,
                    name="CPS GraphQL Search",
                    operation="search_products",
                    endpoint=CPS_GRAPHQL_V2_ENDPOINT,
                    query=search_kw,
                    budget_label=detail.get("budget_label") or "",
                )

        # Layer 0: product map — fallback khi category browse được ưu tiên nhưng chưa resolve
        if not detail and map_terms and _is_product_map_query(map_terms):
            if not prioritize_product_detail:
                map_hit = await _fetch_product_from_map(
                    map_terms,
                    province_id=province_id,
                )
                if map_hit:
                    search_results, detail = map_hit
                    stats["resolve_source"] = "product_map"
                    stats["product_map_id"] = detail.get("product_id", "")
                    stats["product_map_score"] = detail.get("product_map_score", 0)
                    stats["product_map_confidence"] = detail.get("product_map_confidence", 0)
                    _append_api_call(
                        stats,
                        name="Product map",
                        operation="product_map",
                        endpoint=PRODUCT_MAP_PATH,
                        query=map_terms,
                        product_id=detail.get("product_id", ""),
                        matched_name=detail.get("product_map_matched_name", ""),
                    )

        # Layer 1: CPS search (advanced_search → quick_search fallback)
        if not detail and search_terms:
            stats["search_products_calls"] += 1
            _append_api_call(
                stats,
                name="CPS GraphQL Search",
                operation="search_products",
                endpoint=CPS_GRAPHQL_V2_ENDPOINT,
                query=search_terms,
            )
            search_results = await search_products(
                search_terms,
                province_id=province_id,
            )
            if search_results:
                stats["resolve_source"] = "search_results"
                best = _pick_best_search_result(search_results, search_terms)
                pick_url = product_url_from_record(best or search_results[0])
                if pick_url:
                    try:
                        stats["cps_url_info_calls"] += 1
                        stats["cps_product_detail_calls"] += 1
                        detail = await fetch_product_from_url(pick_url, keywords=search_terms)
                        if detail and search_terms:
                            detail = await resolve_product_variant(
                                search_terms,
                                detail,
                                province_id=province_id,
                            )
                    except Exception as exc:
                        logger.warning("CPS fetch thất bại (%s): %s", pick_url, exc)
                if len(search_results) >= 2 and search_results_need_advanced(
                    search_results[:2], search_terms
                ):
                    stats["ambiguous_search"] = True

        # Layer 2: SerpAPI (chỉ khi CPS search không có kết quả)
        serp_urls: list[str] = []
        use_serp = SERPAPI_ENABLED and bool(SERPAPI_API_KEY)
        if not detail and use_serp:
            stats["serpapi_calls"] += 1
            try:
                from cps_bot.core.api_trace import build_curl_get

                query = f"site:cellphones.com.vn {search_terms}".strip()
                params = {
                    "engine": "google",
                    "q": query,
                    "api_key": SERPAPI_API_KEY,
                    "num": 10,
                }
                _append_api_call(
                    stats,
                    name="SerpAPI",
                    operation="serpapi",
                    method="GET",
                    endpoint=SERPAPI_ENDPOINT,
                    query=query,
                    variables=params,
                    curl=build_curl_get(SERPAPI_ENDPOINT, params=params),
                )
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(SERPAPI_ENDPOINT, params=params)
                    response.raise_for_status()
                    data = response.json()
                for item in data.get("organic_results", []) or []:
                    link = str(item.get("link") or "").strip()
                    if _is_cellphones_product_url(link) and link not in serp_urls:
                        serp_urls.append(link)
                serp_urls.sort(key=_serp_url_score, reverse=True)
            except Exception as exc:
                logger.warning("SerpAPI lỗi: %s", exc)

        if not detail and serp_urls:
            stats["resolve_source"] = "serpapi"
            for url in serp_urls:
                try:
                    stats["cps_url_info_calls"] += 1
                    stats["cps_product_detail_calls"] += 1
                    detail = await fetch_product_from_url(url, keywords=keywords)
                    if detail:
                        if keywords:
                            detail = await resolve_product_variant(
                                keywords,
                                detail,
                                province_id=province_id,
                            )
                        break
                except Exception as exc:
                    logger.warning("CPS fetch thất bại (%s): %s", url, exc)

    if not detail and identity_ok and (fallback_pid or fallback_url):
        detail = await _apply_session_product_fallback(
            fallback_pid=fallback_pid,
            fallback_url=fallback_url,
            session_parent_pid=session_parent_pid,
            session_last_product_name=session_last_product_name,
            user_message=user_message,
            keywords=keywords,
            stats=stats,
        )

    if not detail:
        return search_results, {}, stats

    if not search_results:
        search_results = [
            normalize_search_result(
                {
                    "name": detail.get("name", ""),
                    "price": detail.get("price", ""),
                    "url_path": detail.get("url_path", ""),
                    "url": detail.get("url", ""),
                    "thumbnail": detail.get("thumbnail", ""),
                    "product_id": detail.get("product_id", ""),
                }
            )
        ]
    else:
        search_results = normalize_search_results(search_results)

    if detail and not _is_browse_list_detail(detail):
        if not color_list_query:
            commerce_province = resolve_province_from_text(user_message) or CPS_PROVINCE_ID
            detail = await resolve_commerce_product_detail(
                detail,
                keywords=keywords,
                user_message=user_message,
                province_id=commerce_province,
            )

    return search_results, detail, stats


_SHOP_STOCK_KEYWORD_STRIP_RES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\s+"
        r"(?:gần|gan\s+)?(?:quận|quan|huyện|huyen|phường|phuong)\s+\d+\s+"
        r"(?:còn|co(?:\s+hàng|\s+hang)?)\s+",
        re.I,
    ),
    re.compile(
        r"^(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\s+"
        r"(?:quận|quan|huyện|huyen|phường|phuong)\s+\d+\s+"
        r"(?:còn|co(?:\s+hàng|\s+hang)?)\s+",
        re.I,
    ),
    re.compile(
        r"^(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\s+"
        r"(?:gần|gan\s+)?[qQ]\.?\s*\d+\s+"
        r"(?:còn|co(?:\s+hàng|\s+hang)?)\s+",
        re.I,
    ),
    re.compile(
        r"^(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\s+"
        r"(?:gần|gan\s+)?(?:tôi|toi|mình|minh|đây|day)\s+"
        r"(?:còn|co(?:\s+hàng|\s+hang)?)\s+",
        re.I,
    ),
    re.compile(r"(?:gần|gan)\s+(?:quận|quan|huyện|huyen|phường|phuong)\s+\d+", re.I),
    re.compile(r"(?:gần|gan)\s+[qQ]\.?\s*\d+", re.I),
    re.compile(r"\s+(?:ở|o)\s+(?:shop|cửa hàng|cua hang|quận|quan)\b[^.?]*", re.I),
    re.compile(r"\s+(?:còn|có|co)\s+(?:hàng|hang)\s*(?:không|khong|ko|k)\??\s*$", re.I),
    re.compile(r"\s+(?:không|khong|ko|k)\??\s*$", re.I),
)

# SP đứng trước cụm hừ tồn CH: "iPhone 17 còn hàng ở cửa hàng nào"
_SHOP_STOCK_PRODUCT_FIRST_SUFFIX_RE = re.compile(
    r"\s+(?:"
    r"có hàng ở cửa hàng nào|còn hàng ở cửa hàng nào|"
    r"ở cửa hàng nào|o cua hang nao|"
    r"có ở cửa hàng|còn ở cửa hàng|co o cua hang|con o cua hang|"
    r"cửa hàng nào(?: còn| có)?|cua hang nao(?: con| co)?|"
    r"chi nhánh nào(?: còn| có)?|chi nhanh nao(?: con| co)?|"
    r"shop nào(?: còn| có)?|shop nao(?: con| co)?|"
    r"ở đâu còn|o dau con|hàng ở đâu|hang o dau|"
    r"gần nhất|gan nhat|"
    r"còn tồn những màu nào|con ton nhung mau nao|"
    r"còn tồn|con ton"
    r").*$",
    re.IGNORECASE,
)

# "Còn hàng {SP} ở shop..." — SP ngay sau còn hàng
_SHOP_STOCK_CON_HANG_THEN_PRODUCT_RE = re.compile(
    r"(?:^|\s)(?:còn|co)\s+(?:hàng|hang)\s+(.+?)\s+(?:"
    r"(?:ở|o)\s+(?:shop|cửa hàng|cua hang|quận|quan)|"
    r"(?:không|khong|ko|k)\??"
    r")",
    re.I,
)

_SHOP_STOCK_PRODUCT_AFTER_CON_RE = re.compile(
    r"(?:còn|co)(?:\s+hàng|\s+hang)?\s+(.+?)\s*(?:"
    r"(?:không|khong|ko|k)\??|"
    r"(?:ở|o)\s+(?:shop|cửa hàng|cua hang|quận|quan)"
    r")(?:\s|$|\?)",
    re.I,
)

_COMBO_STOCK_PRODUCT_RE = re.compile(
    r"combo\s+(.+?)\s*$",
    re.I,
)
_GENERIC_STOCK_WORDS = frozenset({"hàng", "hang", "còn", "co", "có", "tồn", "ton"})

_SHOP_STOCK_PRODUCT_AFTER_CON_TON_RE = re.compile(
    r"còn\s+tồn\s+(.+?)(?:\s+(?:không|khong|ko|k)\??\s*)?$",
    re.I,
)
_SHOP_STOCK_PRODUCT_AFTER_SHOP_CON_TON_RE = re.compile(
    r"shop nào còn tồn\s+(.+?)(?:\s+(?:không|khong|ko|k)\??\s*)?$",
    re.I,
)
_STOCK_AT_LOCATION_FOR_PRODUCT_RE = re.compile(
    r"^tồn kho\s+(?:tại|tai|ở|o)\s+.+?\s+cho\s+(.+)$",
    re.I,
)


def needs_shop_stock_keyword_strip(text: str) -> bool:
    """Câu hỏi tồn cửa hàng / shop theo khu vực — cần bóc tên SP trước khi search."""
    if is_stock_availability_query(text):
        return True
    lower = (text or "").lower()
    has_shop = bool(re.search(r"\b(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\b", lower))
    has_stock_ask = bool(re.search(r"\b(?:còn|co|có|con|không|khong)\b", lower))
    has_district = bool(
        _DISTRICT_HINT_RE.search(text or "")
        or _DISTRICT_HINT_LOOSE_RE.search(text or "")
        or _DISTRICT_ABBREV_RE.search(text or "")
    )
    has_ton_kho = bool(re.search(r"\btồn kho\b|\bton kho\b", lower))
    return (
        (has_shop and has_stock_ask)
        or (has_shop and has_district)
        or (has_district and has_stock_ask)
        or (has_ton_kho and has_district)
    )


def strip_shop_stock_phrases_for_keywords(text: str) -> str:
    """Bóc cụm shop/khu vực/tồn — chỉ giữ tên sản phẩm cho API search."""
    s = (text or "").strip().rstrip("?").strip()
    if not s:
        return ""

    product_before_ton_colors = re.match(
        r"^(.+?)\s+còn\s+tồn\s+(?:những\s+)?màu nào\s*$",
        s,
        re.I,
    )
    if product_before_ton_colors:
        return product_before_ton_colors.group(1).strip()

    combo_match = _COMBO_STOCK_PRODUCT_RE.search(s)
    if combo_match:
        return combo_match.group(1).strip()

    at_loc = _STOCK_AT_LOCATION_FOR_PRODUCT_RE.match(s)
    if at_loc:
        product = at_loc.group(1).strip()
        if product and product.lower() not in _GENERIC_STOCK_WORDS:
            return product

    match = _SHOP_STOCK_PRODUCT_AFTER_SHOP_CON_TON_RE.search(s)
    if match:
        product = match.group(1).strip()
        if product and product.lower() not in _GENERIC_STOCK_WORDS:
            return product

    match = _SHOP_STOCK_PRODUCT_AFTER_CON_TON_RE.search(s)
    if match:
        product = match.group(1).strip()
        if product and product.lower() not in _GENERIC_STOCK_WORDS:
            return product

    product_first = _SHOP_STOCK_PRODUCT_FIRST_SUFFIX_RE.sub("", s).strip()
    if product_first and product_first != s:
        return product_first

    match = _SHOP_STOCK_CON_HANG_THEN_PRODUCT_RE.search(s)
    if match:
        product = match.group(1).strip()
        if product and product.lower() not in _GENERIC_STOCK_WORDS:
            return product

    match = _SHOP_STOCK_PRODUCT_AFTER_CON_RE.search(s)
    if match:
        product = match.group(1).strip()
        product = re.sub(r"^(?:hàng|hang)\s+", "", product, flags=re.I)
        if product and product.lower() not in _GENERIC_STOCK_WORDS:
            return product

    for pattern in _SHOP_STOCK_KEYWORD_STRIP_RES:
        s = pattern.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_shop_stock_question(text: str) -> bool:
    """Câu hỏi về tồn tại cửa hàng/chi nhánh (kịch bản kiểm tra tồn kho)."""
    return bool(_SHOP_STOCK_QUESTION_RE.search(text or ""))


def is_district_stock_query(text: str) -> bool:
    """Câu có gợi ý quận/khu vực + hỏi còn hàng — vd. 'ở quận 10 có không?'."""
    value = text or ""
    hint = extract_location_hint(value)
    if not hint:
        return False
    if _DISTRICT_STOCK_INTENT_RE.search(value):
        return True
    if _DISTRICT_TAIL_AVAILABILITY_RE.search(value):
        return True
    if _SHOP_DISTRICT_STOCK_RE.search(value) and re.search(
        r"\b(?:còn|co|có|con)\b", value, re.IGNORECASE
    ):
        return True
    return bool(
        _DISTRICT_AVAILABILITY_RE.search(value)
        or _STOCK_STATUS_QUESTION_RE.search(value)
        or _SHOP_STOCK_QUESTION_RE.search(value)
    )


def is_stock_availability_query(text: str) -> bool:
    """Câu hỏi tồn kho / còn hàng — online hoặc theo cửa hàng / quận / tỉnh."""
    value = text or ""
    if is_shop_stock_question(value):
        return True
    if _STOCK_STATUS_QUESTION_RE.search(value):
        return True
    if is_district_stock_query(value):
        return True
    if is_province_stock_query(value):
        return True
    return False


_PROVINCE_STOCK_INTENT_RE = re.compile(
    r"\b(?:"
    r"còn hàng|con hang|có hàng|co hang|"
    r"hết hàng|het hang|tồn kho|ton kho|"
    r"còn tồn|con ton"
    r")\b",
    re.IGNORECASE,
)


def is_province_stock_query(text: str) -> bool:
    """Hỏi tồn/còn hàng theo tỉnh — vd. 'Có hàng ở Bình Phước ko?'."""
    value = text or ""
    if resolve_province_from_text(value) is None:
        return False
    if _PROVINCE_STOCK_INTENT_RE.search(value):
        return True
    if re.search(
        r"\b(?:có|co|còn|con)\b.+\b(?:ko|khong|không|k)\??\s*$",
        value,
        re.IGNORECASE,
    ):
        return True
    return bool(_STOCK_STATUS_QUESTION_RE.search(value))


def should_attach_shop_stock(
    text: str,
    *,
    resume: bool = False,
    reuse_product_context: bool = False,
) -> bool:
    """
    Có nên gọi GraphQL SHOP_STOCK (shops_stock) để lấy danh sách cửa hàng còn tồn.
    """
    if resume:
        return True
    value = text or ""
    if is_stock_availability_query(value):
        return True
    # Hỏi tiếp chỉ nêu quận: "quận 10", "ở Q10" — đã có SP trong session.
    if reuse_product_context and extract_location_hint(value):
        return True
    if reuse_product_context and (
        _STOCK_STATUS_QUESTION_RE.search(value)
        or _DISTRICT_AVAILABILITY_RE.search(value)
        or _DISTRICT_TAIL_AVAILABILITY_RE.search(value)
        or _PROVINCE_STOCK_INTENT_RE.search(value)
    ):
        return True
    return False


def _is_category_filter_browse_query(text: str) -> bool:
    from cps_bot.browse.category_filter_browse import is_category_filter_browse_query

    return is_category_filter_browse_query(text)


def classify_question_scenarios(text: str) -> dict[str, bool]:
    """Phân loại kịch bản CSV — dùng để enrich payload và prompt Gemini."""
    value = text or ""
    from cps_bot.cps.cps_installment import is_installment_query

    installment = bool(_INSTALLMENT_QUESTION_RE.search(value)) or is_installment_query(value)
    return {
        "price_promotion": bool(_PRICE_QUESTION_RE.search(value)),
        "shop_stock": is_stock_availability_query(value),
        "trade_in": bool(_TRADE_IN_QUESTION_RE.search(value)),
        "installment": installment,
        "warranty": bool(_WARRANTY_QUESTION_RE.search(value)),
        "compare": bool(_COMPARE_QUESTION_RE.search(value)),
        "specs": bool(_SPECS_QUESTION_RE.search(value)),
        "advice": bool(_ADVICE_QUESTION_RE.search(value)),
        "incoming_stock": bool(_INCOMING_STOCK_RE.search(value)),
        "stock_status": bool(_STOCK_STATUS_QUESTION_RE.search(value)),
        "stock_browse": is_stock_status_browse_query(value),
        "budget_browse": is_budget_browse_query(value),
        "category_filter_browse": _is_category_filter_browse_query(value),
        "reviews": bool(_REVIEWS_QUESTION_RE.search(value)),
        "faq_policy": bool(_FAQ_POLICY_RE.search(value)),
        "flash_sale": bool(_FLASH_SALE_RE.search(value)),
        "trade_in_device": bool(_TRADE_DEVICE_RE.search(value)),
        "store_locator": bool(_STORE_LOCATOR_RE.search(value)),
        "combo": bool(_COMBO_QUESTION_RE.search(value)),
        "color_variants": is_color_variant_list_query(value),
    }


async def fetch_trade_promo_for_product(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    """Trợ giá thu cũ / trade-in — graphql-dashboard trade_promo."""
    product_id = detail.get("product_id")
    if not product_id:
        return None
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None

    category_ids = [str(c) for c in (detail.get("category_ids") or []) if c]
    if not category_ids and detail.get("category_id"):
        category_ids = [str(detail["category_id"])]

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    company_id = company_id_for_province(pid_province)

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            TRADE_PROMO_QUERY,
            {
                "productId": pid,
                "categoryIds": category_ids,
                "companyId": company_id,
            },
        )
    promo = payload.get("data", {}).get("trade_promo")
    if not promo:
        return None

    promo_value = _price_amount(promo.get("promo_value"))
    pmh = _price_amount(promo.get("pmh"))
    return {
        "product_id": promo.get("product_id"),
        "promo_value": int(promo_value) if promo_value else 0,
        "promo_value_formatted": _format_price(promo_value) if promo_value else "",
        "pmh": int(pmh) if pmh else 0,
        "pmh_formatted": _format_price(pmh) if pmh else "",
        "company_id": company_id,
        "note": (
            "Giá trị tham khảo từ chương trình trade-in CellphoneS; "
            "giá thu cũ thực tế phụ thuộc tình trạng máy."
        ),
    }


async def fetch_extended_warranty_for_product(
    detail: dict[str, Any],
) -> dict[str, Any] | None:
    """Gói bảo hành mở rộng — graphql-dashboard extended_warranty."""
    product_id = detail.get("product_id")
    price_value = detail.get("price_value")
    if not product_id or not price_value:
        return None
    try:
        pid = int(product_id)
        categories = [int(c) for c in (detail.get("category_ids") or []) if str(c).isdigit()]
    except (TypeError, ValueError):
        return None
    if not categories:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            EXTENDED_WARRANTY_QUERY,
            {
                "productId": pid,
                "categories": categories,
                "productPrice": float(price_value),
            },
        )
    data = payload.get("data", {}).get("extended_warranty")
    if not data:
        return None

    packs: list[dict[str, Any]] = []
    for pack in data.get("warranty_packs") or []:
        if not isinstance(pack, dict):
            continue
        value = _price_amount(pack.get("value"))
        packs.append(
            {
                "pack_id": pack.get("pack_id"),
                "pack_title": _strip_html(str(pack.get("pack_title") or "")),
                "pack_tooltip": _strip_html(str(pack.get("pack_tooltip") or "")),
                "value": int(value) if value else 0,
                "value_formatted": _format_price(value) if value else "",
            }
        )
    return {
        "warranty_url": data.get("warranty_url") or "",
        "warranty_packs": packs,
    }


async def fetch_instock_other_provinces(
    product_id: str | int,
    *,
    province_id: int | None = None,
) -> list[str]:
    """Tỉnh khác trong cùng vùng còn tồn — instock_provinces."""
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return []

    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    company_id = company_id_for_province(pid_province)

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            INSTOCK_PROVINCES_QUERY,
            {"productId": pid, "companyId": company_id},
        )
    rows = payload.get("data", {}).get("instock_provinces") or []
    names: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        prov_id = row.get("id")
        try:
            prov_int = int(prov_id)
        except (TypeError, ValueError):
            continue
        if prov_int == pid_province:
            continue
        name = PROVINCE_ID_TO_NAME.get(prov_int)
        if name:
            names.append(name)
    return names


async def enrich_payload_for_scenarios(
    payload: dict[str, Any],
    detail: dict[str, Any],
    *,
    user_question: str = "",
    province_id: int | None = None,
    api_trace_stats: dict[str, Any] | None = None,
) -> dict[str, bool]:
    """Bổ sung dữ liệu theo kịch bản CSV; trả về flags đã fetch."""
    from cps_bot.core.api_trace import api_trace_scope, trace_phase

    if api_trace_stats is not None:
        async with api_trace_scope(api_trace_stats):
            with trace_phase("enrich"):
                return await _enrich_payload_for_scenarios_inner(
                    payload,
                    detail,
                    user_question=user_question,
                    province_id=province_id,
                )
    return await _enrich_payload_for_scenarios_inner(
        payload,
        detail,
        user_question=user_question,
        province_id=province_id,
    )


async def _enrich_payload_for_scenarios_inner(
    payload: dict[str, Any],
    detail: dict[str, Any],
    *,
    user_question: str = "",
    province_id: int | None = None,
) -> dict[str, bool]:
    scenarios = classify_question_scenarios(user_question)
    payload["question_scenarios"] = scenarios
    fetched: dict[str, bool] = {}
    unavailable = is_unavailable_product_detail(detail)
    if unavailable:
        primary = payload.get("primary_product") or {}
        if isinstance(primary, dict):
            for key in (
                "member_prices",
                "promotions",
                "promotion_info",
                "member_promotion",
                "stock_quantity",
                "company_stock_quantity",
                "up_sell",
            ):
                primary.pop(key, None)
            payload["primary_product"] = primary
        payload.pop("shop_stock", None)
        payload.pop("online_stock", None)
    pid = (
        province_id
        if province_id is not None
        else resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    )

    if not unavailable and (scenarios.get("trade_in") or scenarios.get("price_promotion")):
        trade = await fetch_trade_promo_for_product(detail, province_id=pid)
        if trade:
            payload["trade_promo"] = trade
            fetched["trade_promo"] = True

    if scenarios.get("warranty"):
        warranty = await fetch_extended_warranty_for_product(detail)
        if warranty:
            payload["extended_warranty"] = warranty
            fetched["extended_warranty"] = True

    if not unavailable and scenarios.get("shop_stock") and detail.get("product_id"):
        other = await fetch_instock_other_provinces(
            detail["product_id"],
            province_id=pid,
        )
        if other:
            payload["instock_other_provinces"] = other
            fetched["instock_other_provinces"] = True

    if scenarios.get("installment"):
        from cps_bot.cps.cps_installment import fetch_installment_context

        installment_ctx = await fetch_installment_context(
            detail,
            user_question=user_question,
        )
        if installment_ctx:
            payload["installment"] = installment_ctx
            fetched["installment"] = True

    if (
        scenarios.get("color_variants")
        or is_color_variant_list_query(user_question)
    ) and detail.get("product_id"):
        color_ctx = await fetch_color_sibling_variants(detail, province_id=pid)
        if color_ctx:
            payload["color_sibling_variants"] = color_ctx
            fetched["color_sibling_variants"] = True

    if scenarios.get("store_locator"):
        from cps_bot.cps.cps_store import fetch_store_locator_context

        store_ctx = await fetch_store_locator_context(
            user_question,
            province_id=pid,
        )
        if store_ctx:
            payload["store_locator"] = store_ctx
            fetched["store_locator"] = True

    from cps_bot.cps.cps_enrich import enrich_extended_scenarios

    extended_scenarios = dict(scenarios)
    if unavailable:
        extended_scenarios["trade_in"] = False
        extended_scenarios["trade_in_device"] = False
        extended_scenarios["combo"] = False
        extended_scenarios["shop_stock"] = False
    extended = await enrich_extended_scenarios(
        payload,
        detail,
        extended_scenarios,
        province_id=pid,
    )
    fetched.update(extended)

    if (
        not _is_browse_list_detail(detail)
        and not payload.get("compare_mode")
    ):
        if unavailable:
            similar = await fetch_similar_products(detail, province_id=pid, limit=10)
            if similar:
                payload["similar_products"] = similar
                fetched["similar_products"] = True
        else:
            rec_pid = _recommendation_product_id(detail)
            if rec_pid:
                recommended = await fetch_recommended_products(
                    rec_pid,
                    province_id=pid,
                )
                if recommended:
                    payload["recommended_products"] = recommended
                    fetched["recommended_products"] = True

    if scenarios.get("warranty") and not detail.get("warranty_information"):
        if not payload.get("product_faqs"):
            payload["policy_note"] = (
                "Chính sách đổi trả chi tiết (7 ngày, 1 đổi 1) nằm trên website CellphoneS; "
                "bot chỉ có warranty_information và gói BH mở rộng từ API sản phẩm."
            )

    return fetched


def extract_location_hint(text: str) -> str:
    """Trích gợi ý địa điểm từ câu hỏi (vd: gần 288 3 tháng 2, quận 10, Q.9)."""
    value = (text or "").strip()
    if re.search(r"gần nhất|gan nhat", value, re.IGNORECASE):
        return ""
    near = _NEAR_STREET_RE.search(value)
    if near:
        return near.group(1).strip().rstrip("?").strip()
    district = _DISTRICT_HINT_RE.search(value)
    if district:
        return f"{district.group(1)} {district.group(2)}".strip()
    district_loose = _DISTRICT_HINT_LOOSE_RE.search(value)
    if district_loose:
        return f"{district_loose.group(1)} {district_loose.group(2)}".strip()
    abbrev = _DISTRICT_ABBREV_RE.search(value)
    if abbrev:
        num = abbrev.group(1) or abbrev.group(2)
        return f"quận {num}"
    return ""


def _location_tokens(hint: str) -> list[str]:
    if not hint:
        return []
    normalized = re.sub(
        r"[^\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]",
        " ",
        hint.lower(),
    )
    return [
        t
        for t in normalized.split()
        if len(t) >= 2 or (t.isdigit() and len(t) >= 1)
    ]


def _extract_district_number(hint: str) -> str | None:
    """Trích số quận/huyện từ hint: quận 9, Q.9, Q9 → '9'."""
    value = (hint or "").strip().lower()
    if not value:
        return None
    for pattern in (
        r"(?:quận|quan|huyện|huyen)\s*(\d{1,2})\b",
        r"\bq\.?\s*(\d{1,2})\b",
        r"\bq(\d{1,2})\b",
    ):
        match = re.search(pattern, value, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _shop_matches_district_number(haystack: str, district_num: str) -> bool:
    """Khớp quận số — địa chỉ CPS thường ghi Q.9, Q9 thay vì 'quận 9'."""
    compact = re.sub(r"[.,]", " ", haystack.lower())
    compact = re.sub(r"\s+", " ", compact).strip()
    patterns = (
        f"q {district_num}",
        f"q.{district_num}",
        f"q{district_num}",
        f"quận {district_num}",
        f"quan {district_num}",
        f"huyện {district_num}",
        f"huyen {district_num}",
    )
    return any(p in compact or p in haystack.lower() for p in patterns)


def _haystack_for_shop(
    shop: dict[str, Any],
    district: dict[str, Any] | None = None,
) -> str:
    parts = [
        str(shop.get("address") or ""),
        str(shop.get("near") or ""),
        str(shop.get("district_name") or ""),
    ]
    if district:
        parts.extend(
            [
                str(district.get("district_name") or ""),
                str(district.get("province_name") or ""),
            ]
        )
    return " ".join(parts).lower()


def _district_id_matches(district: dict[str, Any], district_num: str) -> bool:
    raw = district.get("district_id")
    if raw is None:
        return False
    try:
        return str(int(raw)) == str(int(district_num))
    except (TypeError, ValueError):
        return str(raw).strip() == str(district_num).strip()


def _district_matches_location(district: dict[str, Any], hint: str) -> bool:
    """Khớp theo district_id / district_name từ shops_stock — không chỉ text địa chỉ shop."""
    if not hint:
        return True
    district_num = _extract_district_number(hint)
    if district_num:
        if _district_id_matches(district, district_num):
            return True
        d_name = str(district.get("district_name") or "").lower()
        if d_name and _shop_matches_district_number(d_name, district_num):
            return True
        return False
    d_name = str(district.get("district_name") or "").lower()
    tokens = _location_tokens(hint)
    if tokens and d_name:
        return all(token in d_name for token in tokens)
    return False


def _shop_matches_location(
    shop: dict[str, Any],
    hint: str,
    *,
    district: dict[str, Any] | None = None,
) -> bool:
    if not hint:
        return True
    haystack = _haystack_for_shop(shop, district)

    district_num = _extract_district_number(hint)
    if district_num:
        if _shop_matches_district_number(haystack, district_num):
            return True
        # Hint có số quận — đã xử lý ở cấp district; shop lẻ không khớp thì loại.
        if re.search(r"(?:quận|quan|q\.?)\s*\d", hint, re.IGNORECASE):
            return False

    tokens = _location_tokens(hint)
    if not tokens:
        return True
    return all(token in haystack for token in tokens)


def _flatten_shops(
    districts: list[dict[str, Any]],
    *,
    location_hint: str = "",
    exclude_online: bool = True,
) -> list[dict[str, Any]]:
    shops: list[dict[str, Any]] = []
    for district in districts or []:
        district_name = district.get("district_name") or ""
        district_matches = _district_matches_location(district, location_hint)
        for shop in district.get("shops") or []:
            if not isinstance(shop, dict):
                continue
            ext_id = shop.get("external_id")
            try:
                if exclude_online and int(ext_id) in ONLINE_SHOP_EXTERNAL_IDS:
                    continue
            except (TypeError, ValueError):
                pass
            if location_hint and not district_matches:
                if not _shop_matches_location(shop, location_hint, district=district):
                    continue
            shops.append(
                {
                    "district_id": district.get("district_id"),
                    "district_name": district_name,
                    "province_name": district.get("province_name") or "",
                    "address": shop.get("address") or "",
                    "phone": shop.get("phone") or "",
                    "near": shop.get("near") or "",
                    "google_link": shop.get("google_link") or "",
                    "external_id": ext_id,
                }
            )
    return shops


async def get_shops_stock(
    product_id: str | int,
    province_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Lấy danh sách cửa hàng còn tồn theo tỉnh — API shops_stock (graphql-dashboard).
    Tham chiếu: cps-nuxt-standard/store/province.js → getShopStockGraphql.
    """
    pid = str(product_id).strip()
    if not pid:
        return []

    try:
        product_id_int = int(pid)
    except ValueError:
        return []

    variables = {
        "productId": product_id_int,
        "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            SHOPS_STOCK_QUERY,
            variables,
        )
    return payload.get("data", {}).get("shops_stock") or []


async def fetch_shop_stock_context(
    product_id: str | int,
    *,
    user_question: str = "",
    province_id: int | None = None,
    product_name: str = "",
    url_path: str = "",
    online_stock_status: str = "",
    online_stock_quantity: int | None = None,
    online_stock_availability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Gói dữ liệu tồn cửa hàng cho Gemini / trả lời trực tiếp.
    Kịch bản: cửa hàng còn hàng, shop lân cận (lọc theo địa chỉ trong câu hỏi).
    """
    location_hint = extract_location_hint(user_question)
    pid = province_id if province_id is not None else CPS_PROVINCE_ID
    province_name = PROVINCE_ID_TO_NAME.get(pid, "")

    districts = await get_shops_stock(product_id, province_id)
    source = "graphql"
    if not districts and url_path:
        districts = await fetch_shop_stock_from_product_page(
            url_path, province_id=province_id
        )
        source = "product_page"

    shops = _flatten_shops(districts, location_hint=location_hint)
    if districts and not province_name:
        province_name = districts[0].get("province_name") or province_name

    total_shops = len(_flatten_shops(districts))
    stock_avail = online_stock_availability or {}
    online_available = bool(stock_avail.get("is_buyable_online"))
    if not online_available:
        online_available = bool(
            online_stock_quantity and online_stock_quantity > 0
        ) or bool(
            re.search(
                r"còn hàng|con hang|đặt trước|dat truoc|drop shipping",
                online_stock_status or "",
                re.I,
            )
        )

    return {
        "scenario": "shop_stock",
        "source": source,
        "product_name": product_name,
        "province_id": pid,
        "province_name": province_name,
        "location_hint": location_hint,
        "online_stock_status": online_stock_status,
        "online_stock_quantity": online_stock_quantity,
        "online_stock_availability": stock_avail,
        "online_stock_available": online_available,
        "total_shops_in_province": total_shops,
        "matched_shops_count": len(shops),
        "shops": shops[:20],
        "has_stock_in_province": total_shops > 0 or online_available,
    }


async def attach_shop_stock_to_payload(
    payload: dict[str, Any],
    detail: dict[str, Any],
    *,
    user_question: str = "",
    province_id: int | None = None,
) -> dict[str, Any] | None:
    """Lấy tồn cửa hàng + tồn online và gắn vào payload."""
    product_id = detail.get("product_id")
    if not product_id:
        return None

    stock_avail = detail.get("stock_availability") or {}
    stock_status = str(
        detail.get("stock_status") or stock_avail.get("display_status") or ""
    )
    stock_qty = detail.get("stock_quantity")
    qty: int | None
    try:
        qty = int(stock_qty) if stock_qty is not None else None
    except (TypeError, ValueError):
        qty = None

    payload["online_stock"] = {
        "stock_status": stock_status,
        "stock_quantity": qty,
        "stock_available_id": detail.get("stock_available_id"),
        "stock_availability": stock_avail,
    }

    pid = (
        province_id
        if province_id is not None
        else resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    )
    shop_ctx = await fetch_shop_stock_context(
        product_id,
        user_question=user_question,
        province_id=pid,
        product_name=detail.get("name") or "",
        url_path=str(detail.get("url_path") or ""),
        online_stock_status=stock_status,
        online_stock_quantity=qty,
        online_stock_availability=stock_avail,
    )
    if (
        shop_ctx.get("total_shops_in_province")
        or shop_ctx.get("matched_shops_count")
        or shop_ctx.get("online_stock_available")
    ):
        payload["shop_stock"] = shop_ctx
    return shop_ctx


def format_shop_stock_summary(ctx: dict[str, Any]) -> str:
    """Tóm tắt tồn cửa hàng — dùng khi không cần Gemini hoặc làm fallback."""
    name = ctx.get("product_name") or "Sản phẩm"
    province = ctx.get("province_name") or f"tỉnh ID {ctx.get('province_id')}"
    hint = ctx.get("location_hint") or ""
    shops: list[dict[str, Any]] = ctx.get("shops") or []
    total = int(ctx.get("total_shops_in_province") or 0)

    if total == 0:
        return (
            f"📦 {name}\n"
            f"Hiện chưa có cửa hàng nào trong {province} báo còn tồn "
            f"(theo dữ liệu CellphoneS)."
        )

    header = f"📦 {name}\n"
    if hint:
        header += f"🔍 Khu vực: {hint}\n"
    header += f"📍 {province}: {total} cửa hàng có hàng"
    if hint:
        header += f" — khớp vùng: {len(shops)}"
    header += "\n\n"

    if hint and not shops:
        return (
            header
            + "Không tìm thấy cửa hàng khớp địa chỉ trong câu hỏi.\n"
            "Thử hỏi rộng hơn (vd: bỏ địa chỉ cụ thể) hoặc đổi tỉnh/thành."
        )

    lines = [header]
    for idx, shop in enumerate(shops[:12], start=1):
        addr = shop.get("address") or "—"
        district = shop.get("district_name") or ""
        phone = shop.get("phone") or ""
        line = f"{idx}. {addr}"
        if district:
            line += f" ({district})"
        if phone:
            line += f"\n   ☎ {phone}"
        map_link = shop.get("google_link") or ""
        if map_link:
            line += f"\n   🗺 {map_link}"
        lines.append(line)

    remaining = len(shops) - 12
    if remaining > 0:
        lines.append(f"\n… và {remaining} cửa hàng khác.")
    return "\n".join(lines)
