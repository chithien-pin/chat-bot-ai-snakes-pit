"""Test song song hoá enrich payload — nhiều scenario cùng lúc."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cps_bot.cps.cps_api import _enrich_payload_for_scenarios_inner


class EnrichParallelTest(unittest.TestCase):
    def test_multiple_scenarios_fetched_in_parallel(self) -> None:
        payload: dict = {"primary_product": {"name": "iPhone 16", "product_id": "100"}}
        detail = {"product_id": "100", "stock_available_id": 46}
        trade_data = {"promo_value": 1000000}
        warranty_data = {"warranty_packs": []}
        installment_data = {"available": True}

        async def _run() -> dict[str, bool]:
            with (
                patch(
                    "cps_bot.cps.cps_api.fetch_trade_promo_for_product",
                    new_callable=AsyncMock,
                    return_value=trade_data,
                ) as mock_trade,
                patch(
                    "cps_bot.cps.cps_api.fetch_extended_warranty_for_product",
                    new_callable=AsyncMock,
                    return_value=warranty_data,
                ) as mock_warranty,
                patch(
                    "cps_bot.cps.cps_installment.fetch_installment_context",
                    new_callable=AsyncMock,
                    return_value=installment_data,
                ) as mock_installment,
                patch(
                    "cps_bot.cps.cps_enrich.enrich_extended_scenarios",
                    new_callable=AsyncMock,
                    return_value={},
                ),
            ):
                flags = await _enrich_payload_for_scenarios_inner(
                    payload,
                    detail,
                    user_question="giá và trả góp iPhone 16, gói bảo hành thêm",
                    province_id=30,
                )
                mock_trade.assert_awaited_once()
                mock_warranty.assert_awaited_once()
                mock_installment.assert_awaited_once()
                return flags

        flags = asyncio.run(_run())
        self.assertTrue(flags.get("trade_promo"))
        self.assertTrue(flags.get("extended_warranty"))
        self.assertTrue(flags.get("installment"))
        self.assertEqual(payload["trade_promo"], trade_data)
        self.assertEqual(payload["extended_warranty"], warranty_data)
        self.assertEqual(payload["installment"], installment_data)


if __name__ == "__main__":
    unittest.main()
