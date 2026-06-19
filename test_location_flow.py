"""Tests — hỏi tỉnh trước khi tra cửa hàng."""
from __future__ import annotations

from cps_api import classify_question_scenarios
from location_flow import (
    build_ask_province_reply,
    handle_province_gate,
    is_province_meta_complaint,
    requires_province_before_shop_query,
)


def test_near_me_requires_province():
    assert requires_province_before_shop_query("cửa hàng gần tôi")
    assert requires_province_before_shop_query("shop gần mình còn hàng không")
    assert not requires_province_before_shop_query(
        "cửa hàng gần tôi", session_province_id=30
    )
    assert not requires_province_before_shop_query("shop quận 1 còn iPhone không")
    assert not requires_province_before_shop_query("cửa hàng ở Hà Nội")


def test_store_locator_requires_province():
    assert requires_province_before_shop_query("danh sách shop")


def test_gate_asks_before_query():
    session: dict = {}
    result = handle_province_gate("cửa hàng gần tôi", session)
    assert result.should_ask
    assert result.pending_kind == "shop_stock"
    assert session.get("pending_shop_question") == "cửa hàng gần tôi"


def test_gate_resumes_after_province_answer():
    session = {
        "pending_province_for": "shop_stock",
        "pending_shop_question": "cửa hàng gần tôi",
    }
    result = handle_province_gate("Hà Nội", session)
    assert not result.should_ask
    assert result.province_id == 24
    assert session.get("resume_shop_stock")
    assert "pending_province_for" not in session


def test_meta_complaint_asks_province():
    assert is_province_meta_complaint(
        "sao bạn không hỏi tôi đang ở đâu?",
        has_product_context=True,
    )
    session: dict = {}
    result = handle_province_gate(
        "sao bạn không hỏi tôi đang ở đâu?",
        session,
        has_product_context=True,
    )
    assert result.should_ask


def test_reviews_scenario_not_triggered_by_sao_complaint():
  scenarios = classify_question_scenarios("sao bạn không hỏi tôi đang ở đâu?")
  assert not scenarios.get("reviews")


def test_ask_reply_not_empty():
    assert "tỉnh" in build_ask_province_reply().lower()


if __name__ == "__main__":
    test_near_me_requires_province()
    test_store_locator_requires_province()
    test_gate_asks_before_query()
    test_gate_resumes_after_province_answer()
    test_meta_complaint_asks_province()
    test_reviews_scenario_not_triggered_by_sao_complaint()
    test_ask_reply_not_empty()
    print("OK — location flow tests passed")
