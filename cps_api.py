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
from scraper import BASE_URL, _format_price, _full_url, product_url_from_record, search_products

logger = logging.getLogger(__name__)

CELLPHONES_URL_RE = re.compile(
    r"https?://(?:www\.)?cellphones\.com\.vn/[^\s<>\"']+\.html",
    re.IGNORECASE,
)

# Kho online / depot — loại khỏi danh sách cửa hàng trưng bày (theo cps-nuxt-standard)
ONLINE_SHOP_EXTERNAL_IDS = frozenset({1280, 1281, 103, 156})

PROVINCE_ID_TO_NAME: dict[int, str] = {
    30: "Hồ Chí Minh",
    24: "Hà Nội",
    27: "Đà Nẵng",
}

# company_id theo tỉnh — tham chiếu cps-nuxt-standard/store/province.js, ChangeProvince.vue
PROVINCE_COMPANY_ID: dict[int, int] = {
    30: 12869,  # Miền Nam
    24: 3759,   # Miền Bắc
    27: 3759,
}

PROVINCE_NAME_ALIASES: dict[str, int] = {
    "hồ chí minh": 30,
    "ho chi minh": 30,
    "hcm": 30,
    "tp hcm": 30,
    "tp.hcm": 30,
    "sài gòn": 30,
    "sai gon": 30,
    "hà nội": 24,
    "ha noi": 24,
    "hn": 24,
    "đà nẵng": 27,
    "da nang": 27,
}

# stock_available_id — cps-nuxt-standard/helper/function/constants/stock-available.js
STOCK_AVAILABLE_PRE_ORDER = 152
STOCK_AVAILABLE_IN_STOCK = 46
STOCK_AVAILABLE_OUT_OF_STOCK = 43

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
_INCOMING_STOCK_RE = re.compile(
    r"\b(hàng về|hang ve|khi nào về|khi nao ve|bao giờ về|bao gio ve|"
    r"pre[- ]?order|đặt trước|dat truoc)\b",
    re.IGNORECASE,
)
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
    r"(?=\s+(?:shop|có|co|còn|con|tìm|tim)\b|[?.!,]|\s|$)",
    re.IGNORECASE,
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
        company_stock_id: [46, 152, 4920]
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


def _format_stock_status(filterable: dict[str, Any]) -> str:
    product_state = _strip_html(str(filterable.get("product_state") or ""))
    stock = filterable.get("stock")
    stock_available_id = filterable.get("stock_available_id")

    parts: list[str] = []
    if product_state:
        parts.append(product_state)
    try:
        said = int(stock_available_id) if stock_available_id is not None else None
    except (TypeError, ValueError):
        said = None
    if said == STOCK_AVAILABLE_PRE_ORDER and not product_state:
        parts.append("Đặt trước / hàng về")
    elif said == STOCK_AVAILABLE_OUT_OF_STOCK and not product_state:
        parts.append("Tạm hết hàng")

    if stock is not None:
        try:
            stock_num = int(stock)
            if stock_num > 0:
                parts.append(f"Còn hàng ({stock_num})")
            elif not product_state and said != STOCK_AVAILABLE_PRE_ORDER:
                parts.append("Tạm hết hàng")
        except (TypeError, ValueError):
            pass
    elif stock_available_id is not None:
        try:
            if int(stock_available_id) in (
                STOCK_AVAILABLE_IN_STOCK,
                STOCK_AVAILABLE_PRE_ORDER,
                4920,
            ):
                parts.append("Còn hàng")
        except (TypeError, ValueError):
            pass

    return " — ".join(dict.fromkeys(parts)) if parts else "Không rõ"


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

    try:
        stock_available_id = int(filterable.get("stock_available_id") or 0)
    except (TypeError, ValueError):
        stock_available_id = None

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
        "stock_status": _format_stock_status(filterable),
        "stock_quantity": stock_qty,
        "stock_available_id": stock_available_id,
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
        except Exception as exc:
            logger.warning("CPS fetch thất bại (%s): %s", target_url, exc)
            return [], {}, stats
    else:
        # Layer 1: SerpAPI trước (có thể tắt bằng SERPAPI_ENABLED=0)
        serp_urls: list[str] = []
        use_serp = SERPAPI_ENABLED and bool(SERPAPI_API_KEY)
        if use_serp:
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

        if serp_urls:
            stats["resolve_source"] = "serpapi"
            for url in serp_urls:
                try:
                    stats["cps_url_info_calls"] += 1
                    stats["cps_product_detail_calls"] += 1
                    detail = await fetch_product_from_url(url, keywords=keywords)
                    if detail:
                        break
                except Exception as exc:
                    logger.warning("CPS fetch thất bại (%s): %s", url, exc)

        # Layer 2: fallback quick_search (Serp tắt / không key / hoặc SERPAPI_FALLBACK_TO_CPS_SEARCH=1)
        if not detail and (not use_serp or SERPAPI_FALLBACK_TO_CPS_SEARCH):
            stats["search_products_calls"] += 1
            search_results = await search_products(keywords)
            if search_results:
                stats["resolve_source"] = "search_results"
                best = _pick_best_search_result(search_results, keywords)
                pick_url = product_url_from_record(best or search_results[0])
                if pick_url:
                    try:
                        stats["cps_url_info_calls"] += 1
                        stats["cps_product_detail_calls"] += 1
                        detail = await fetch_product_from_url(pick_url, keywords=keywords)
                    except Exception as exc:
                        logger.warning("CPS fetch thất bại (%s): %s", pick_url, exc)

    if not detail:
        return search_results, {}, stats

    if not search_results:
        search_results = [
            {
                "name": detail.get("name", ""),
                "price": detail.get("price", ""),
                "url_path": detail.get("url_path", ""),
                "url": detail.get("url", ""),
                "thumbnail": detail.get("thumbnail", ""),
                "product_id": detail.get("product_id", ""),
            }
        ]

    return search_results, detail, stats


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
    }


