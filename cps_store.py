"""
Cửa hàng CellphoneS — shops_stock_full, shop lookup.
Tham chiếu cps-nuxt-standard/store/shop-data.js, province.js
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import CPS_GRAPHQL_DASHBOARD_ENDPOINT, CPS_PROVINCE_ID
from cps_api import _graphql, company_id_for_province
from cps_provinces import PROVINCE_ID_TO_NAME, resolve_province_from_text

logger = logging.getLogger(__name__)

SHOPS_STOCK_FULL_QUERY = """
query ShopStockFull($companyId: Int!, $provinceId: Int!) {
  shops_stock_full(companyId: $companyId, provinceId: $provinceId) {
    district_name
    district_id
    shops {
      id
      address
      phone
      google_link
      time_opening
    }
  }
}
"""

SHOPS_BY_IDS_QUERY = """
query shops_by_shop_ids($shopIds: [Int!]!) {
  shops(shopIds: $shopIds) {
    id
    code
    address
    google_link
    phone
    company_id
  }
}
"""

SHOP_BY_ID_QUERY = """
query shop_info($shopId: Int!) {
  shop(id: $shopId) {
    id
    code
    address
    phone
    google_link
    company_id
  }
}
"""


async def fetch_all_shops_in_province(
    *,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    """Danh sách tất cả CH trong tỉnh — không cần product_id."""
    pid = province_id if province_id is not None else CPS_PROVINCE_ID
    company_id = company_id_for_province(pid)

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            SHOPS_STOCK_FULL_QUERY,
            {"companyId": company_id, "provinceId": pid},
        )
    districts = payload.get("data", {}).get("shops_stock_full") or []
    if not districts:
        return None

    total = 0
    district_list: list[dict[str, Any]] = []
    for dist in districts:
        if not isinstance(dist, dict):
            continue
        shops = dist.get("shops") or []
        total += len(shops)
        district_list.append(
            {
                "district_name": dist.get("district_name") or "",
                "shop_count": len(shops),
                "shops": [
                    {
                        "address": s.get("address") or "",
                        "phone": s.get("phone") or "",
                        "google_link": s.get("google_link") or "",
                        "time_opening": s.get("time_opening") or "",
                    }
                    for s in shops[:5]
                    if isinstance(s, dict)
                ],
            }
        )

    return {
        "province_id": pid,
        "province_name": PROVINCE_ID_TO_NAME.get(pid, ""),
        "total_shops": total,
        "districts": district_list[:12],
    }


async def fetch_shops_by_ids(shop_ids: list[int]) -> list[dict[str, Any]]:
    if not shop_ids:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = await _graphql(
            client,
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            SHOPS_BY_IDS_QUERY,
            {"shopIds": shop_ids},
        )
    return payload.get("data", {}).get("shops") or []


async def fetch_store_locator_context(
    user_question: str,
    *,
    province_id: int | None = None,
) -> dict[str, Any] | None:
    """Context cửa hàng khi khách hỏi shop ở tỉnh (không gắn SP)."""
    pid = province_id or resolve_province_from_text(user_question) or CPS_PROVINCE_ID
    return await fetch_all_shops_in_province(province_id=pid)
