"""Tests fast-path so sánh + Lark column card."""
from cps_bot.browse.compare_reply import (
    build_compare_advice,
    build_compare_reply,
    build_compare_summary,
    can_fast_compare_reply,
    pick_compare_specs,
)
from cps_bot.lark.compare_card import build_lark_compare_card


def _sample_product(name: str, price: str, **extra) -> dict:
    base = {
        "product_id": "1",
        "name": name,
        "price": price,
        "stock_status": "Còn hàng",
        "url": "https://cellphones.com.vn/x.html",
        "specifications": {
            "Màn hình": '6.7" Super AMOLED',
            "Chip": "Exynos 1330",
            "RAM": "8 GB",
            "Bộ nhớ trong": "256 GB",
            "Pin": "5000 mAh",
        },
    }
    base.update(extra)
    return base


def test_can_fast_compare_reply():
    payload = {
        "compare_mode": True,
        "compare_products": [
            _sample_product("Galaxy A17 5G", "5.290.000đ"),
            _sample_product("Redmi Note 15", "4.990.000đ"),
        ],
    }
    detail = {"product_id": "1", "name": "Galaxy A17 5G"}
    q = "So sánh Galaxy A17 5G và Redmi note 15"
    assert can_fast_compare_reply(q, detail, payload)


def test_can_fast_compare_blocks_advice():
    payload = {
        "compare_mode": True,
        "compare_products": [
            _sample_product("A", "1đ"),
            _sample_product("B", "2đ"),
        ],
    }
    detail = {"product_id": "1"}
    assert not can_fast_compare_reply(
        "So sánh A và B nên mua con nào tư vấn giúp",
        detail,
        payload,
    )


def test_build_lark_compare_card_has_column_set():
    products = [
        _sample_product("Galaxy A17 5G", "5.290.000đ"),
        _sample_product("Redmi Note 15", "4.990.000đ"),
    ]
    card = build_lark_compare_card(products, summary="⚖️ So sánh nhanh")
    assert card["header"]["title"]["content"] == "So sánh sản phẩm"
    column_sets = [
        el for el in card["elements"] if el.get("tag") == "column_set"
    ]
    assert len(column_sets) == 1
    columns = column_sets[0]["columns"]
    assert len(columns) == 2
    assert columns[0]["tag"] == "column"
    assert "Galaxy A17" in columns[0]["elements"][0]["text"]["content"]
    assert all(el.get("tag") != "action" for col in columns for el in col.get("elements", []))


def test_build_compare_advice_price_and_pin():
    products = [
        _sample_product("Galaxy A17 5G", "5.290.000đ", price_value=5_290_000),
        _sample_product(
            "Redmi Note 15",
            "4.990.000đ",
            price_value=4_990_000,
            specifications={
                "Màn hình": '6.67"',
                "RAM": "8 GB",
                "Pin": "5110 mAh",
            },
        ),
    ]
    advice = build_compare_advice(products)
    assert "Gợi ý chọn máy" in advice
    assert "Redmi Note 15" in advice
    assert "rẻ hơn" in advice
    assert "5000 mAh" in advice or "5110 mAh" in advice


def test_build_compare_summary_for_lark():
    products = [
        _sample_product("Galaxy A17 5G", "5.290.000đ", price_value=5_290_000),
        _sample_product("Redmi Note 15", "4.990.000đ", price_value=4_990_000),
    ]
    summary = build_compare_summary(products, fast=True)
    assert "So sánh nhanh" in summary
    assert "Gợi ý chọn máy" in summary


def test_build_compare_reply_includes_advice():
    payload = {
        "compare_mode": True,
        "compare_products": [
            _sample_product("Galaxy A17 5G", "5.290.000đ", price_value=5_290_000),
            _sample_product("Redmi Note 15", "4.990.000đ", price_value=4_990_000),
        ],
    }
    text = build_compare_reply("So sánh A và B", payload)
    assert "Gợi ý chọn máy" in text


def test_build_compare_reply_plain():
    payload = {
        "compare_mode": True,
        "compare_products": [
            _sample_product("Galaxy A17 5G", "5.290.000đ"),
            _sample_product("Redmi Note 15", "4.990.000đ"),
        ],
    }
    text = build_compare_reply("So sánh A và B", payload)
    assert "Galaxy A17 5G" in text
    assert "Redmi Note 15" in text


def test_pick_compare_specs_priority():
    specs = pick_compare_specs(
        {
            "specifications": {
                "Bluetooth": "5.3",
                "Màn hình": '6.7"',
                "Chip": "Snapdragon",
            }
        }
    )
    labels = [label for label, _ in specs]
    assert labels[0] == "Màn hình"
