"""Test phân loại kịch bản câu hỏi."""
from __future__ import annotations

from cps_api import classify_question_scenarios


def test_reviews_scenario() -> None:
    s = classify_question_scenarios("iPhone 16 review sao?")
    assert s["reviews"]


def test_faq_scenario() -> None:
    s = classify_question_scenarios("chính sách đổi trả thế nào")
    assert s["faq_policy"]


def test_flash_sale_scenario() -> None:
    s = classify_question_scenarios("flash sale hôm nay")
    assert s["flash_sale"]


def test_store_locator_scenario() -> None:
    s = classify_question_scenarios("cửa hàng ở Bình Dương")
    assert s["store_locator"]


def test_combo_scenario() -> None:
    s = classify_question_scenarios("mua kèm giảm bao nhiêu")
    assert s["combo"]


if __name__ == "__main__":
    test_reviews_scenario()
    test_faq_scenario()
    test_flash_sale_scenario()
    test_store_locator_scenario()
    test_combo_scenario()
    print("OK — scenario classify tests passed")
