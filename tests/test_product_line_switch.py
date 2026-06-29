"""Test chuyển SP trong hội thoại (MacBook Neo → Mac mini)."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from cps_bot.browse.product_lines import (
    extract_product_lines,
    mentions_product_line,
    product_lines_conflict,
)
from cps_bot.browse.product_map import clear_product_map_cache, resolve_product_from_map
from cps_bot.cps.cps_api import fetch_product_for_query
from cps_bot.llm.gemini_client import (
    extract_search_keywords,
    identity_compatible_with_session,
    is_contextual_follow_up,
    should_reuse_product_identity,
)


def _macbook_neo_ctx() -> str:
    return (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        "Sản phẩm đang thảo luận: MacBook Neo 13 inch 512GB\n"
        "Từ khóa tìm gần nhất: macbook neo 512gb\n"
        "Khách: giá macbook neo\n"
        "Bot: Giá MacBook Neo ..."
    )


class ProductLineDetectionTest(unittest.TestCase):
    def test_extract_macbook_neo_and_mac_mini(self) -> None:
        self.assertIn("macbook_neo", extract_product_lines("macbook neo giá"))
        self.assertIn("mac_mini", extract_product_lines("mac mini giá như nào"))
        self.assertTrue(product_lines_conflict("mac mini giá sao", "macbook neo 512gb"))

    def test_color_follow_up_no_conflict(self) -> None:
        self.assertFalse(product_lines_conflict("còn màu nào", "macbook neo"))
        self.assertFalse(product_lines_conflict("giá sao", "macbook neo"))


class MacMiniAfterMacbookNeoTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = _macbook_neo_ctx()

    def test_mentions_new_product_mac_mini(self) -> None:
        self.assertTrue(mentions_product_line("mac mini giá như nào?"))

    def test_not_contextual_follow_up_after_line_switch(self) -> None:
        self.assertFalse(is_contextual_follow_up("mac mini giá như nào?", self.ctx))

    def test_should_not_reuse_identity(self) -> None:
        self.assertFalse(
            should_reuse_product_identity(
                "mac mini giá như nào?",
                self.ctx,
                last_keywords="macbook neo 512gb",
                last_product_name="MacBook Neo 13 inch 512GB",
            )
        )

    def test_identity_not_compatible(self) -> None:
        self.assertFalse(
            identity_compatible_with_session(
                "mac mini giá như nào?",
                last_keywords="macbook neo 512gb",
                last_product_name="MacBook Neo 13 inch 512GB",
            )
        )

    def test_keywords_not_reuse_macbook_neo(self) -> None:
        kw = extract_search_keywords("mac mini giá như nào?", self.ctx, use_llm=False)
        self.assertIn("mini", kw.lower())
        self.assertNotIn("neo", kw.lower())

    def test_keywords_reject_llm_context_swap(self) -> None:
        with patch(
            "cps_bot.llm.gemini_client._generate_with_fallback",
            return_value="macbook neo 512gb",
        ):
            kw = extract_search_keywords("mac mini giá như nào?", self.ctx, use_llm=True)
        self.assertIn("mini", kw.lower())
        self.assertNotIn("neo", kw.lower())

    @unittest.skipUnless(
        __import__("pathlib").Path(__import__("config").PRODUCT_MAP_PATH).is_file(),
        "product_map.txt missing",
    )
    def test_map_resolves_mac_mini(self) -> None:
        clear_product_map_cache()
        hit = resolve_product_from_map("mac mini")
        self.assertIsNotNone(hit)
        self.assertIn("Mac mini", hit.name)


class FetchAfterTopicSwitchTest(unittest.TestCase):
    def test_fetch_mac_mini_not_macbook_neo(self) -> None:
        async def _run() -> tuple[str, str, str]:
            _results, detail, stats = await fetch_product_for_query(
                "mac mini",
                user_message="mac mini giá như nào?",
                fallback_url="https://cellphones.com.vn/macbook-neo.html",
                fallback_product_id="125879",
                session_last_keywords="macbook neo 512gb",
                session_last_product_name="MacBook Neo 13 inch 512GB",
            )
            return (
                str(stats.get("resolve_source") or ""),
                str(detail.get("name") or ""),
                str(detail.get("product_id") or ""),
            )

        try:
            source, name, pid = asyncio.run(_run())
        except Exception as exc:
            if exc.__class__.__module__.startswith("httpx"):
                self.skipTest(f"CPS API unavailable: {exc}")
            raise
        self.assertNotEqual(source, "session_fallback_product_id")
        self.assertIn("Mac mini", name)
        self.assertNotIn("MacBook Neo", name)
        self.assertNotEqual(pid, "125879")


if __name__ == "__main__":
    unittest.main()
