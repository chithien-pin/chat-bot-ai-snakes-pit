"""
Lazy-fetch GraphQL bổ sung theo kịch bản — reviews, FAQ, trade-in, flash sale, combo.
Tham chiếu cps-nuxt-standard store modules.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import (
    CPS_GRAPHQL_CUSTOMER_ENDPOINT,
    CPS_GRAPHQL_DASHBOARD_ENDPOINT,
    CPS_GRAPHQL_V2_ENDPOINT,
    CPS_PROVINCE_ID,
)
from cps_bot.cps.cps_api import _graphql, company_id_for_province
from cps_bot.cps.cps_provinces import PROVINCE_ID_TO_NAME

logger = logging.getLogger(__name__)

REVIEWS_QUERY = """
query REVIEWS($productId: Int!, $page: Int!) {
  reviews(page: $page, product_id: $productId) {
    total
    matches {
      id
      content
      rating_id
      created_at
      is_purchased
      customer { fullname }
    }
  }
}
"""

REVIEW_STATS_QUERY = """
query RATINGS($productId: Int!) {
  review_stats(product_id: $productId) {
    average_rating
    total_reviews
    rating_breakdown { rating_id count }
  }
}
"""

FAQS_QUERY = """
query faqs($url: String!) {
  faq(url: $url) {
    question
    answer
    score
  }
}
"""

TRADE_PRODUCTS_QUERY = """
query trade_product($productId: Int!, $tradeType: Int!) {
  trade_products(productId: $productId, tradeType: $tradeType) {
    exchange_products {
      webId
      name
      brand
      thuLoai1
      thuLoai2
      thuLoai3
      thuLoai4
      troGia
      text
    }
    applied_promotion_width
  }
}
"""

FLASH_SALE_QUERY = """
query FlashSaleProgram($provinceId: Int!, $parentId: Int!, $childId: Int!) {
  flash_sale_programs(
    province_id: $provinceId
    products: { parent_ids: [$parentId], children_ids: [$childId] }
  ) {
    id
    title
    is_active
    started_at
    ended_at
    flash_sale_slots {
      product_id
      product_name
      max_slot
      sold
      product_url
      flash_sale_prices {
        product_flash_sale_price
        product_special_price
        product_normal_price
      }
    }
  }
}
"""

COMBO_QUERY = """
query COMBO_LIST($productId: Int!, $categoryIds: [Int!]!) {
  combo(productId: $productId, categoryIds: $categoryIds) {
    id
    name
    discount_percent
    max_value
    thumbnail
    combo_id
    score
  }
}
"""

INSTOCK_BY_LIST_QUERY = """
query InstockProvinces($productIds: String!, $companyId: Int!) {
  instock_provinces_by_list(product_ids: [$productIds], company_id: $companyId)
}
"""


async def fetch_product_reviews(product_id: str | int, *, page: int = 1) -> dict[str, Any] | None:
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        stats_payload = await _graphql(
            client,
            CPS_GRAPHQL_CUSTOMER_ENDPOINT,
            REVIEW_STATS_QUERY,
            {"productId": pid},
        )
        reviews_payload = await _graphql(
            client,
            CPS_GRAPHQL_CUSTOMER_ENDPOINT,
            REVIEWS_QUERY,
            {"productId": pid, "page": page},
        )

    stats = stats_payload.get("data", {}).get("review_stats") or {}
    reviews_block = reviews_payload.get("data", {}).get("reviews") or {}
    matches = reviews_block.get("matches") or []
    if not stats and not matches:
        return None

    sample = []
    for row in matches[:5]:
        if not isinstance(row, dict):
            continue
        customer = row.get("customer") or {}
        sample.append(
            {
                "rating_id": row.get("rating_id"),
                "content": (row.get("content") or "")[:300],
                "author": customer.get("fullname") or "Khách",
                "is_purchased": row.get("is_purchased"),
            }
        )

    return {
        "average_rating": stats.get("average_rating"),
        "total_reviews": stats.get("total_reviews") or reviews_block.get("total"),
        "rating_breakdown": stats.get("rating_breakdown") or [],
        "sample_reviews": sample,
    }


async def fetch_product_faqs(url_path: str) -> list[dict[str, str]] | None:
    path = (url_path or "").strip().lstrip("/")
    if not path:
        return None
    if path.endswith(".html"):
        path = path[:-5]

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            FAQS_QUERY,
            {"url": path},
        )
    rows = payload.get("data", {}).get("faq") or []
    if not rows:
        return None
    faqs: list[dict[str, str]] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        q = str(row.get("question") or "").strip()
        a = str(row.get("answer") or "").strip()
        if q and a:
            faqs.append({"question": q, "answer": a})
    return faqs or None


async def fetch_trade_exchange_products(
    product_id: str | int,
    *,
    trade_type: int = 5,
) -> dict[str, Any] | None:
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            TRADE_PRODUCTS_QUERY,
            {"productId": pid, "tradeType": trade_type},
        )
    block = payload.get("data", {}).get("trade_products") or {}
    exchange = block.get("exchange_products") or []
    if not exchange:
        return None

    devices: list[dict[str, Any]] = []
    for row in exchange[:12]:
        if not isinstance(row, dict):
            continue
        devices.append(
            {
                "name": row.get("name") or "",
                "brand": row.get("brand") or "",
                "thu_loai_1": row.get("thuLoai1"),
                "thu_loai_2": row.get("thuLoai2"),
                "thu_loai_3": row.get("thuLoai3"),
                "thu_loai_4": row.get("thuLoai4"),
                "tro_gia": row.get("troGia"),
                "note": row.get("text") or "",
            }
        )
    return {
        "exchange_products": devices,
        "trade_type": trade_type,
        "note": "Giá thu thực tế phụ thuộc tình trạng máy tại cửa hàng.",
    }


async def fetch_flash_sale_for_product(
    detail: dict[str, Any],
    *,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    product_id = detail.get("product_id")
    if not product_id:
        return None
    try:
        child_id = int(product_id)
    except (TypeError, ValueError):
        return None

    parent_id = child_id
    up_sell = detail.get("up_sell") or []
    if isinstance(up_sell, list) and up_sell:
        first = up_sell[0]
        if isinstance(first, dict):
            raw_parent = first.get("parent_id") or first.get("product_id")
        else:
            raw_parent = first
        try:
            parent_id = int(raw_parent)
        except (TypeError, ValueError):
            parent_id = child_id

    pid = province_id if province_id is not None else CPS_PROVINCE_ID
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            FLASH_SALE_QUERY,
            {
                "provinceId": pid,
                "parentId": parent_id,
                "childId": child_id,
            },
        )
    programs = payload.get("data", {}).get("flash_sale_programs") or []
    if not programs:
        return None

    program = programs[0] if isinstance(programs[0], dict) else {}
    slots = program.get("flash_sale_slots") or []
    active_slots: list[dict[str, Any]] = []
    for slot in slots[:5]:
        if not isinstance(slot, dict):
            continue
        prices = (slot.get("flash_sale_prices") or [{}])[0]
        if isinstance(prices, dict):
            flash_price = prices.get("product_flash_sale_price")
        else:
            flash_price = None
        active_slots.append(
            {
                "product_name": slot.get("product_name") or "",
                "max_slot": slot.get("max_slot"),
                "sold": slot.get("sold"),
                "flash_price": flash_price,
                "url": slot.get("product_url") or "",
            }
        )
    return {
        "title": program.get("title") or "",
        "is_active": program.get("is_active"),
        "started_at": program.get("started_at"),
        "ended_at": program.get("ended_at"),
        "slots": active_slots,
    }


async def fetch_product_combos(detail: dict[str, Any]) -> list[dict[str, Any]] | None:
    product_id = detail.get("product_id")
    if not product_id:
        return None
    try:
        pid = int(product_id)
    except (TypeError, ValueError):
        return None

    category_ids: list[int] = []
    for raw in detail.get("category_ids") or []:
        try:
            category_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    if not category_ids and detail.get("category_id"):
        try:
            category_ids.append(int(detail["category_id"]))
        except (TypeError, ValueError):
            pass
    if not category_ids:
        return None

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            COMBO_QUERY,
            {"productId": pid, "categoryIds": category_ids},
        )
    rows = payload.get("data", {}).get("combo") or []
    if not rows:
        return None
    combos: list[dict[str, Any]] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        combos.append(
            {
                "name": row.get("name") or "",
                "discount_percent": row.get("discount_percent"),
                "max_value": row.get("max_value"),
                "combo_id": row.get("combo_id"),
            }
        )
    return combos or None


async def fetch_instock_by_variant_ids(
    product_ids: list[int],
    *,
    province_id: int | None = None,
) -> dict[str, list[str]] | None:
    if not product_ids:
        return None
    pid_province = province_id if province_id is not None else CPS_PROVINCE_ID
    company_id = company_id_for_province(pid_province)
    ids_str = ", ".join(str(i) for i in product_ids)

    query = f"""
