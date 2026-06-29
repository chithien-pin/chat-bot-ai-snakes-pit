"""Test gợi ý sản phẩm mua cùng (recommendation API)."""
from __future__ import annotations

import asyncio
import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from cps_bot.cps.cps_api import (
    _recommendation_product_id,
    fetch_recommended_products,
)


class RecommendedProductsTest(unittest.TestCase):
    def test_recommendation_product_id_prefers_parent(self) -> None:
        detail = {
            "product_id": "112598",
            "parent_id": "112580",
            "default_product_id": "112595",
        }
        self.assertEqual(_recommendation_product_id(detail), "112580")

    def test_fetch_recommended_products_maps_graphql(self) -> None:
        api_body = {
            "data": [
                {"product_id": 113166, "source": "auto"},
                {"product_id": 112945, "source": "auto"},
            ],
            "message": "ok",
        }
        gql_products = [
            {
                "general": {
                    "product_id": 113166,
                    "name": "Ốp lưng iPhone 17",
                    "url_path": "op-lung-iphone-17.html",
                },
                "filterable": {
                    "special_price": 199000,
                    "price": 299000,
                    "stock_available_id": 46,
                },
            },
            {
                "general": {
                    "product_id": 112945,
                    "name": "Cường lực iPhone 17",
                    "url_path": "cuong-luc-iphone-17.html",
                },
                "filterable": {
                    "special_price": 99000,
                    "price": 150000,
                    "stock_available_id": 46,
                },
            },
        ]

        async def _run() -> list[dict[str, Any]]:
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json = lambda: api_body

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            with (
                patch("cps_bot.cps.cps_api.httpx.AsyncClient", return_value=mock_client),
                patch(
                    "cps_bot.cps.cps_api.get_products_by_ids",
                    new_callable=AsyncMock,
                    return_value=gql_products,
                ) as mock_gql,
            ):
                result = await fetch_recommended_products(
                    "112580", province_id=30, max_products=2
                )
                mock_gql.assert_awaited_once_with([113166, 112945], province_id=30)
                return result

        records = asyncio.run(_run())
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["name"], "Ốp lưng iPhone 17")
        self.assertTrue(records[0]["price"])
        self.assertIn("op-lung-iphone-17.html", records[0]["url"])
        self.assertEqual(records[1]["name"], "Cường lực iPhone 17")


if __name__ == "__main__":
    unittest.main()
