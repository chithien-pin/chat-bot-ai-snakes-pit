"""Test MacBook Neo + confidence threshold product map."""
from __future__ import annotations

import unittest

import config
from cps_bot.browse.product_map import (
    clear_product_map_cache,
    compute_map_match_confidence,
    resolve_product_from_map,
)


class MacbookNeoMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.has_map = __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file()

    def setUp(self) -> None:
        clear_product_map_cache()

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.map missing",
    )
    def test_macbook_neo_not_iphone(self) -> None:
        hit = resolve_product_from_map("macbook neo hồng 512g")
        self.assertIsNotNone(hit, "phải resolve MacBook Neo từ map")
        self.assertIn("MacBook Neo", hit.name)
        self.assertEqual(hit.product_id, "125879")
        self.assertGreaterEqual(hit.confidence, config.PRODUCT_MAP_MIN_CONFIDENCE)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.map missing",
    )
    def test_iphone_map_confidence_rejects_wrong_brand(self) -> None:
        conf = compute_map_match_confidence(
            "macbook neo hồng 512g",
            "iPhone 17 512GB | Chính hãng",
        )
        self.assertEqual(conf, 0.0)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.map missing",
    )
    def test_macbook_neo_confidence_high(self) -> None:
        conf = compute_map_match_confidence(
            "macbook neo hồng 512g",
            "MacBook Neo 13 inch A18 Pro 2026 6CPU 5GPU 8GB 512GB Touch ID | Chính hãng Apple Việt Nam",
        )
        self.assertGreaterEqual(conf, 0.6)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.map missing",
    )
    def test_macbook_air_m2_rejects_accessory_hit(self) -> None:
        conf = compute_map_match_confidence(
            "MacBook Air M2",
            "Dán màn hình MacBook Air M2 2022 13 inch Mocoll",
        )
        self.assertEqual(conf, 0.0)

        hit = resolve_product_from_map("MacBook Air M2")
        self.assertIsNotNone(hit, "phải resolve được MacBook Air M2 thật")
        self.assertIn("macbook air m2", hit.name.lower())
        self.assertNotIn("Dán", hit.name)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.map missing",
    )
    def test_iphone_16_still_resolves(self) -> None:
        hit = resolve_product_from_map("iphone 16 hồng 256g")
        self.assertIsNotNone(hit)
        self.assertEqual(hit.product_id, "90112")
        self.assertGreaterEqual(hit.confidence, config.PRODUCT_MAP_MIN_CONFIDENCE)


if __name__ == "__main__":
    unittest.main()
