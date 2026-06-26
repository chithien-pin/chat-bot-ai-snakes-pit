"""Test resolve màu sibling qua parent_id."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

from cps_bot.cps.cps_api import (
    _load_child_product_ids,
    _resolve_color_parent_product_id,
    _resolve_sibling_color_product_ids,
    fetch_color_sibling_variants,
)


def test_resolve_parent_from_child_detail() -> None:
    async def _run() -> int | None:
        detail = {
            "product_id": "112598",
            "parent_id": "112580",
            "name": "iPhone 17 256GB | Chính hãng-Trắng",
            "child_product": [],
        }
        return await _resolve_color_parent_product_id(detail, province_id=30)

    assert asyncio.run(_run()) == 112580


def test_resolve_sibling_ids_via_parent() -> None:
    child_ids = [112595, 112598, 112600, 112601, 112602]

    async def _run() -> list[int]:
        detail = {
            "product_id": "112598",
            "parent_id": "112580",
            "child_product": [],
        }
        with patch(
            "cps_bot.cps.cps_api._load_child_product_ids",
            new_callable=AsyncMock,
            return_value=child_ids,
        ) as mock_load:
            result = await _resolve_sibling_color_product_ids(detail, province_id=30)
            mock_load.assert_awaited_once_with(112580, province_id=30)
            return result

    assert asyncio.run(_run()) == child_ids


def test_fetch_color_siblings_builds_payload() -> None:
    child_ids = [112595, 112598, 112600]

    async def _run() -> dict:
        detail = {
            "product_id": "112598",
            "parent_id": "112580",
            "name": "iPhone 17 256GB | Chính hãng-Trắng",
        }
        products = [
            {
                "general": {
                    "product_id": 112595,
                    "name": "iPhone 17 256GB | Chính hãng-Đen",
                    "url_path": "/iphone-17-256gb-den.html",
                },
                "filterable": {
                    "display_price": 23990000,
                    "stock": 10,
                    "stock_available_id": 46,
                },
            },
            {
                "general": {
                    "product_id": 112598,
                    "name": "iPhone 17 256GB | Chính hãng-Trắng",
                    "url_path": "/iphone-17-256gb-trang.html",
                },
                "filterable": {
                    "display_price": 23990000,
                    "stock": 5,
                    "stock_available_id": 46,
                },
            },
        ]
        with patch(
            "cps_bot.cps.cps_api._resolve_sibling_color_product_ids",
            new_callable=AsyncMock,
            return_value=child_ids,
        ), patch(
            "cps_bot.cps.cps_api.get_products_by_ids",
            new_callable=AsyncMock,
            return_value=products,
        ), patch(
            "cps_bot.cps.cps_api._resolve_color_parent_product_id",
            new_callable=AsyncMock,
            return_value=112580,
        ):
            return await fetch_color_sibling_variants(detail, province_id=30) or {}

    payload = asyncio.run(_run())
    assert payload.get("count", 0) >= 2
    assert payload.get("parent_product_id") == "112580"
    assert len(payload.get("variants") or []) >= 2


def test_resolve_variant_does_not_query_child_as_parent() -> None:
    async def _run() -> None:
        detail = {
            "product_id": "112598",
            "name": "iPhone 17 256GB | Chính hãng-Trắng",
            "parent_id": "",
            "child_product": [],
        }
        with patch(
            "cps_bot.cps.cps_api._resolve_color_parent_product_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "cps_bot.cps.cps_api._load_child_product_ids",
            new_callable=AsyncMock,
            return_value=[],
        ) as mock_load:
            from cps_bot.cps.cps_api import resolve_product_variant

            result = await resolve_product_variant(
                "iphone 17 màu đen",
                detail,
                province_id=30,
            )
            mock_load.assert_not_awaited()
            assert result == detail

    asyncio.run(_run())


def test_color_list_session_skips_child_refetch() -> None:
    child_ids = [68887, 68889, 68892, 68893, 68894]

    async def _run() -> tuple[dict[str, Any], dict[str, Any]]:
        with patch(
            "cps_bot.cps.cps_api.get_product_by_id",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "cps_bot.cps.cps_api._load_child_product_ids",
            new_callable=AsyncMock,
            return_value=child_ids,
        ) as mock_load:
            from cps_bot.cps.cps_api import _fetch_product_for_query_body

            stats: dict[str, Any] = {
                "serpapi_calls": 0,
                "search_products_calls": 0,
                "cps_url_info_calls": 0,
                "cps_product_detail_calls": 0,
                "category_filter_calls": 0,
                "api_calls_detail": [],
                "resolve_source": "",
            }
            _, detail, out_stats = await _fetch_product_for_query_body(
                "iphone 15 128gb hồng",
                user_message="còn màu khác không?",
                fallback_product_id="68892",
                session_fallback_parent_id="43152",
                session_last_product_name="iPhone 15 128GB | Chính hãng VN/A-Hồng",
                stats=stats,
            )
            mock_get.assert_not_awaited()
            mock_load.assert_not_called()
            return detail, out_stats

    detail, stats = asyncio.run(_run())
    assert detail.get("parent_id") == "43152"
    assert detail.get("product_id") == "68892"
    assert stats.get("resolve_source") == "session_color_list_context"