query InstockProvinces {{
  instock_provinces_by_list(product_ids: [{ids_str}], company_id: {company_id})
}}
"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_V2_ENDPOINT,
            query,
            {},
        )
    raw = payload.get("data", {}).get("instock_provinces_by_list") or {}
    if not raw:
        return None

    result: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for key, provinces in raw.items():
            names: list[str] = []
            if isinstance(provinces, list):
                for prov in provinces:
                    if isinstance(prov, dict):
                        prov_id = prov.get("province_id") or prov.get("id")
                    else:
                        prov_id = prov
                    try:
                        name = PROVINCE_ID_TO_NAME.get(int(prov_id), "")
                    except (TypeError, ValueError):
                        name = ""
                    if name and name not in names:
                        names.append(name)
            if names:
                result[str(key)] = names
    return result or None


async def enrich_extended_scenarios(
    payload: dict[str, Any],
    detail: dict[str, Any],
    scenarios: dict[str, bool],
    *,
    province_id: int | None = None,
) -> dict[str, bool]:
    """Fetch dữ liệu bổ sung từ GraphQL theo scenario flags."""
    fetched: dict[str, bool] = {}
    product_id = detail.get("product_id")

    if scenarios.get("reviews") and product_id:
        reviews = await fetch_product_reviews(product_id)
        if reviews:
            payload["product_reviews"] = reviews
            fetched["product_reviews"] = True

    if scenarios.get("faq_policy") or scenarios.get("warranty"):
        url_path = detail.get("url_path") or ""
        faqs = await fetch_product_faqs(url_path)
        if faqs:
            payload["product_faqs"] = faqs
            fetched["product_faqs"] = True

    if (scenarios.get("trade_in_device") or scenarios.get("trade_in")) and product_id:
        trade_devices = await fetch_trade_exchange_products(product_id)
        if trade_devices:
            payload["trade_exchange_products"] = trade_devices
            fetched["trade_exchange_products"] = True

    if scenarios.get("flash_sale") and product_id:
        flash = await fetch_flash_sale_for_product(detail, province_id=province_id)
        if flash:
            payload["flash_sale"] = flash
            fetched["flash_sale"] = True

    if scenarios.get("combo") and product_id:
        combos = await fetch_product_combos(detail)
        if combos:
            payload["product_combos"] = combos
            fetched["product_combos"] = True

    if scenarios.get("shop_stock") and detail.get("up_sell"):
        variant_ids = []
        for raw in _collect_variant_ids(detail):
            if raw not in variant_ids:
                variant_ids.append(raw)
        if len(variant_ids) > 1:
            instock_map = await fetch_instock_by_variant_ids(
                variant_ids,
                province_id=province_id,
            )
            if instock_map:
                payload["instock_by_variant"] = instock_map
                fetched["instock_by_variant"] = True

    return fetched


def _collect_variant_ids(detail: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    try:
        current = int(detail.get("product_id") or 0)
    except (TypeError, ValueError):
        current = 0
    if current:
        ids.append(current)
    for item in detail.get("up_sell") or []:
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
    return ids
