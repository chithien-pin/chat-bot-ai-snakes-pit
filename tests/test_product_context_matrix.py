"""Ma trận test chuyển SP / danh mục — không pin nhầm ngữ cảnh."""
from __future__ import annotations

import unittest

from cps_bot.browse.product_lines import (
    product_context_conflict,
    product_lines_conflict,
)
from cps_bot.llm.gemini_client import (
    extract_search_keywords,
    identity_compatible_with_session,
    is_contextual_follow_up,
    should_reuse_product_identity,
)


def _ctx(keywords: str, product: str) -> str:
    return (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        f"Sản phẩm đang thảo luận: {product}\n"
        f"Từ khóa tìm gần nhất: {keywords}\n"
    )


# (session_keywords, session_product, new_query, expect_conflict, expect_follow_up)
_SWITCH_CASES: list[tuple[str, str, str, bool, bool]] = [
    # Apple ecosystem
    ("macbook neo", "MacBook Neo 512GB", "mac mini giá như nào?", True, False),
    ("macbook neo", "MacBook Neo", "macbook air giá bao nhiêu", True, False),
    ("macbook neo", "MacBook Neo", "imac giá sao", True, False),
    ("iphone 17", "iPhone 17 256GB", "ipad giá bao nhiêu", True, False),
    ("iphone 17", "iPhone 17", "airpods pro giá", True, False),
    ("iphone 17", "iPhone 17", "apple watch giá", True, False),
    ("iphone 17", "iPhone 17", "macbook neo giá", True, False),
    # Samsung / cross-brand phone
    ("iphone 17", "iPhone 17 256GB", "galaxy s25 giá", True, False),
    ("iphone 17", "iPhone 17", "samsung giá bao nhiêu", True, False),
    ("galaxy s24", "Galaxy S24 Ultra", "iphone 17 giá", True, False),
    ("galaxy s24", "Galaxy S24", "redmi note giá", True, False),
    ("galaxy s24", "Galaxy S24", "xiaomi giá", True, False),
    # Fold vs bar phone
    ("galaxy s24", "Galaxy S24", "z fold giá bao nhiêu", True, False),
    # Laptop brands
    ("iphone 17", "iPhone 17", "laptop asus rog giá", True, False),
    ("iphone 17", "iPhone 17", "dell xps giá", True, False),
    ("asus vivobook", "ASUS Vivobook", "lenovo thinkpad giá", True, False),
    # Category switches
    ("iphone 17", "iPhone 17", "pin dự phòng giá", True, False),
    ("iphone 17", "iPhone 17", "tai nghe sony giá", True, False),
    ("iphone 17", "iPhone 17", "nồi chiên giá bao nhiêu", True, False),
    # Valid follow-ups — NO conflict
    ("iphone 17", "iPhone 17 256GB", "còn hàng không", False, True),
    ("iphone 17", "iPhone 17", "giá sao", False, True),
    ("iphone 17", "iPhone 17", "các màu", False, True),
    ("iphone 17", "iPhone 17", "bản 512gb thì sao", False, True),
    ("macbook neo", "MacBook Neo", "còn màu nào", False, True),
    ("macbook neo", "MacBook Neo", "trả góp thế nào", False, True),
    # In-box accessory question — still follow-up
    ("iphone 17", "iPhone 17", "có kèm tai nghe không", False, True),
    ("iphone 17", "iPhone 17", "tặng kèm gì", False, True),
    # Same line variant — NO conflict
    ("iphone 17", "iPhone 17 256GB", "iphone 17 pro giá", False, False),
]


class ProductContextMatrixTest(unittest.TestCase):
    def test_conflict_matrix(self) -> None:
        for kw, prod, query, expect_conflict, _ in _SWITCH_CASES:
            with self.subTest(query=query, session=kw):
                prior = f"{kw} {prod}"
                self.assertEqual(
                    product_context_conflict(query, prior),
                    expect_conflict,
                    f"conflict({query!r}, {prior!r})",
                )

    def test_follow_up_matrix(self) -> None:
        for kw, prod, query, _, expect_follow_up in _SWITCH_CASES:
            ctx = _ctx(kw, prod)
            with self.subTest(query=query, session=kw):
                self.assertEqual(
                    is_contextual_follow_up(query, ctx),
                    expect_follow_up,
                    f"follow_up({query!r})",
                )

    def test_identity_and_keywords_on_switches(self) -> None:
        switches = [c for c in _SWITCH_CASES if c[3]]
        for kw, prod, query, _, _ in switches:
            ctx = _ctx(kw, prod)
            with self.subTest(query=query):
                self.assertFalse(
                    should_reuse_product_identity(
                        query, ctx, last_keywords=kw, last_product_name=prod
                    )
                )
                self.assertFalse(
                    identity_compatible_with_session(
                        query, last_keywords=kw, last_product_name=prod
                    )
                )
                extracted = extract_search_keywords(query, ctx, use_llm=False)
                self.assertNotEqual(
                    extracted.lower().strip(),
                    kw.lower().strip(),
                    f"keyword reused: {extracted!r}",
                )

    def test_llm_swap_rejected_iphone_to_galaxy(self) -> None:
        from unittest.mock import patch

        ctx = _ctx("iphone 17 256gb", "iPhone 17 256GB")
        with patch(
            "cps_bot.llm.gemini_client._generate_with_fallback",
            return_value="iPhone 17 256GB",
        ):
            kw = extract_search_keywords("galaxy s25 giá", ctx, use_llm=True)
        self.assertIn("galaxy", kw.lower())
        self.assertNotIn("iphone", kw.lower())


if __name__ == "__main__":
    unittest.main()
