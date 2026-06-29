"""Test guard reuse product identity vs semantic follow-up."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cps_bot.llm.gemini_client import (
    identity_compatible_with_session,
    models_conflict_with_session,
    should_reuse_product_identity,
)


def _ctx(keywords: str, product: str) -> str:
    return (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        f"Sản phẩm đang thảo luận: {product}\n"
        f"Từ khóa tìm gần nhất: {keywords}\n"
        "Khách: iphone 17\n"
        "Bot: Giá từ ..."
    )


def test_models_conflict_iphone_17_to_15() -> None:
    assert models_conflict_with_session(
        "iphone 15",
        last_keywords="iPhone 17 256GB",
        last_product_name="iPhone 17 256GB | Chính hãng-Trắng",
    )


def test_models_no_conflict_color_follow_up() -> None:
    assert not models_conflict_with_session(
        "còn màu nào khác không",
        last_keywords="iPhone 17 256GB",
        last_product_name="iPhone 17 256GB | Chính hãng-Trắng",
    )


def test_models_conflict_standalone_15_pro() -> None:
    assert models_conflict_with_session(
        "15 pro",
        last_keywords="iPhone 17",
        last_product_name="iPhone 17 256GB",
    )


def test_should_not_reuse_identity_on_topic_switch() -> None:
    ctx = _ctx("iPhone 17 256GB", "iPhone 17 256GB | Chính hãng-Trắng")
    assert not should_reuse_product_identity(
        "iphone 15",
        ctx,
        last_keywords="iPhone 17 256GB",
        last_product_name="iPhone 17 256GB | Chính hãng-Trắng",
    )


def test_should_not_reuse_identity_ip16_to_ip15_shorthand() -> None:
    ctx = _ctx("iphone 16 xanh mòng két", "iPhone 16 128GB | Chính hãng VN/A-Xanh Mòng Két")
    assert models_conflict_with_session(
        "ip15 plus màu xanh giá bao nhiêu",
        last_keywords="iphone 16 xanh mòng két",
        last_product_name="iPhone 16 128GB | Chính hãng VN/A-Xanh Mòng Két",
    )
    assert not should_reuse_product_identity(
        "ip15 plus màu xanh giá bao nhiêu",
        ctx,
        last_keywords="iphone 16 xanh mòng két",
        last_product_name="iPhone 16 128GB | Chính hãng VN/A-Xanh Mòng Két",
    )
    assert not identity_compatible_with_session(
        "ip15 plus màu xanh giá bao nhiêu",
        last_keywords="iphone 16 xanh mòng két",
        last_product_name="iPhone 16 128GB | Chính hãng VN/A-Xanh Mòng Két",
    )


def test_should_reuse_identity_on_color_follow_up() -> None:
    ctx = _ctx("iPhone 17 256GB", "iPhone 17 256GB | Chính hãng-Trắng")
    assert should_reuse_product_identity(
        "còn màu nào khác không",
        ctx,
        last_keywords="iPhone 17 256GB",
        last_product_name="iPhone 17 256GB | Chính hãng-Trắng",
    )


def test_should_reuse_identity_on_storage_follow_up() -> None:
    ctx = _ctx("iPhone 17", "iPhone 17 256GB")
    assert should_reuse_product_identity(
        "bản 512gb thì sao",
        ctx,
        last_keywords="iPhone 17",
        last_product_name="iPhone 17 256GB",
    )


def test_should_reuse_identity_on_province_stock_follow_up() -> None:
    ctx = _ctx("iPhone 17 256GB Xanh", "iPhone 17 256GB Xanh dương")
    assert should_reuse_product_identity(
        "còn hàng ở hà nội không",
        ctx,
        last_keywords="iPhone 17 256GB Xanh",
        last_product_name="iPhone 17 256GB Xanh dương",
    )


def test_identity_compatible_blocks_new_product() -> None:
    assert not identity_compatible_with_session(
        "iphone 15",
        last_keywords="iPhone 17",
        last_product_name="iPhone 17 256GB",
    )


def test_fetch_skips_session_fallback_on_topic_switch() -> None:
    async def _run() -> str:
        with patch(
            "cps_bot.cps.cps_api.get_product_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            from cps_bot.cps.cps_api import _fetch_product_for_query_body

            stats: dict = {}
            with patch(
                "cps_bot.cps.cps_api.search_products",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "name": "iPhone 15 256GB",
                        "url_path": "iphone-15-256gb.html",
                        "url": "https://cellphones.com.vn/iphone-15-256gb.html",
                        "price": "20.000.000",
                        "product_id": "90001",
                    }
                ],
            ), patch(
                "cps_bot.cps.cps_api.fetch_product_from_url",
                new_callable=AsyncMock,
                return_value={"name": "iPhone 15 256GB", "product_id": "90001"},
            ), patch(
                "cps_bot.cps.cps_api.resolve_commerce_product_detail",
                new_callable=AsyncMock,
                side_effect=lambda d, **kw: d,
            ):
                await _fetch_product_for_query_body(
                    "iphone 15",
                    user_message="iphone 15",
                    fallback_url="https://cellphones.com.vn/iphone-17-256gb.html",
                    fallback_product_id="112598",
                    session_last_keywords="iPhone 17 256GB",
                    session_last_product_name="iPhone 17 256GB | Chính hãng-Trắng",
                    stats=stats,
                )
            mock_get.assert_not_called()
            return str(stats.get("resolve_source") or "")

    source = asyncio.run(_run())
    assert source != "session_fallback_product_id"
