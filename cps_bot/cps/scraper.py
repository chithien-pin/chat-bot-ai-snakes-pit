"""
Module crawl / scrape dữ liệu sản phẩm từ cellphones.com.vn.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote, quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from config import CPS_GRAPHQL_SEARCH_ENDPOINT, CPS_PROVINCE_ID, CPS_WEB_BASE_URL

logger = logging.getLogger(__name__)

BASE_URL = CPS_WEB_BASE_URL
CDN_BASE = "https://cdn2.cellphones.com.vn"
SEARCH_GRAPHQL_URL = CPS_GRAPHQL_SEARCH_ENDPOINT
CATALOG_SEARCH_URL = f"{BASE_URL}/catalogsearch/result/"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

QUICK_SEARCH_QUERY = """
query quick_search($terms: String!, $province: Int!) {
  quick_search(user_query: { terms: $terms, province: $province }) {
    products {
      product_id
      name
      url_path
      price
      special_price
      thumbnail
      display_price
      stock_available_id
    }
  }
}
"""

ADVANCED_SEARCH_QUERY = """
query advanced_search($terms: String!, $province: Int!, $page: Int!, $categoryId: Int) {
  advanced_search(
    user_query: { terms: $terms, province: $province, category_id: $categoryId }
    page: $page
  ) {
    products {
      product_id
      name
      url_path
      price
      special_price
      display_price
      display_root_price
      thumbnail
      stock_available_id
      flash_sale_types
      promotion_info
      promotion_information
      score
      category_objects {
        category_id
        name
        uri
      }
    }
    related_categories {
      category_id
      name
      uri
      path
    }
    meta {
      total
      page
    }
  }
}
"""


def _format_price(amount: float | int | None) -> str:
    """Định dạng giá VNĐ."""
    if amount is None:
        return "Liên hệ"
    value = int(amount)
    return f"{value:,}".replace(",", ".") + "₫"


def _full_url(path: str) -> str:
    if path.startswith("http"):
        return path
    return urljoin(BASE_URL + "/", path.lstrip("/"))


_CATEGORY_BROWSE_PATH_RE = re.compile(
    r"^(?:[\w-]+/)*[\w-]+\.html(?:\?[\w=&%.,+-]+)?$",
    re.IGNORECASE,
)


def is_category_browse_path(text: str) -> bool:
    """True khi chuỗi là path trang danh mục CPS (vd. laptop.html?price=0-20000000)."""
    value = (text or "").strip()
    if not value:
        return False
    if value.startswith("http"):
        parsed = urlparse(value)
        path = (parsed.path or "").lstrip("/")
        query = parsed.query or ""
        value = f"{path}?{query}" if query else path
    return bool(_CATEGORY_BROWSE_PATH_RE.match(value))


def category_browse_url(path: str) -> str:
    """Chuẩn hóa path danh mục → URL đầy đủ trên cellphones.com.vn."""
    value = (path or "").strip()
    if not value:
        return ""
    if value.startswith("http"):
        return value
    return _full_url(value)


def product_url_from_record(record: dict[str, Any] | None) -> str:
    """URL sản phẩm — ưu tiên url_path, rồi url, rồi url_key từ GraphQL."""
    if not record:
        return ""
    url_path = str(record.get("url_path") or "").strip()
    if url_path:
        return _full_url(url_path)
    url = str(record.get("url") or "").strip()
    if url:
        return _full_url(url) if not url.startswith("http") else url
    url_key = str(record.get("url_key") or "").strip()
    if url_key:
        path = url_key if url_key.endswith(".html") else f"{url_key}.html"
        return _full_url(path)
    return ""


def graphql_product_url(general: dict[str, Any] | None) -> str:
    """URL từ block general của GraphQL products/quick_search."""
    if not general:
        return ""
    return product_url_from_record(
        {
            "url_path": general.get("url_path"),
            "url_key": general.get("url_key"),
        }
    )


def normalize_search_result(record: dict[str, Any]) -> dict[str, Any]:
    """Đảm bảo mỗi kết quả có url đầy đủ cho bot/Gemini."""
    out = dict(record)
    url = product_url_from_record(out)
    if url:
        out["url"] = url
    if not out.get("url_path") and url:
        try:
            out["url_path"] = url.split("cellphones.com.vn/", 1)[-1].lstrip("/")
        except (IndexError, AttributeError):
            pass
    return out


def normalize_search_results(
    search_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [normalize_search_result(item) for item in search_results if isinstance(item, dict)]


def format_product_links_appendix(
    search_results: list[dict[str, Any]],
    *,
    max_items: int = 8,
) -> str:
    """Khối link SP đính kèm cuối tin nhắn khi trả nhiều sản phẩm."""
    lines: list[str] = []
    for idx, item in enumerate(normalize_search_results(search_results)[:max_items], start=1):
        name = (item.get("name") or "Sản phẩm").strip()
        url = product_url_from_record(item)
        if not url:
            continue
        price = (item.get("price") or "").strip()
        label = f"{idx}. {name}"
        if price:
            label = f"{label} — {price}"
        lines.append(f"{label}\n{url}")
    if not lines:
        return ""
    return "\n\n🔗 Link sản phẩm:\n" + "\n".join(lines)


def is_browse_list_mode(detail: dict[str, Any] | None) -> bool:
    """True khi trả danh sách SP (category filter / budget / stock browse)."""
    if not detail:
        return False
    return bool(
        detail.get("category_filter_list_mode")
        or detail.get("budget_browse_list_mode")
        or detail.get("stock_browse_list_mode")
    )


def should_attach_product_links_appendix(
    detail: dict[str, Any] | None,
    *,
    scenarios: dict[str, bool] | None = None,
    compare_mode: bool = False,
    ambiguous_search: bool = False,
    fast_browse_reply: bool = False,
) -> bool:
    """
    Chỉ đính block link khi bot cố ý trả nhiều SP (browse / so sánh).
    Không gắn khi đã chốt 1 SP — search_results có thể còn nhiễu từ API.
    """
    if fast_browse_reply or ambiguous_search:
        return False
    if compare_mode:
        return True
    if is_browse_list_mode(detail):
        return True
    scenarios = scenarios or {}
    return bool(
        scenarios.get("stock_browse")
        or scenarios.get("budget_browse")
        or scenarios.get("category_filter_browse")
    )


def _browse_list_primary(detail: dict[str, Any]) -> dict[str, Any]:
    """Metadata danh sách — không phải 1 SP; tránh LLM nhầm thiếu dữ liệu."""
    keys = (
        "category_filter_list_mode",
        "category_filter_name",
        "category_filter_id",
        "category_filter_matched",
        "category_filter_url",
        "budget_browse_list_mode",
        "budget_label",
        "budget_category",
        "stock_browse_list_mode",
        "stock_filter_ids",
        "product_count",
        "name",
        "description",
        "url",
    )
    return {k: detail[k] for k in keys if detail.get(k) not in (None, "", [], {})}


def _thumbnail_url(path: str | None) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if path.startswith("/"):
        return urljoin(BASE_URL, path)
    return f"{CDN_BASE}/x/media/catalog/product{path}"


def build_catalog_search_url(query: str) -> str:
    """
    Link trang kết quả tìm kiếm đúng rule:
    https://cellphones.com.vn/catalogsearch/result?q=<query_encoded>
    """
    q = (query or "").strip()
    base = f"{BASE_URL}/catalogsearch/result"
    if not q:
        return base
    return f"{base}?q={quote(q, safe='')}"


def is_single_product_result(
    search_results: list[dict[str, Any]],
    detail: dict[str, Any] | None = None,
) -> bool:
    """True khi kết quả chỉ trỏ về một sản phẩm cụ thể."""
    if len(search_results) <= 1:
        return True

    product_ids = {
        str(item.get("product_id") or "").strip()
        for item in search_results
        if item.get("product_id")
    }
    if len(product_ids) == 1:
        return True

    urls = {
        str(item.get("url") or "").strip()
        for item in search_results
        if item.get("url")
    }
    url_paths = {
        str(item.get("url_path") or "").strip()
        for item in search_results
        if item.get("url_path")
    }
    if len(url_paths) == 1:
        return True
    if len(urls) == 1:
        return True

    detail_path = str((detail or {}).get("url_path") or "").strip()
    if detail_path and search_results:
        top_path = str(search_results[0].get("url_path") or "").strip()
        if detail_path == top_path:
            return True

    detail_url = product_url_from_record(detail)
    if detail_url and urls == {detail_url}:
        return True
    return False


def build_response_link_url(
    *,
    search_results: list[dict[str, Any]],
    detail: dict[str, Any],
    search_keywords: str,
) -> str:
    """
    Link đính kèm cuối tin nhắn:
    - 1 sản phẩm → url_path trang chi tiết SP
    - Browse danh mục + filter → URL category (không bọc catalogsearch)
    - Nhiều SP → danh mục (category_url) hoặc trang search theo từ khóa
    """
    keywords = (search_keywords or "").strip()
    category_url = str(detail.get("category_url") or "").strip()

    if detail.get("category_filter_list_mode"):
        filter_url = str(
            detail.get("category_filter_url") or detail.get("url") or keywords
        ).strip()
        if filter_url:
            return category_browse_url(filter_url)

    if detail.get("budget_browse_list_mode") and is_category_browse_path(keywords):
        return category_browse_url(keywords)

    if detail.get("stock_filter_ids"):
        primary_url = product_url_from_record(detail)
        if primary_url:
            return primary_url

    if is_single_product_result(search_results, detail):
        product_url = product_url_from_record(detail)
        if product_url:
            return product_url
        if search_results:
            first_url = product_url_from_record(search_results[0])
            if first_url:
                return first_url

    if is_category_browse_path(keywords):
        return category_browse_url(keywords)

    if category_url:
        return category_browse_url(category_url)
    return build_catalog_search_url(keywords)


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.text


def _parse_specs(soup: BeautifulSoup) -> dict[str, str]:
    """Trích thông số kỹ thuật từ bảng .technical-content."""
    specs: dict[str, str] = {}
    table = soup.select_one("table.technical-content")
    if not table:
        return specs
    for row in table.select("tr.technical-content-item"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        key = cells[0].get_text(strip=True)
        value = cells[1].get_text("\n", strip=True)
        if key and value:
            specs[key] = value
    return specs


def _parse_stock_status(soup: BeautifulSoup) -> str:
    """Lấy tình trạng hàng (còn / hết hàng)."""
    out_of_stock = soup.select_one(".title-out-stock strong")
    if out_of_stock:
        extra = soup.select_one(".title-out-stock span")
        suffix = f" {extra.get_text(strip=True)}" if extra else ""
        return out_of_stock.get_text(strip=True) + suffix

    buy_btn = soup.select_one(
        ".btn-buy, .button-buy, [class*='btn-buy'], .box-order__buy"
    )
    if buy_btn:
        text = buy_btn.get_text(strip=True)
        if text:
            return text

    page_text = soup.get_text(" ", strip=True).upper()
    if "TẠM HẾT HÀNG" in page_text:
        return "Tạm hết hàng"
    if "CÒN HÀNG" in page_text or "MUA NGAY" in page_text:
        return "Còn hàng"
    return "Không rõ"


def _parse_detail_html(html: str, url: str) -> dict[str, Any]:
    """Parse HTML trang chi tiết sản phẩm."""
    soup = BeautifulSoup(html, "lxml")

    name_el = soup.select_one(".box-product-name, h1")
    name = name_el.get_text(strip=True) if name_el else ""

    price_el = soup.select_one(".sale-price, .product__price--show")
    price = price_el.get_text(strip=True) if price_el else ""

    old_price_el = soup.select_one(".base-price, .product__price--through")
    old_price = old_price_el.get_text(strip=True) if old_price_el else ""

    meta_desc = soup.find("meta", attrs={"name": "description"})
    description = meta_desc.get("content", "").strip() if meta_desc else ""

    specs = _parse_specs(soup)
    stock_status = _parse_stock_status(soup)

    og_image = soup.find("meta", attrs={"property": "og:image"})
    thumbnail = og_image.get("content", "") if og_image else ""

    return {
        "name": name,
        "price": price,
        "old_price": old_price,
        "description": description,
        "specifications": specs,
        "stock_status": stock_status,
        "url": url,
        "thumbnail": thumbnail,
    }


def _parse_search_fallback_html(html: str, limit: int = 8) -> list[dict[str, Any]]:
    """
    Dự phòng: parse link sản phẩm từ trang catalogsearch (khi API lỗi).
    """
    soup = BeautifulSoup(html, "lxml")
    products: list[dict[str, Any]] = []
    seen: set[str] = set()

    for anchor in soup.select("a[href*='.html']"):
        href = anchor.get("href", "")
        if not href or "/mobile/" in href and href.count("/") < 3:
            continue
        if not re.search(r"cellphones\.com\.vn/[^/]+\.html$", href):
            continue
        if href in seen:
            continue
        name = anchor.get_text(strip=True)
        if len(name) < 5:
            continue
        seen.add(href)
        path = urlparse(href).path.lstrip("/") if href.startswith("http") else href.lstrip("/")
        products.append(
            {
                "name": name,
                "price": "",
                "url_path": path,
                "url": _full_url(path),
                "thumbnail": "",
            }
        )
        if len(products) >= limit:
            break
    return products


def _map_search_product_item(item: dict[str, Any]) -> dict[str, Any]:
    url_path = item.get("url_path") or ""
    url_key = item.get("url_key") or ""
    display = item.get("display_price") or item.get("special_price")
    if display is None:
        display = item.get("price")
    return normalize_search_result(
        {
            "name": item.get("name", ""),
            "price": _format_price(display),
            "url_path": url_path,
            "url_key": url_key,
            "thumbnail": _thumbnail_url(item.get("thumbnail")),
            "product_id": str(item.get("product_id") or ""),
            "stock_available_id": item.get("stock_available_id"),
            "flash_sale_types": item.get("flash_sale_types"),
            "promotion_info": item.get("promotion_info") or "",
            "score": item.get("score"),
        }
    )


async def advanced_search(
    query: str,
    *,
    province_id: int | None = None,
    page: int = 1,
    category_id: int = 0,
    limit: int = 12,
) -> dict[str, Any]:
    """
    Tìm kiếm nâng cao — tham chiếu cps-nuxt-standard/store/search-graphql.js.
    Trả products, related_categories, meta.
    """
    query = query.strip()
    if not query:
        return {"products": [], "related_categories": [], "meta": {}}

    pid = province_id if province_id is not None else CPS_PROVINCE_ID
    variables: dict[str, Any] = {
        "terms": query,
        "province": pid,
        "page": page,
    }
    if category_id:
        variables["categoryId"] = category_id

    async with httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=30.0) as client:
        try:
            payload = {"query": ADVANCED_SEARCH_QUERY, "variables": variables}
            from cps_bot.core.api_trace import record_from_context

            record_from_context(
                name="CPS advanced_search",
                operation="advanced_search",
                endpoint=SEARCH_GRAPHQL_URL,
                graphql_query=ADVANCED_SEARCH_QUERY,
                variables=variables,
            )
            response = await client.post(
                SEARCH_GRAPHQL_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            block = data.get("data", {}).get("advanced_search") or {}
            items = block.get("products") or []
            products = [_map_search_product_item(item) for item in items[:limit]]
            return {
                "products": products,
                "related_categories": block.get("related_categories") or [],
                "meta": block.get("meta") or {},
            }
        except Exception as exc:
            logger.warning("API advanced_search lỗi: %s", exc)
            return {"products": [], "related_categories": [], "meta": {}}


def search_results_need_advanced(
    results: list[dict[str, Any]],
    keywords: str,
) -> bool:
    """True khi kết quả search trống hoặc nhiễu — nên thử API search khác."""
    if not results:
        return True
    if len(results) == 1:
        return False
    kw_tokens = {
        t
        for t in re.sub(r"[^\w\s]", " ", keywords.lower()).split()
        if len(t) >= 2 or t.isdigit()
    }
    if not kw_tokens:
        return False
    best = results[0]
    name_tokens = set(re.sub(r"[^\w\s]", " ", (best.get("name") or "").lower()).split())
    overlap = len(kw_tokens & name_tokens)
    return overlap < max(1, len(kw_tokens) // 3)


async def _quick_search(
    client: httpx.AsyncClient,
    query: str,
    *,
    province_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """GraphQL quick_search — fallback khi advanced_search thiếu/nhiễu."""
    products: list[dict[str, Any]] = []
    try:
        payload = {
            "query": QUICK_SEARCH_QUERY,
            "variables": {
                "terms": query,
                "province": province_id,
            },
        }
        from cps_bot.core.api_trace import record_from_context

        record_from_context(
            name="CPS quick_search",
            operation="quick_search",
            endpoint=SEARCH_GRAPHQL_URL,
            graphql_query=QUICK_SEARCH_QUERY,
            variables=payload["variables"],
        )
        response = await client.post(
            SEARCH_GRAPHQL_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        items = (
            data.get("data", {})
            .get("quick_search", {})
            .get("products", [])
            or []
        )
        for item in items[:limit]:
            products.append(_map_search_product_item(item))
    except Exception as exc:
        logger.warning("API quick_search lỗi: %s", exc)
    return products


async def search_products(
    query: str,
    limit: int = 8,
    *,
    province_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Tìm sản phẩm theo từ khóa qua API GraphQL của Cellphones.
    Ưu tiên advanced_search, fallback quick_search rồi scrape catalog.
    """
    query = query.strip()
    if not query:
        return []

    pid = province_id if province_id is not None else CPS_PROVINCE_ID

    adv = await advanced_search(query, province_id=pid, limit=limit)
    products: list[dict[str, Any]] = list(adv.get("products") or [])

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, timeout=30.0
    ) as client:
        if search_results_need_advanced(products, query):
            quick = await _quick_search(
                client, query, province_id=pid, limit=limit
            )
            if quick:
                products = quick

        if not products:
            try:
                search_url = f"{CATALOG_SEARCH_URL}?q={quote_plus(query)}"
                html = await _fetch_html(client, search_url)
                products = _parse_search_fallback_html(html, limit=limit)
            except Exception as exc:
                logger.error("Scrape catalogsearch thất bại: %s", exc)

    return products


