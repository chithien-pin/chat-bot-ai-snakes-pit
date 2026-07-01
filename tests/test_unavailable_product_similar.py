"""Test fallback sản phẩm tương tự cho SP hết hàng/đăng ký nhận tin."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cps_bot.cps.cps_api import (
    fetch_similar_products,
    is_unavailable_product_detail,
    _enrich_payload_for_scenarios_inner,
)


class UnavailableProductSimilarTest(unittest.TestCase):
    def test_is_unavailable_product_detail(self) -> None:
        self.assertTrue(
            is_unavailable_product_detail(
                {
                    "stock_available_id": 43,
                    "stock_availability": {"is_out_of_stock": True},
                }
            )
        )
        self.assertTrue(
            is_unavailable_product_detail(
                {
                    "stock_available_id": 56,
                    "stock_availability": {"is_subscription": True},
                }
            )
        )
        self.assertFalse(
            is_unavailable_product_detail(
                {
                    "stock_available_id": 46,
                    "stock_availability": {"is_out_of_stock": False},
                }
            )
        )

    def test_fetch_similar_products_filters_current_and_zero_stock(self) -> None:
        gql_payload = {
            "data": {
                "products": [
                    {
                        "general": {
                            "product_id": "2001",
                            "name": "Galaxy A tương tự",
                            "url_path": "galaxy-a-tuong-tu.html",
                            "url_key": "galaxy-a-tuong-tu",
                        },
                        "filterable": {
                            "stock_available_id": 46,
                            "stock": 5,
                            "special_price": 22990000,
                            "price": 23990000,
                            "thumbnail": "/media/a.jpg",
                        },
                    },
                    {
                        "general": {
                            "product_id": "1000",
                            "name": "Chính nó",
                            "url_path": "same-product.html",
                        },
                        "filterable": {
                            "stock_available_id": 46,
                            "stock": 10,
                            "special_price": 21990000,
                            "price": 22990000,
                        },
                    },
                    {
                        "general": {
                            "product_id": "2002",
                            "name": "Hết stock",
                            "url_path": "het-stock.html",
                        },
                        "filterable": {
                            "stock_available_id": 46,
                            "stock": 0,
                            "special_price": 21990000,
                            "price": 22990000,
                        },
                    },
                ]
            }
        }

        detail = {
            "product_id": "1000",
            "price_value": 22990000,
            "category_id": "132",
            "category_ids": ["132", "169"],
        }

        async def _run() -> list[dict]:
            with patch("cps_bot.cps.cps_api._graphql", new_callable=AsyncMock, return_value=gql_payload):
                return await fetch_similar_products(detail, province_id=30, limit=10)

        result = asyncio.run(_run())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "2001")
        self.assertIn("galaxy-a-tuong-tu.html", result[0]["url"])

    def test_unavailable_enrich_strips_sale_data_and_uses_similar(self) -> None:
        payload = {
            "primary_product": {
                "name": "Galaxy hết hàng",
                "price": "22.990.000đ",
                "member_prices": [{"label": "S-Member"}],
                "promotions": {"highlights": ["KM 1"]},
                "promotion_info": "KM",
                "stock_status": "Hết hàng",
                "stock_available_id": 43,
            },
            "shop_stock": {"total_shops_in_province": 3},
        }
        detail = {
            "product_id": "1000",
            "price_value": 22990000,
            "category_id": "132",
            "category_ids": ["132"],
            "stock_available_id": 43,
            "stock_availability": {"is_out_of_stock": True},
        }
        similar = [{"name": "Galaxy khác", "price": "21.990.000đ", "url": "https://cellphones.com.vn/a.html"}]

        async def _run() -> dict[str, bool]:
            with (
                patch("cps_bot.cps.cps_api.fetch_similar_products", new_callable=AsyncMock, return_value=similar),
                patch("cps_bot.cps.cps_api.fetch_trade_promo_for_product", new_callable=AsyncMock) as mock_trade,
                patch("cps_bot.cps.cps_enrich.enrich_extended_scenarios", new_callable=AsyncMock, return_value={}),
            ):
                flags = await _enrich_payload_for_scenarios_inner(
                    payload,
                    detail,
                    user_question="giá máy này",
                    province_id=30,
                )
                mock_trade.assert_not_awaited()
                return flags

        flags = asyncio.run(_run())
        self.assertIn("similar_products", flags)
        self.assertNotIn("member_prices", payload["primary_product"])
        self.assertNotIn("promotions", payload["primary_product"])
        self.assertNotIn("promotion_info", payload["primary_product"])
        self.assertNotIn("shop_stock", payload)
        self.assertEqual(payload["similar_products"], similar)


if __name__ == "__main__":
    unittest.main()
