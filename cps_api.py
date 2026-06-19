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
    CPS_GRAPHQL_DASHBOARD_ENDPOINT,
    CPS_GRAPHQL_URL_ENDPOINT,
    CPS_GRAPHQL_V2_ENDPOINT,
    CPS_GRAPHQL_V2_PRODUCTION,
    CPS_PROVINCE_ID,
    SERPAPI_API_KEY,
    SERPAPI_ENABLED,
    SERPAPI_ENDPOINT,
    SERPAPI_FALLBACK_TO_CPS_SEARCH,
)
from budget_browse import (
    filter_results_by_budget,
    is_budget_browse_query,
    parse_budget_constraint,
    strip_budget_phrases_for_keywords,
)
from scraper import (
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

from cps_provinces import (
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
    r"home credit|homecredit|cttc|"
    r"kỳ hạn|ky han|"
    r"miễn lãi|mien lai|chuyển đổi trả góp|"
    r"thẻ tín dụng|the tin dung|techcombank|tcb|alepay|onepay|"
    r"vib|vnpay"
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
    r"\b(so sánh|so sanh|vs\.?|với|voi|khác biệt|khac biet|nên mua|nen mua)\b",
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
    r"tình trạng hàng|tinh trang hang|trạng thái hàng|trang thai hang|"
    r"có bán không|co ban khong|có hàng không|co hang khong|"
    r"out of stock|in stock|"
    r"đăng ký nhận tin|dang ky nhan tin|"
    r"đặt trước được|dat truoc duoc|mua được không|mua duoc khong"
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
    r"cửa hàng|cua hang|chi nhánh|chi nhanh|shop nào|shop nao|shop mình|shop minh|"
    r"ở đâu còn|o dau con|gần đây|gan day|lân cận|lan can|"
    r"cửa hàng gần|cua hang gan|shop gần|shop gan|"
    r"xem chi nhánh|co hang o|hàng ở đâu|hang o dau|"
    r"còn ở shop|còn shop|con shop|shop nào còn|shop nao con"
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
    r"(?=\s+(?:shop|có|co|còn|con|tìm|tim|không|khong)\b|[?.!,]|\s|$)",
    re.IGNORECASE,
)
# Q.9, Q9, q 9 — cách viết phổ biến trên địa chỉ shop CellphoneS
_DISTRICT_ABBREV_RE = re.compile(
    r"\b[qQ]\.?\s*(\d{1,2})\b",
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
        "product_id": str(
            general.get("product_id")
            or (url_info or {}).get("product_id")
            or ""
        ),
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
        "is_installment": filterable.get("is_installment"),
    }


async def _graphql(
    client: httpx.AsyncClient,
    endpoint: str,
    query: str,
    variables: dict[str, Any],
) -> dict[str, Any]:
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

        if path.startswith("dien-thoai-") or path.endswith(".html"):
            points += 5

        return points

    return max(results, key=score)


_VARIANT_STORAGE_RE = re.compile(
    r"\b(64|128|256|512|1024|1tb|2tb)\s*(?:gb|tb)?\b",
    re.IGNORECASE,
)
_VARIANT_COLOR_HINTS: tuple[tuple[str, ...], ...] = (
    ("titan", "titan tự nhiên", "titan tu nhien", "natural titanium"),
    ("titan đen", "titan den", "black titanium", "đen titan"),
    ("titan trắng", "titan trang", "white titanium", "trắng titan"),
    ("titan sa mạc", "titan sa mac", "desert titanium"),
    ("hồng", "hong", "pink"),
    ("xanh", "blue", "xanh dương"),
    ("xanh lá", "xanh la", "green"),
    ("tím", "tim", "purple", "titan tím"),
    ("vàng", "vang", "gold"),
    ("đen", "den", "black"),
    ("trắng", "trang", "white"),
    ("bạc", "bac", "silver"),
)


def _extract_variant_hints(keywords: str) -> list[str]:
    hints: list[str] = []
    lower = (keywords or "").lower()
    for match in _VARIANT_STORAGE_RE.finditer(lower):
        val = match.group(1).lower()
        if val in {"1tb", "1024"}:
            hints.append("1tb")
        elif val == "2tb":
            hints.append("2tb")
        else:
            hints.append(f"{val}gb")
    for aliases in _VARIANT_COLOR_HINTS:
        for alias in aliases:
            if alias in lower:
                hints.append(aliases[0])
                break
    return hints


def _variant_hint_score(name: str, hints: list[str]) -> int:
    if not hints:
        return 0
    text = name.lower()
    score = 0
    for hint in hints:
        if hint in text or hint.replace(" ", "") in text.replace(" ", ""):
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


def _build_products_by_ids_query(product_ids: list[int]) -> str:
    ids_literal = ", ".join(str(i) for i in product_ids)
    return f"""
query GetProductsByIds($provinceId: Int!) {{
  products(
    filter: {{
      static: {{
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


async def resolve_product_variant(
    keywords: str,
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> dict[str, Any]:
    """Chọn biến thể (màu/dung lượng) khớp từ khóa — tham chiếu up_sell / sibling SKUs."""
    hints = _extract_variant_hints(keywords)
    if not hints:
        return detail
    if _variant_hint_score(detail.get("name") or "", hints) >= len(hints) * 10:
        return detail

    candidate_ids = _collect_up_sell_ids(detail)
    if len(candidate_ids) <= 1:
        return detail

    products = await get_products_by_ids(candidate_ids, province_id=province_id)
    if not products:
        return detail

    best_item: dict[str, Any] | None = None
    best_score = _variant_hint_score(detail.get("name") or "", hints)
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID

    for item in products:
        general = item.get("general") or {}
        name = str(general.get("name") or "")
        score = _variant_hint_score(name, hints)
        if score > best_score:
            best_score = score
            best_item = item

    if not best_item:
        return detail

    product_id = (best_item.get("general") or {}).get("product_id")
    if not product_id:
        return detail

    product = await get_product_by_id(product_id, province_id=pid_province)
    if not product:
        return detail

    url_path = str((best_item.get("general") or {}).get("url_path") or "")
    resolved = normalize_product_detail(
        product,
        url=_full_url(url_path) if url_path else detail.get("url") or "",
    )
    resolved["variant_resolved_from"] = detail.get("product_id")
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


async def fetch_product_for_query(
    keywords: str,
    *,
    user_message: str = "",
    fallback_url: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """
    Tìm sản phẩm theo link trong tin nhắn, URL session cũ, hoặc quick_search.
    Chi tiết lấy qua CPS GraphQL (không scrape HTML).
    """
    target_url = ""
    stats: dict[str, Any] = {
        "serpapi_calls": 0,
        "search_products_calls": 0,
        "cps_url_info_calls": 0,
        "cps_product_detail_calls": 0,
        "resolve_source": "",
    }

    for url in extract_cellphones_urls(user_message):
        target_url = url
        stats["resolve_source"] = "user_url"
        break

    if not target_url and fallback_url:
        target_url = fallback_url
        stats["resolve_source"] = "session_fallback_url"

    search_results: list[dict[str, Any]] = []
    detail: dict[str, Any] = {}

    # Nếu đã có URL (user gửi link hoặc fallback session) thì resolve thẳng.
    if target_url:
        try:
            stats["cps_url_info_calls"] += 1
            stats["cps_product_detail_calls"] += 1
            detail = await fetch_product_from_url(target_url, keywords=keywords)
            if detail and keywords:
                province_id = resolve_province_from_text(user_message)
                detail = await resolve_product_variant(
                    keywords,
                    detail,
                    province_id=province_id,
                )
        except Exception as exc:
            logger.warning("CPS fetch thất bại (%s): %s", target_url, exc)
            return [], {}, stats
    else:
        province_id = resolve_province_from_text(user_message) or CPS_PROVINCE_ID
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
            budget_hit = await _fetch_products_by_budget_browse(
                keywords,
                user_message,
                province_id=province_id,
            )
            if budget_hit:
                search_results, detail = budget_hit
                stats["resolve_source"] = "budget_browse"
                stats["budget_label"] = detail.get("budget_label") or ""

        # Layer 1: CPS search (advanced_search → quick_search fallback)
        if not detail and keywords:
            stats["search_products_calls"] += 1
            search_results = await search_products(
                keywords,
                province_id=province_id,
            )
            if search_results:
                stats["resolve_source"] = "search_results"
                best = _pick_best_search_result(search_results, keywords)
                pick_url = product_url_from_record(best or search_results[0])
                if pick_url:
                    try:
                        stats["cps_url_info_calls"] += 1
                        stats["cps_product_detail_calls"] += 1
                        detail = await fetch_product_from_url(pick_url, keywords=keywords)
                        if detail and keywords:
                            detail = await resolve_product_variant(
                                keywords,
                                detail,
                                province_id=province_id,
                            )
                    except Exception as exc:
                        logger.warning("CPS fetch thất bại (%s): %s", pick_url, exc)
                if len(search_results) >= 2 and search_results_need_advanced(
                    search_results[:2], keywords
                ):
                    stats["ambiguous_search"] = True

        # Layer 2: SerpAPI (chỉ khi CPS search không có kết quả)
        serp_urls: list[str] = []
        use_serp = SERPAPI_ENABLED and bool(SERPAPI_API_KEY)
        if not detail and use_serp:
            stats["serpapi_calls"] += 1
            try:
                query = f"site:cellphones.com.vn {keywords}".strip()
                params = {
                    "engine": "google",
                    "q": query,
                    "api_key": SERPAPI_API_KEY,
                    "num": 10,
                }
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

_SHOP_STOCK_PRODUCT_AFTER_CON_RE = re.compile(
    r"(?:còn|co)(?:\s+hàng|\s+hang)?\s+(.+?)\s*(?:"
    r"(?:không|khong|ko|k)\??|"
    r"(?:ở|o)\s+(?:shop|cửa hàng|cua hang|quận|quan)"
    r")(?:\s|$|\?)",
    re.I,
)


def needs_shop_stock_keyword_strip(text: str) -> bool:
    """Câu hỏi tồn cửa hàng / shop theo khu vực — cần bóc tên SP trước khi search."""
    if is_shop_stock_question(text):
        return True
    lower = (text or "").lower()
    has_shop = bool(re.search(r"\b(?:shop|cửa hàng|cua hang|chi nhánh|chi nhanh)\b", lower))
    has_stock_ask = bool(re.search(r"\b(?:còn|co|không|khong)\b", lower))
    has_district = bool(_DISTRICT_HINT_RE.search(text or "") or _DISTRICT_ABBREV_RE.search(text or ""))
    return (has_shop and has_stock_ask) or (has_district and has_stock_ask and has_shop)


def strip_shop_stock_phrases_for_keywords(text: str) -> str:
    """Bóc cụm shop/khu vực/tồn — chỉ giữ tên sản phẩm cho API search."""
    s = (text or "").strip().rstrip("?").strip()
    if not s:
        return ""

    match = _SHOP_STOCK_PRODUCT_AFTER_CON_RE.search(s)
    if match:
        product = match.group(1).strip()
        product = re.sub(r"^(?:hàng|hang)\s+", "", product, flags=re.I)
        if product:
            return product

    for pattern in _SHOP_STOCK_KEYWORD_STRIP_RES:
        s = pattern.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_shop_stock_question(text: str) -> bool:
    """Câu hỏi về tồn tại cửa hàng/chi nhánh (kịch bản kiểm tra tồn kho)."""
    return bool(_SHOP_STOCK_QUESTION_RE.search(text or ""))


def classify_question_scenarios(text: str) -> dict[str, bool]:
    """Phân loại kịch bản CSV — dùng để enrich payload và prompt Gemini."""
    value = text or ""
    return {
        "price_promotion": bool(_PRICE_QUESTION_RE.search(value)),
        "shop_stock": is_shop_stock_question(value),
        "trade_in": bool(_TRADE_IN_QUESTION_RE.search(value)),
        "installment": bool(_INSTALLMENT_QUESTION_RE.search(value)),
        "warranty": bool(_WARRANTY_QUESTION_RE.search(value)),
        "compare": bool(_COMPARE_QUESTION_RE.search(value)),
        "specs": bool(_SPECS_QUESTION_RE.search(value)),
        "advice": bool(_ADVICE_QUESTION_RE.search(value)),
        "incoming_stock": bool(_INCOMING_STOCK_RE.search(value)),
        "stock_status": bool(_STOCK_STATUS_QUESTION_RE.search(value)),
        "stock_browse": is_stock_status_browse_query(value),
        "budget_browse": is_budget_browse_query(value),
        "reviews": bool(_REVIEWS_QUESTION_RE.search(value)),
        "faq_policy": bool(_FAQ_POLICY_RE.search(value)),
        "flash_sale": bool(_FLASH_SALE_RE.search(value)),
        "trade_in_device": bool(_TRADE_DEVICE_RE.search(value)),
        "store_locator": bool(_STORE_LOCATOR_RE.search(value)),
        "combo": bool(_COMBO_QUESTION_RE.search(value)),
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
) -> dict[str, bool]:
    """Bổ sung dữ liệu theo kịch bản CSV; trả về flags đã fetch."""
    scenarios = classify_question_scenarios(user_question)
    payload["question_scenarios"] = scenarios
    fetched: dict[str, bool] = {}
    pid = (
        province_id
        if province_id is not None
        else resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    )

    if scenarios.get("trade_in") or scenarios.get("price_promotion"):
        trade = await fetch_trade_promo_for_product(detail, province_id=pid)
        if trade:
            payload["trade_promo"] = trade
            fetched["trade_promo"] = True

    if scenarios.get("warranty"):
        warranty = await fetch_extended_warranty_for_product(detail)
        if warranty:
            payload["extended_warranty"] = warranty
            fetched["extended_warranty"] = True

    if scenarios.get("shop_stock") and detail.get("product_id"):
        other = await fetch_instock_other_provinces(
            detail["product_id"],
            province_id=pid,
        )
        if other:
            payload["instock_other_provinces"] = other
            fetched["instock_other_provinces"] = True

    if scenarios.get("installment"):
        from cps_installment import fetch_installment_context

        installment_ctx = await fetch_installment_context(
            detail,
            user_question=user_question,
        )
        if installment_ctx:
            payload["installment"] = installment_ctx
            fetched["installment"] = True

    if scenarios.get("store_locator"):
        from cps_store import fetch_store_locator_context

        store_ctx = await fetch_store_locator_context(
            user_question,
            province_id=pid,
        )
        if store_ctx:
            payload["store_locator"] = store_ctx
            fetched["store_locator"] = True

    from cps_enrich import enrich_extended_scenarios

    extended = await enrich_extended_scenarios(
        payload,
        detail,
        scenarios,
        province_id=pid,
    )
    fetched.update(extended)

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
    abbrev = _DISTRICT_ABBREV_RE.search(value)
    if abbrev:
        return f"quận {abbrev.group(1)}"
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


def _haystack_for_shop(shop: dict[str, Any]) -> str:
    return " ".join(
        [
            str(shop.get("address") or ""),
            str(shop.get("near") or ""),
            str(shop.get("district_name") or ""),
        ]
    ).lower()


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


def _shop_matches_location(shop: dict[str, Any], hint: str) -> bool:
    if not hint:
        return True
    haystack = _haystack_for_shop(shop)

    district_num = _extract_district_number(hint)
    if district_num:
        if _shop_matches_district_number(haystack, district_num):
            return True
        # Hint có số quận nhưng shop không khớp → loại (tránh nhầm quận khác)
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
        for shop in district.get("shops") or []:
            if not isinstance(shop, dict):
                continue
            ext_id = shop.get("external_id")
            try:
                if exclude_online and int(ext_id) in ONLINE_SHOP_EXTERNAL_IDS:
                    continue
            except (TypeError, ValueError):
                pass
            if not _shop_matches_location(shop, location_hint):
                continue
            shops.append(
                {
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            SHOPS_STOCK_QUERY,
            {
                "productId": product_id_int,
                "provinceId": province_id if province_id is not None else CPS_PROVINCE_ID,
            },
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
