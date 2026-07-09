"""Ma trận kịch bản hỏi tồn kho — cửa hàng / quận / tỉnh / online."""
from __future__ import annotations

import unittest

from cps_bot.cps.cps_api import (
    classify_question_scenarios,
    extract_location_hint,
    is_district_stock_query,
    is_province_stock_query,
    is_stock_availability_query,
    should_attach_shop_stock,
)
from cps_bot.cps.cps_provinces import resolve_province_from_text


# (query, expect_attach, expect_district, expect_location_substr | None)
_STOCK_ATTACH_CASES: list[tuple[str, bool, bool, str | None]] = [
    # --- Quận / Q abbrev ---
    ("s26 ultra đen có hàng ở q5 không", True, True, "quận 5"),
    ("ở q5 có không", True, True, "quận 5"),
    ("quận 5 còn không", True, True, "quận 5"),
    ("Q10 còn hàng không", True, True, "quận 10"),
    ("q10 có hàng ko", True, True, "quận 10"),
    ("Q.7 còn hàng không", True, True, "quận 7"),
    ("còn hàng quận 7 không", True, True, "quận 7"),
    ("màu đen còn hàng q5 không", True, True, "quận 5"),
    ("tồn kho tại quận 3", True, True, "quận 3"),
    ("kiểm tra tồn q1", True, True, "quận 1"),
    ("Q10 có tồn Galaxy A17", True, True, "quận 10"),
    ("ở quận 10 có không?", True, True, "quận 10"),
    ("gần quận 9 còn hàng không", True, True, "quận 9"),
    # --- Shop + quận ---
    ("shop quận 1 còn iphone không", True, True, "quận 1"),
    ("Shop gần quận 1 còn Samsung S26 Ultra không?", True, True, "quận 1"),
    ("cửa hàng gần quận 9 còn không", True, True, "quận 9"),
    ("còn hàng Samsung S24 ở shop quận 9 không?", True, True, "quận 9"),
    ("shop q3 còn macbook không", True, True, "quận 3"),
    # --- Cửa hàng / chi nhánh chung ---
    ("ở đâu còn hàng", True, False, None),
    ("shop nào còn hàng?", True, False, None),
    ("shop nào còn", True, False, None),
    ("chi nhánh nào còn hàng", True, False, None),
    ("cửa hàng gần tôi còn iPhone 16 Pro Max không", True, False, None),
    ("mua ở đâu còn hàng", True, False, None),
    ("hàng ở đâu", True, False, None),
    ("xem chi nhánh còn hàng", True, False, None),
    ("nhận tại shop còn không", True, False, None),
    # --- Tồn online / trạng thái ---
    ("iPhone 16 Pro còn hàng không?", True, False, None),
    ("còn hàng không", True, False, None),
    ("hết hàng chưa", True, False, None),
    ("còn máy không", True, False, None),
    ("còn bán không", True, False, None),
    ("mua được không", True, False, None),
    ("check tồn s26 ultra", True, False, None),
    ("tình trạng hàng iphone 17", True, False, None),
    ("còn ko", True, False, None),
    ("còn k", True, False, None),
    # --- Tỉnh / thành phố ---
    ("Có hàng ở Bình Phước ko?", True, False, None),
    ("HCM còn hàng không", True, False, None),
    ("Sài Gòn còn hàng không", True, False, None),
    ("Hà Nội còn không", True, False, None),
    ("còn hàng ở Đà Nẵng không", True, False, None),
    # --- Follow-up (reuse context) ---
    ("ở quận 10 có không?", True, True, "quận 10"),
    ("quận 5 còn không", True, True, "quận 5"),
    # --- KHÔNG phải hỏi tồn ---
    ("giá iphone 17 bao nhiêu", False, False, None),
    ("thông số s26 ultra", False, False, None),
    ("so sánh s26 và s25", False, False, None),
    ("trả góp thế nào", False, False, None),
    ("bảo hành bao lâu", False, False, None),
    ("các màu của iphone 17", False, False, None),
]

# Province resolution for stock queries
_PROVINCE_STOCK_CASES: list[tuple[str, int | None]] = [
    ("HCM còn hàng không", 30),
    ("Sài Gòn còn hàng không", 30),
    ("Hà Nội còn không", 24),
    ("Có hàng ở Bình Phước ko?", 10),
    ("còn hàng ở Đà Nẵng không", 15),
    ("giá iphone 17", None),
]


class ShopStockScenarioMatrixTest(unittest.TestCase):
    def test_should_attach_matrix(self) -> None:
        for query, expect_attach, expect_district, loc_sub in _STOCK_ATTACH_CASES:
            with self.subTest(query=query):
                self.assertEqual(
                    should_attach_shop_stock(query),
                    expect_attach,
                    f"should_attach_shop_stock({query!r})",
                )
                self.assertEqual(
                    is_stock_availability_query(query),
                    expect_attach,
                    f"is_stock_availability_query({query!r})",
                )
                self.assertEqual(
                    classify_question_scenarios(query)["shop_stock"],
                    expect_attach,
                    f"shop_stock scenario({query!r})",
                )
                if expect_district:
                    self.assertTrue(
                        is_district_stock_query(query),
                        f"is_district_stock_query({query!r})",
                    )
                if loc_sub:
                    hint = extract_location_hint(query).lower()
                    self.assertIn(loc_sub, hint, f"location_hint({query!r})={hint!r}")

    def test_follow_up_with_context(self) -> None:
        follow_ups = (
            "ở quận 10 có không?",
            "quận 5 còn không",
            "còn hàng không",
            "còn ko",
        )
        for q in follow_ups:
            with self.subTest(query=q):
                self.assertTrue(
                    should_attach_shop_stock(q, reuse_product_context=True),
                    q,
                )

    def test_province_stock_resolution(self) -> None:
        for query, expect_pid in _PROVINCE_STOCK_CASES:
            with self.subTest(query=query):
                pid = resolve_province_from_text(query)
                self.assertEqual(pid, expect_pid)
                if expect_pid is not None:
                    self.assertTrue(is_province_stock_query(query), query)


if __name__ == "__main__":
    unittest.main()
