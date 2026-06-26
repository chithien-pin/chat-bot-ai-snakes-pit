"""Test fast reply màu sibling + slim payload giữ color_sibling_variants."""
from __future__ import annotations

import asyncio
import unittest

from cps_bot.browse.fast_reply import (
    build_color_sibling_reply,
    can_fast_color_sibling_reply,
    slim_payload_for_llm,
)
from cps_bot.core.conversation import append_turn, format_context_block, get_session
from cps_bot.cps.cps_api import enrich_payload_for_scenarios, fetch_product_for_query
from cps_bot.cps.scraper import build_product_payload
from cps_bot.llm.gemini_client import extract_search_keywords


class ColorSiblingReplyTest(unittest.TestCase):
    def test_slim_payload_keeps_color_siblings(self) -> None:
        payload = {
            "primary_product": {"name": "iPhone 16 128GB", "product_id": "90126"},
            "search_results": [{"name": "x", "price": "1"}],
            "color_sibling_variants": {
                "count": 5,
                "current_product_id": "90126",
                "parent_product_id": "59254",
                "variants": [
                    {"product_id": "90126", "name": "iPhone 16-Xanh Lưu Ly", "price": "20tr", "stock_status": "Còn hàng"},
                    {"product_id": "90122", "name": "iPhone 16-Đen", "price": "20tr", "stock_status": "Còn hàng"},
                ],
            },
        }
        slim = slim_payload_for_llm(payload)
        self.assertIn("color_sibling_variants", slim)
        self.assertEqual(slim["color_sibling_variants"]["count"], 5)

    def test_fast_color_reply_lists_all_colors(self) -> None:
        payload = {
            "primary_product": {"name": "iPhone 16 128GB | Chính hãng VN/A-Xanh Lưu Ly"},
            "color_sibling_variants": {
                "count": 3,
                "current_product_id": "90126",
                "variants": [
                    {"product_id": "90126", "name": "iPhone 16 128GB | VN/A-Xanh Lưu Ly", "price": "20.490.000₫", "stock_status": "Còn hàng"},
                    {"product_id": "90122", "name": "iPhone 16 128GB | VN/A-Đen", "price": "20.490.000₫", "stock_status": "Còn hàng"},
                    {"product_id": "90124", "name": "iPhone 16 128GB | VN/A-Hồng", "price": "20.490.000₫", "stock_status": "Hết hàng"},
                ],
            },
        }
        self.assertTrue(can_fast_color_sibling_reply(payload, "có màu nào khác không?"))
        answer = build_color_sibling_reply("có màu nào khác không?", payload)
        self.assertIn("Xanh Lưu Ly", answer)
        self.assertIn("Đen", answer)
        self.assertIn("Hồng", answer)
        self.assertIn("màu bạn đang xem", answer)


class ColorSiblingE2ETest(unittest.TestCase):
    def test_ip16_xanh_luu_ly_then_other_colors(self) -> None:
        async def _run() -> str:
            q1 = "ip16 xanh lưu ly giá bao nhiêu?"
            q2 = "có màu nào khác không?"
            kw1 = extract_search_keywords(q1, use_llm=False)
            _, d1, _ = await fetch_product_for_query(kw1, user_message=q1)
            self.assertEqual(str(d1.get("product_id")), "90126")

            store: dict = {}
            session = get_session(store, "chat", "user")
            append_turn(
                session,
                user=q1,
                assistant="giá",
                keywords=kw1,
                product_name=d1.get("name") or "",
                product_url=d1.get("url") or "",
                product_id=d1.get("product_id") or "",
                parent_product_id=d1.get("parent_id") or "",
            )
            lp = session["last_product"]
            ctx = format_context_block(session)
            kw2 = extract_search_keywords(q2, ctx, use_llm=False)

            _, d2, stats = await fetch_product_for_query(
                kw2,
                user_message=q2,
                fallback_url=lp.get("url") or "",
                fallback_product_id=lp.get("product_id") or "",
                session_fallback_parent_id=lp.get("parent_id") or "",
                session_last_keywords=session["last_keywords"],
                session_last_product_name=lp.get("name") or "",
            )
            self.assertEqual(stats.get("resolve_source"), "session_color_list_context")

            payload = build_product_payload([], d2)
            await enrich_payload_for_scenarios(payload, d2, user_question=q2)
            self.assertTrue(can_fast_color_sibling_reply(payload, q2))

            slim = slim_payload_for_llm(payload)
            self.assertIn("color_sibling_variants", slim)
            return build_color_sibling_reply(q2, payload)

        answer = asyncio.run(_run())
        for color in ("Xanh Lưu Ly", "Đen", "Hồng", "Trắng", "Xanh Mòng Két"):
            self.assertIn(color, answer, answer)

    def test_ip17_pro_1tb_then_color_list(self) -> None:
        async def _run() -> str:
            q1 = "iphone 17 pro 1tb bạc giá bao nhiêu"
            q2 = "các màu của ip17 pro"
            kw1 = extract_search_keywords(q1, use_llm=False)
            _, d1, _ = await fetch_product_for_query(kw1, user_message=q1)
            self.assertEqual(str(d1.get("product_id")), "112606")

            store: dict = {}
            session = get_session(store, "chat", "user")
            append_turn(
                session,
                user=q1,
                assistant="giá",
                keywords=kw1,
                product_name=d1.get("name") or "",
                product_url=d1.get("url") or "",
                product_id=d1.get("product_id") or "",
                parent_product_id=d1.get("parent_id") or "",
            )
            lp = session["last_product"]
            ctx = format_context_block(session)
            kw2 = extract_search_keywords(q2, ctx, use_llm=False)

            _, d2, stats = await fetch_product_for_query(
                kw2,
                user_message=q2,
                fallback_url=lp.get("url") or "",
                fallback_product_id=lp.get("product_id") or "",
                session_fallback_parent_id=lp.get("parent_id") or "",
                session_last_keywords=session["last_keywords"],
                session_last_product_name=lp.get("name") or "",
            )
            self.assertEqual(stats.get("resolve_source"), "session_color_list_context")

            payload = build_product_payload([], d2)
            await enrich_payload_for_scenarios(payload, d2, user_question=q2)
            self.assertTrue(can_fast_color_sibling_reply(payload, q2))
            return build_color_sibling_reply(q2, payload)

        answer = asyncio.run(_run())
        for color in ("Bạc", "Cam Vũ Trụ", "Xanh Đậm"):
            self.assertIn(color, answer, answer)


if __name__ == "__main__":
    unittest.main()
