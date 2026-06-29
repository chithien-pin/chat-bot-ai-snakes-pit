"""MacBook Pro M5 — chip M5 + kích thước inch, không nhầm 2022 / phụ kiện."""
from __future__ import annotations

import unittest

import config
from cps_bot.browse.product_map import (
    clear_product_map_cache,
    compute_map_match_confidence,
    resolve_product_from_map,
)


class MacbookProM5MapTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_product_map_cache()

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_macbook_pro_m5_base(self) -> None:
        hit = resolve_product_from_map("macbook pro m5")
        self.assertIsNotNone(hit)
        self.assertIn("M5", hit.name)
        self.assertIn("MacBook Pro", hit.name)
        self.assertNotIn("2022", hit.name)
        self.assertGreaterEqual(hit.confidence, config.PRODUCT_MAP_MIN_CONFIDENCE)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_macbook_pro_16_m5_not_2022(self) -> None:
        hit = resolve_product_from_map("MacBook Pro 16 M5")
        self.assertIsNotNone(hit)
        self.assertIn("M5", hit.name)
        self.assertIn("16", hit.name)
        self.assertNotEqual(hit.product_id, "54104")
        self.assertNotIn("2022", hit.name)
        self.assertIn(hit.product_id, {"125741", "125747"})

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_macbook_pro_16_m4_not_accessory(self) -> None:
        hit = resolve_product_from_map("MacBook Pro 16 M4")
        self.assertIsNotNone(hit)
        self.assertNotIn("Innostyle", hit.name)
        self.assertNotIn("dán", hit.name.lower())

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_confidence_rejects_m5_vs_2022(self) -> None:
        conf = compute_map_match_confidence(
            "MacBook Pro 16 M5",
            "Macbook Pro 16 2022",
        )
        self.assertLess(conf, config.PRODUCT_MAP_MIN_CONFIDENCE)

    @unittest.skipUnless(
        __import__("pathlib").Path(config.PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_16inch_follow_up_from_14_m5_context(self) -> None:
        from cps_bot.cps.cps_api import (
            merge_follow_up_variant_into_keywords,
            screen_size_conflicts_with_session,
        )
        from cps_bot.llm.gemini_client import (
            extract_search_keywords,
            identity_compatible_with_session,
            should_reuse_product_identity,
        )

        ctx = (
            "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
            "Sản phẩm đang thảo luận: MacBook Pro 14 M5 16GB/512GB\n"
            "Từ khóa tìm gần nhất: MacBook Pro M5\n"
        )
        q = "có bản 16inch không?"
        merged = merge_follow_up_variant_into_keywords("MacBook Pro M5", q)
        self.assertIn("16", merged)
        self.assertTrue(
            screen_size_conflicts_with_session(
                q,
                last_keywords="MacBook Pro M5",
                last_product_name="MacBook Pro 14 M5",
            )
        )
        self.assertFalse(
            should_reuse_product_identity(
                q, ctx, last_keywords="MacBook Pro M5", last_product_name="MacBook Pro 14 M5"
            )
        )
        self.assertFalse(
            identity_compatible_with_session(
                q, last_keywords="MacBook Pro M5", last_product_name="MacBook Pro 14 M5"
            )
        )
        kw = extract_search_keywords(q, ctx, use_llm=False)
        hit = resolve_product_from_map(kw)
        self.assertIsNotNone(hit)
        self.assertIn("16", hit.name)
        self.assertIn("M5", hit.name)
        self.assertNotIn("2022", hit.name)


if __name__ == "__main__":
    unittest.main()
