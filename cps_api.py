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
    CPS_GRAPHQL_URL_ENDPOINT,
    CPS_GRAPHQL_V2_ENDPOINT,
    CPS_PROVINCE_ID,
)
from scraper import BASE_URL, _format_price, _full_url, search_products

logger = logging.getLogger(__name__)

CELLPHONES_URL_RE = re.compile(
    r"https?://(?:www\.)?cellphones\.com\.vn/[^\s<>\"']+\.html",
    re.IGNORECASE,
)

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
      special_price
      thumbnail
      product_state
      short_description
      stock
      stock_available_id
      display_price
      promotion_info
      product_condition
    }
    specification {
      basic
      full_by_group
    }
  }
}
"""


def extract_cellphones_urls(text: str) -> list[str]:
    return CELLPHONES_URL_RE.findall(text or "")


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
    if stock is not None:
        try:
            stock_num = int(stock)
            if stock_num > 0:
                parts.append(f"Còn hàng ({stock_num})")
            elif not product_state:
                parts.append("Tạm hết hàng")
        except (TypeError, ValueError):
            pass
    elif stock_available_id is not None:
        try:
            if int(stock_available_id) > 0:
                parts.append("Còn hàng")
        except (TypeError, ValueError):
            pass

    return " — ".join(dict.fromkeys(parts)) if parts else "Không rõ"


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

    url_path = general.get("url_path") or ""
    product_url = url or (_full_url(url_path) if url_path else "")

    display_price = filterable.get("display_price")
    special_price = filterable.get("special_price")
    base_price = filterable.get("price")
    sale_price = display_price if display_price is not None else special_price
    old_price_val = None
    if base_price is not None and sale_price is not None:
        try:
            if float(base_price) > float(sale_price):
                old_price_val = base_price
        except (TypeError, ValueError):
            pass

    thumbnail = filterable.get("thumbnail") or ""
    if thumbnail and not str(thumbnail).startswith("http"):
        thumbnail = _full_url(str(thumbnail))

    categories = [
        cat.get("name")
        for cat in (general.get("categories") or [])
        if isinstance(cat, dict) and cat.get("name")
    ]

    return {
        "name": general.get("name") or filterable.get("short_name") or "",
        "price": _format_price(sale_price),
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
        "url": product_url,
        "thumbnail": thumbnail,
        "product_id": str(
            general.get("product_id")
            or (url_info or {}).get("product_id")
            or ""
        ),
        "category_id": str(
            (url_info or {}).get("category_id")
            or (categories[0] if categories else "")
            or ""
        ),
        "sku": general.get("sku") or "",
        "manufacturer": general.get("manufacturer") or "",
        "categories": categories,
        "promotion_info": _strip_html(str(filterable.get("promotion_info") or "")),
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
    return payload.get("data", {}).get("product")


async def fetch_product_from_url(url: str) -> dict[str, Any]:
    """URL CellphoneS → detail chuẩn hóa."""
    info = await url_info(url)
    if not info or not info.get("product_id"):
        raise ValueError(f"Không resolve được product_id từ URL: {url}")

    product = await get_product_by_id(info["product_id"])
    if not product:
        raise ValueError(f"Không lấy được chi tiết product_id={info['product_id']}")

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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Tìm sản phẩm theo link trong tin nhắn, URL session cũ, hoặc quick_search.
    Chi tiết lấy qua CPS GraphQL (không scrape HTML).
    """
    target_url = ""

    for url in extract_cellphones_urls(user_message):
        target_url = url
        break

    if not target_url and fallback_url:
        target_url = fallback_url

    search_results: list[dict[str, Any]] = []
    if not target_url:
        search_results = await search_products(keywords)
        if not search_results:
            return [], {}
        target_url = search_results[0].get("url", "")

    if not target_url:
        return search_results, {}

    try:
        detail = await fetch_product_from_url(target_url)
    except Exception as exc:
        logger.error("CPS fetch thất bại (%s): %s", target_url, exc)
        return search_results, {}

    if not search_results:
        search_results = [
            {
                "name": detail.get("name", ""),
                "price": detail.get("price", ""),
                "url": detail.get("url", target_url),
                "thumbnail": detail.get("thumbnail", ""),
                "product_id": detail.get("product_id", ""),
            }
        ]

    return search_results, detail
