"""Test parse_stock_availability — mapping stock_available_id CellphoneS."""
from __future__ import annotations

from cps_api import (
    STOCK_AVAILABLE_DROP_SHIPPING,
    STOCK_AVAILABLE_IN_STOCK,
    STOCK_AVAILABLE_OUT_OF_STOCK,
    STOCK_AVAILABLE_PRE_ORDER,
    STOCK_AVAILABLE_SUBSCRIPTION,
    STOCK_AVAILABLE_VIRTUAL_STOCK,
    parse_stock_availability,
)


def _f(**kwargs: object) -> dict:
    base = {
        "product_state": "",
        "stock": None,
        "stock_available_id": None,
    }
    base.update(kwargs)
    return base


def test_in_stock_with_qty() -> None:
    r = parse_stock_availability(_f(stock_available_id=46, stock=5))
    assert r["status_code"] == "in_stock"
    assert r["is_buyable_online"]
    assert "Còn hàng (5)" in r["display_status"]


def test_out_of_stock() -> None:
    r = parse_stock_availability(_f(stock_available_id=43, stock=0))
    assert r["is_out_of_stock"]
    assert not r["is_buyable_online"]
    assert "Hết hàng" in r["display_status"]


def test_pre_order() -> None:
    r = parse_stock_availability(_f(stock_available_id=152, stock=10))
    assert r["is_pre_order"]
    assert r["is_buyable_online"]
    assert "đặt trước" in r["display_status"].lower() or "Đặt trước" in r["display_status"]


def test_subscription() -> None:
    r = parse_stock_availability(_f(stock_available_id=56))
    assert r["is_subscription"]
    assert not r["is_buyable_online"]
    assert "Đăng ký nhận tin" in r["display_status"]


def test_virtual_and_drop_shipping() -> None:
    v = parse_stock_availability(_f(stock_available_id=4920, stock=3))
    d = parse_stock_availability(_f(stock_available_id=4164, stock=2))
    assert v["is_in_stock"] and v["is_buyable_online"]
    assert d["is_in_stock"] and d["is_buyable_online"]


def test_constants() -> None:
    assert STOCK_AVAILABLE_OUT_OF_STOCK == 43
    assert STOCK_AVAILABLE_IN_STOCK == 46
    assert STOCK_AVAILABLE_SUBSCRIPTION == 56
    assert STOCK_AVAILABLE_PRE_ORDER == 152
    assert STOCK_AVAILABLE_DROP_SHIPPING == 4164
    assert STOCK_AVAILABLE_VIRTUAL_STOCK == 4920


if __name__ == "__main__":
    test_in_stock_with_qty()
    test_out_of_stock()
    test_pre_order()
    test_subscription()
    test_virtual_and_drop_shipping()
    test_constants()
    print("OK — stock availability tests passed")