async def get_product_detail(url: str) -> dict[str, Any]:
    """
    Lấy chi tiết sản phẩm: tên, giá, mô tả, thông số, tình trạng hàng.
    """
    url = _full_url(url)

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, timeout=30.0
    ) as client:
        try:
            html = await _fetch_html(client, url)
            return _parse_detail_html(html, url)
        except httpx.HTTPError as exc:
            logger.error("Không tải được trang chi tiết %s: %s", url, exc)
            return {
                "name": "",
                "price": "",
                "old_price": "",
                "description": "",
                "specifications": {},
                "stock_status": "Không truy cập được",
                "url": url,
                "thumbnail": "",
                "error": str(exc),
            }


def build_product_payload(
    search_results: list[dict[str, Any]],
    detail: dict[str, Any],
) -> dict[str, Any]:
    """Gộp kết quả tìm kiếm + chi tiết để gửi cho Gemini."""
    results = normalize_search_results(search_results)
    if is_browse_list_mode(detail):
        primary = _browse_list_primary(detail)
    else:
        primary = normalize_search_result(detail)
    return {
        "search_results": results,
        "primary_product": primary,
        "browse_list_mode": is_browse_list_mode(detail),
        "browse_product_count": detail.get("product_count") or len(results),
    }


# Cho phép test nhanh: python scraper.py "iphone 15"
if __name__ == "__main__":

    async def _main() -> None:
        import sys

        keyword = " ".join(sys.argv[1:]) or "iphone 15 pro max"
        found = await search_products(keyword)
        print(f"Tìm thấy {len(found)} sản phẩm:")
        for p in found[:3]:
            print("-", p["name"], p["price"], p["url"])
        if found:
            detail = await get_product_detail(found[0]["url"])
            print("\nChi tiết:", detail.get("name"))
            print("Tồn kho:", detail.get("stock_status"))

    asyncio.run(_main())
