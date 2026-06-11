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


def product_url_from_record(record: dict[str, Any] | None) -> str:
    """URL sản phẩm — luôn ưu tiên url_path từ GraphQL."""
    if not record:
        return ""
    url_path = str(record.get("url_path") or "").strip()
    if url_path:
        return _full_url(url_path)
    return str(record.get("url") or "").strip()


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
    - Nhiều SP → danh mục (category_url) hoặc trang search theo từ khóa
    """
    keywords = (search_keywords or "").strip()
    category_url = str(detail.get("category_url") or "").strip()

    if is_single_product_result(search_results, detail):
        product_url = product_url_from_record(detail)
        if product_url:
            return product_url
        if search_results:
            first_url = product_url_from_record(search_results[0])
            if first_url:
                return first_url

    if category_url:
        return category_url
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


async def search_products(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """
    Tìm sản phẩm theo từ khóa qua API GraphQL của Cellphones.
    Trả về: name, price, url, thumbnail.
    """
    query = query.strip()
    if not query:
        return []

    products: list[dict[str, Any]] = []

    async with httpx.AsyncClient(
        headers=DEFAULT_HEADERS, timeout=30.0
    ) as client:
        # Ưu tiên API quick_search (ổn định hơn scrape HTML)
        try:
            payload = {
                "query": QUICK_SEARCH_QUERY,
                "variables": {
                    "terms": query,
                    "province": CPS_PROVINCE_ID,
                },
            }
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
                url_path = item.get("url_path") or ""
                display = item.get("display_price") or item.get("special_price")
                if display is None:
                    display = item.get("price")
                products.append(
                    {
                        "name": item.get("name", ""),
                        "price": _format_price(display),
                        "url_path": url_path,
                        "url": _full_url(url_path),
                        "thumbnail": _thumbnail_url(item.get("thumbnail")),
                    }
                )
        except Exception as exc:
            logger.warning("API quick_search lỗi: %s", exc)

        # Dự phòng: scrape trang kết quả tìm kiếm
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
    return {
        "search_results": search_results,
        "primary_product": detail,
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
