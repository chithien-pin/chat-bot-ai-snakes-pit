"""Ma trận test resolve SP — keyword, màu, map, search pick, (tùy chọn) API."""
from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path

from cps_bot.cps.cps_api import _extract_variant_hints, _pick_best_search_result, fetch_product_for_query
from cps_bot.browse.product_map import clear_product_map_cache, resolve_product_from_map
from cps_bot.llm.gemini_client import extract_search_keywords
from tests.product_resolution_cases import (
    COLOR_HINT_CASES,
    INTEGRATION_CASES,
    KEYWORD_CASES,
    REAL_MAP_CASES,
    SEARCH_PICK_CASES,
)

_INTEGRATION = os.getenv("PRODUCT_RESOLUTION_INTEGRATION", "").strip() in {"1", "true", "yes"}
_HAS_MAP = Path(__file__).resolve().parents[1].joinpath("data", "product_map.txt").is_file()


class ProductResolutionMatrixTest(unittest.TestCase):
    def test_keyword_normalize_matrix(self) -> None:
        for case in KEYWORD_CASES:
            with self.subTest(case.id):
                kw = extract_search_keywords(case.query, use_llm=False)
                self.assertEqual(kw, case.expected)

    def test_color_hint_matrix(self) -> None:
        for case in COLOR_HINT_CASES:
            with self.subTest(case.id):
                hints = _extract_variant_hints(case.text)
                self.assertIn(case.want, hints, hints)
                for bad in case.avoid:
                    self.assertNotIn(bad, hints)

    def test_search_pick_matrix(self) -> None:
        base_results = [
            {"name": "Điện thoại iPhone 16 Pro Max 256GB", "url_path": "iphone-16-pro-max-256gb.html"},
            {"name": "iPhone 16 Pro 256GB", "url_path": "iphone-16-pro-256gb.html"},
            {"name": "iPhone 16 Plus 128GB | Chính hãng VN/A", "url_path": "iphone-16-plus-128gb.html"},
            {"name": "iPhone 16 128GB | Chính hãng VN/A", "url_path": "iphone-16-128gb.html"},
            {"name": "iPhone 16 256GB | Chính hãng VN/A", "url_path": "iphone-16-256gb.html"},
        ]
        promax_results = [
            {"name": "iPhone 16 Pro Max 256GB | Chính hãng VN/A", "url_path": "iphone-16-pro-max-256gb.html"},
            {"name": "iPhone 16 256GB | Chính hãng VN/A", "url_path": "iphone-16-256gb.html"},
        ]
        for case in SEARCH_PICK_CASES:
            with self.subTest(case.id):
                results = promax_results if "pro max" in case.keywords.lower() else base_results
                best = _pick_best_search_result(results, case.keywords)
                self.assertIsNotNone(best)
                assert best is not None
                self.assertIn(case.want_substr, best["name"])
                for bad in case.avoid_substr:
                    self.assertNotIn(bad, best["name"])

    @unittest.skipUnless(_HAS_MAP, "product_map.txt missing")
    def test_real_map_matrix(self) -> None:
        for case in REAL_MAP_CASES:
            with self.subTest(case.id):
                clear_product_map_cache()
                hit = resolve_product_from_map(case.keywords)
                self.assertIsNotNone(hit, case.keywords)
                assert hit is not None
                self.assertEqual(hit.product_id, case.product_id)
                if case.name_contains:
                    self.assertIn(case.name_contains, hit.name)


class ProductResolutionIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(_INTEGRATION, "set PRODUCT_RESOLUTION_INTEGRATION=1")
    def test_integration_resolve_matrix(self) -> None:
        for case in INTEGRATION_CASES:
            with self.subTest(case.id):
                kw = extract_search_keywords(case.query, use_llm=False)

                async def _run() -> str:
                    _, detail, _ = await fetch_product_for_query(kw, user_message=case.query)
                    return str(detail.get("product_id") or "")

                product_id = asyncio.run(_run())
                self.assertEqual(product_id, case.expected)


if __name__ == "__main__":
    unittest.main()
