"""Test variant hint extraction + commerce detail resolution helpers."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cps_bot.cps.cps_api import (
    _default_filterable_product_id,
    _extract_variant_hints,
    _variant_hint_score,
    is_commerce_detail_query,
    resolve_commerce_product_detail,
)


def test_storage_hint() -> None:
    hints = _extract_variant_hints("iPhone 16 Pro Max 256GB Titan")
    assert "256gb" in hints


def test_color_hint() -> None:
    hints = _extract_variant_hints("iPhone 16 Plus 256 màu hồng")
    assert "hồng" in hints


def test_cam_color_hint() -> None:
    hints = _extract_variant_hints("iphone 17 pro max màu cam")
    assert "cam" in hints


def test_xanh_duong_color_hint() -> None:
    hints = _extract_variant_hints("màu xanh dương thì sao")
    assert "xanh dương" in hints
    assert "xanh lá" not in hints
    assert hints.count("xanh") == 0 or "xanh dương" in hints


def test_xanh_la_vs_xanh_duong_score() -> None:
    blue_score = _variant_hint_score(
        "iPhone 15 128GB | Chính hãng VN/A – Xanh dương",
        ["xanh dương"],
    )
    green_score = _variant_hint_score(
        "iPhone 15 128GB | Chính hãng VN/A – Xanh lá",
        ["xanh dương"],
    )
    assert blue_score >= 10
    assert green_score == 0


def test_xanh_duong_beats_generic_xanh() -> None:
    hints = _extract_variant_hints("iphone 15 xanh dương")
    assert "xanh dương" in hints
    generic = _extract_variant_hints("iphone 15 màu xanh")
    assert "xanh" in generic
    assert "xanh dương" not in generic


def test_variant_score() -> None:
    score = _variant_hint_score("iPhone 16 Pro Max 256GB Titan Tự Nhiên", ["256gb", "titan"])
    assert score >= 20


def test_default_filterable_product_id() -> None:
    product = {
        "general": {"product_id": 100},
        "filterable": {"default": {"product_id": 200}},
    }
    assert _default_filterable_product_id(product) == "200"


def test_commerce_detail_query_price() -> None:
    assert is_commerce_detail_query("Giá iPhone 17 Pro Max bao nhiêu")


def test_commerce_detail_query_specs_only() -> None:
    assert not is_commerce_detail_query("Thông số camera iPhone 17 Pro Max megapixel")


def test_commerce_preserves_color_on_stock_follow_up() -> None:
    detail = {
        "product_id": "111",
        "default_product_id": "999",
        "name": "iPhone 15 128GB | Chính hãng VN/A – Xanh dương",
        "url": "https://cellphones.com.vn/iphone-15.html",
    }

    async def _run() -> dict:
        with patch(
            "cps_bot.cps.cps_api.get_product_by_id",
            new_callable=AsyncMock,
        ) as mock_get:
            result = await resolve_commerce_product_detail(
                detail,
                keywords="iPhone 15 128GB Xanh Dương",
                user_message="còn hàng ở hà nội không?",
                province_id=1,
            )
            mock_get.assert_not_called()
            return result

    result = asyncio.run(_run())
    assert result["product_id"] == "111"
    assert "Xanh dương" in result["name"]


if __name__ == "__main__":
    test_storage_hint()
    test_color_hint()
    test_cam_color_hint()
    test_variant_score()
    test_default_filterable_product_id()
    test_commerce_detail_query_price()
    test_commerce_detail_query_specs_only()
    test_commerce_preserves_color_on_stock_follow_up()
    print("OK — variant resolve tests passed")
