"""Test nhận diện tìm SP theo stock status (company_stock_id)."""
from __future__ import annotations

from cps_bot.cps.cps_api import (
    STOCK_AVAILABLE_IN_STOCK,
    STOCK_AVAILABLE_PRE_ORDER,
    STOCK_AVAILABLE_SUBSCRIPTION,
    is_stock_status_browse_query,
    resolve_stock_filter_ids,
)


def test_pre_order_browse() -> None:
    q = "iPhone 17 Pro Max đặt trước"
    assert resolve_stock_filter_ids(q) == [STOCK_AVAILABLE_PRE_ORDER]
    assert is_stock_status_browse_query(q)


def test_pre_order_english() -> None:
    q = "samsung s25 pre-order"
    assert STOCK_AVAILABLE_PRE_ORDER in resolve_stock_filter_ids(q)
    assert is_stock_status_browse_query(q)


def test_subscription_browse() -> None:
    q = "điện thoại đăng ký nhận tin"
    assert resolve_stock_filter_ids(q) == [STOCK_AVAILABLE_SUBSCRIPTION]
    assert is_stock_status_browse_query(q)


def test_status_check_not_browse() -> None:
    q = "iPhone 17 Pro Max còn hàng không?"
    assert resolve_stock_filter_ids(q) == []
    assert not is_stock_status_browse_query(q)


def test_list_in_stock_browse() -> None:
    q = "danh sách sản phẩm còn hàng laptop gaming"
    assert resolve_stock_filter_ids(q) == [STOCK_AVAILABLE_IN_STOCK]
    assert is_stock_status_browse_query(q)


def test_subscription_list_browse_keywords() -> None:
    from cps_bot.llm.gemini_client import extract_search_keywords

    q = "các sản phẩm đăng ký nhận tin"
    assert resolve_stock_filter_ids(q) == [STOCK_AVAILABLE_SUBSCRIPTION]
    assert is_stock_status_browse_query(q)
    assert extract_search_keywords(q) == ""


def test_stock_browse_list_mode_summary() -> None:
    from cps_bot.cps.cps_api import _build_stock_browse_summary

    results = [
        {"name": "SP A", "price": "10.000.000₫", "url": "https://cellphones.com.vn/a.html"},
        {"name": "SP B", "price": "20.000.000₫", "url": "https://cellphones.com.vn/b.html"},
    ]
    detail = _build_stock_browse_summary([STOCK_AVAILABLE_SUBSCRIPTION], results, 30)
    assert detail.get("stock_browse_list_mode") is True
    assert detail.get("product_count") == 2
    assert not detail.get("product_id")


def test_strip_subscription_with_product_name() -> None:
    from cps_bot.cps.cps_api import strip_stock_browse_phrases_for_keywords

    assert strip_stock_browse_phrases_for_keywords("iPhone 17 Pro Max đăng ký nhận tin") == (
        "iPhone 17 Pro Max"
    )


if __name__ == "__main__":
    test_pre_order_browse()
    test_pre_order_english()
    test_subscription_browse()
    test_status_check_not_browse()
    test_list_in_stock_browse()
    test_subscription_list_browse_keywords()
    test_stock_browse_list_mode_summary()
    test_strip_subscription_with_product_name()
    print("OK — stock browse tests passed")
