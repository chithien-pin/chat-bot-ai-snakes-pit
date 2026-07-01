"""Regression: câu hỏi SP mới không pin session iPhone."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cps_bot.llm.gemini_client import (
    extract_search_keywords,
    identity_compatible_with_session,
    should_reuse_product_identity,
)


def _ctx() -> str:
    return (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        "Sản phẩm đang thảo luận: iPhone 17 Pro 256GB | Chính hãng\n"
        "Từ khóa tìm gần nhất: iphone 17 pro\n"
    )


def test_neck_fan_not_reuse_iphone_session() -> None:
    q = "có quạt mini đeo cổ không"
    ctx = _ctx()
    assert not should_reuse_product_identity(
        q,
        ctx,
        last_keywords="iphone 17 pro",
        last_product_name="iPhone 17 Pro 256GB | Chính hãng",
    )
    assert not identity_compatible_with_session(
        q,
        last_keywords="iphone 17 pro",
        last_product_name="iPhone 17 Pro 256GB | Chính hãng",
    )


def test_neck_fan_keywords_not_iphone() -> None:
    q = "có quạt mini đeo cổ không"
    kw = extract_search_keywords(q, _ctx(), use_llm=False)
    assert "iphone" not in kw.lower()
    assert "quat" in kw.lower()


def test_fetch_uses_search_not_session_for_neck_fan() -> None:
    async def _run() -> str:
        with patch(
            "cps_bot.cps.cps_api.get_product_by_id",
            new_callable=AsyncMock,
        ) as mock_get, patch(
            "cps_bot.cps.cps_api.search_products",
            new_callable=AsyncMock,
            return_value=[],
        ), patch(
            "cps_bot.cps.cps_api._fetch_products_by_category_filter",
            new_callable=AsyncMock,
            return_value=None,
        ), patch(
            "cps_bot.cps.cps_api._fetch_product_from_map",
            new_callable=AsyncMock,
            return_value=(
                [
                    {
                        "name": "Quạt đeo cổ Y06",
                        "url_path": "quat-deo-co-y06.html",
                        "url": "https://cellphones.com.vn/quat-deo-co-y06.html",
                        "price": "199.000",
                        "product_id": "81624",
                    }
                ],
                {
                    "name": "Quạt đeo cổ Y06",
                    "product_id": "81624",
                    "url": "https://cellphones.com.vn/quat-deo-co-y06.html",
                },
            ),
        ), patch(
            "cps_bot.cps.cps_api.resolve_commerce_product_detail",
            new_callable=AsyncMock,
            side_effect=lambda d, **kw: d,
        ):
            from cps_bot.cps.cps_api import _fetch_product_for_query_body

            stats: dict = {
                "serpapi_calls": 0,
                "search_products_calls": 0,
                "cps_url_info_calls": 0,
                "cps_product_detail_calls": 0,
                "category_filter_calls": 0,
                "api_calls_detail": [],
                "resolve_source": "",
            }
            q = "có quạt mini đeo cổ không"
            kw = extract_search_keywords(q, _ctx(), use_llm=False)
            await _fetch_product_for_query_body(
                kw,
                user_message=q,
                fallback_url="https://cellphones.com.vn/iphone-17-pro.html",
                fallback_product_id="112598",
                session_last_keywords="iphone 17 pro",
                session_last_product_name="iPhone 17 Pro 256GB | Chính hãng",
                stats=stats,
            )
            mock_get.assert_not_called()
            return str(stats.get("resolve_source") or "")

    source = asyncio.run(_run())
    assert source == "product_map"