def company_id_for_province(province_id: int) -> int:
    return PROVINCE_COMPANY_ID.get(province_id, PROVINCE_COMPANY_ID.get(CPS_PROVINCE_ID, 12869))


def resolve_province_from_text(text: str) -> int | None:
    """Trích tỉnh/thành từ câu hỏi (vd: Hà Nội, HCM)."""
    lower = (text or "").lower()
    for alias, pid in sorted(
        PROVINCE_NAME_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if alias in lower:
            return pid
    return None


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
) -> dict[str, bool]:
    """Bổ sung dữ liệu theo kịch bản CSV; trả về flags đã fetch."""
    scenarios = classify_question_scenarios(user_question)
    payload["question_scenarios"] = scenarios
    fetched: dict[str, bool] = {}

    if scenarios.get("trade_in") or scenarios.get("price_promotion"):
        trade = await fetch_trade_promo_for_product(detail)
        if trade:
            payload["trade_promo"] = trade
            fetched["trade_promo"] = True

    if scenarios.get("warranty"):
        warranty = await fetch_extended_warranty_for_product(detail)
        if warranty:
            payload["extended_warranty"] = warranty
            fetched["extended_warranty"] = True

    if scenarios.get("shop_stock") and detail.get("product_id"):
        other = await fetch_instock_other_provinces(detail["product_id"])
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

    if scenarios.get("warranty") and not detail.get("warranty_information"):
        payload["policy_note"] = (
            "Chính sách đổi trả chi tiết (7 ngày, 1 đổi 1) nằm trên website CellphoneS; "
            "bot chỉ có warranty_information và gói BH mở rộng từ API sản phẩm."
        )

    return fetched


def extract_location_hint(text: str) -> str:
    """Trích gợi ý địa điểm từ câu hỏi (vd: gần 288 3 tháng 2, quận 10)."""
    value = (text or "").strip()
    if re.search(r"gần nhất|gan nhat", value, re.IGNORECASE):
        return ""
    near = _NEAR_STREET_RE.search(value)
    if near:
        return near.group(1).strip().rstrip("?").strip()
    district = _DISTRICT_HINT_RE.search(value)
    if district:
        return f"{district.group(1)} {district.group(2)}".strip()
    return ""


def _location_tokens(hint: str) -> list[str]:
    if not hint:
        return []
    normalized = re.sub(r"[^\wàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ\s]", " ", hint.lower())
    return [t for t in normalized.split() if len(t) >= 2]


def _shop_matches_location(shop: dict[str, Any], hint: str) -> bool:
    tokens = _location_tokens(hint)
    if not tokens:
        return True
    haystack = " ".join(
        [
            str(shop.get("address") or ""),
            str(shop.get("near") or ""),
        ]
    ).lower()
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
    online_available = bool(
        online_stock_quantity and online_stock_quantity > 0
    ) or bool(re.search(r"còn hàng|con hang", online_stock_status or "", re.I))

    return {
        "scenario": "shop_stock",
        "source": source,
        "product_name": product_name,
        "province_id": pid,
        "province_name": province_name,
        "location_hint": location_hint,
        "online_stock_status": online_stock_status,
        "online_stock_quantity": online_stock_quantity,
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
) -> dict[str, Any] | None:
    """Lấy tồn cửa hàng + tồn online và gắn vào payload."""
    product_id = detail.get("product_id")
    if not product_id:
        return None

    stock_status = str(detail.get("stock_status") or "")
    stock_qty = detail.get("stock_quantity")
    qty: int | None
    try:
        qty = int(stock_qty) if stock_qty is not None else None
    except (TypeError, ValueError):
        qty = None

    payload["online_stock"] = {
        "stock_status": stock_status,
        "stock_quantity": qty,
    }

    province_id = resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    shop_ctx = await fetch_shop_stock_context(
        product_id,
        user_question=user_question,
        province_id=province_id,
        product_name=detail.get("name") or "",
        url_path=str(detail.get("url_path") or ""),
        online_stock_status=stock_status,
        online_stock_quantity=qty,
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
