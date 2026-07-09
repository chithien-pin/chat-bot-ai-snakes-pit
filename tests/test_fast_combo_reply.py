"""Test fast combo/accessory reply — template không qua LLM."""
from __future__ import annotations

from cps_bot.browse.combo_reply import build_combo_reply, can_fast_combo_reply
from cps_bot.cps.cps_api import is_combo_accessory_query
from cps_bot.llm.gemini_client import extract_search_keywords
from cps_bot.llm.query_router import resolve_query_route


def _combo_payload(**overrides) -> tuple[str, dict, dict]:
    question = "Phụ kiện mua kèm Galaxy A17 5G"
    detail = {
        "product_id": 12345,
        "name": "Samsung Galaxy A17 5G",
    }
    payload = {
        "primary_product": {
            "product_id": 12345,
            "name": "Samsung Galaxy A17 5G | Chính hãng",
            "included_accessories": "Cáp USB-C; Que chọc SIM",
            "url": "https://cellphones.com.vn/samsung-galaxy-a17-5g.html",
        },
        "product_combos": [
            {"name": "Combo ốp + dán", "discount_percent": 10, "max_value": 100000},
        ],
        "recommended_products": [
            {
                "name": "Ốp lưng Galaxy A17 5G",
                "price": "199.000₫",
                "stock_status": "Còn hàng",
                "url": "https://cellphones.com.vn/op-lung-a17.html",
                "product_id": 999,
            },
        ],
    }
    payload.update(overrides.pop("payload", {}))
    detail.update(overrides.pop("detail", {}))
    question = overrides.pop("question", question)
    return question, detail, payload


def test_is_combo_accessory_query() -> None:
    assert is_combo_accessory_query("Phụ kiện mua kèm Galaxy A17 5G")
    assert is_combo_accessory_query("mua kèm giảm bao nhiêu")
    assert is_combo_accessory_query("mua cùng Galaxy A17 5G")


def test_category_browse_blocked_for_combo_with_product() -> None:
    from cps_bot.browse.category_filter_browse import is_category_filter_browse_query

    assert not is_category_filter_browse_query("Phụ kiện mua kèm Galaxy A17 5G")
    assert not is_category_filter_browse_query("Mua cùng iPhone 17 Pro Max")


def test_extract_keywords_strips_combo_noise() -> None:
    kw = extract_search_keywords("Phụ kiện mua kèm Galaxy A17 5G", use_llm=False)
    assert "galaxy" in kw.lower()
    assert "a17" in kw.lower()
    assert "mua kèm" not in kw.lower()
    assert "phụ kiện" not in kw.lower()


def test_can_fast_combo_reply_positive() -> None:
    q, detail, payload = _combo_payload()
    assert can_fast_combo_reply(q, detail, payload)


def test_can_fast_combo_reply_blocks_compare() -> None:
    q, detail, payload = _combo_payload(payload={"compare_mode": True})
    assert not can_fast_combo_reply(q, detail, payload)


def test_build_combo_reply_includes_sections() -> None:
    q, _, payload = _combo_payload()
    answer = build_combo_reply(q, payload)
    assert "Samsung Galaxy A17 5G" in answer
    assert "Cáp USB-C" in answer
    assert "Combo ốp + dán" in answer
    assert "Ốp lưng Galaxy A17 5G" in answer
    assert "199.000₫" in answer
    assert "cellphones.com.vn" in answer


def test_query_router_combo_query_skips_llm() -> None:
    route = resolve_query_route("Phụ kiện mua kèm Galaxy A17 5G", use_llm=False)
    assert route.mode == "product_search"
    assert route.confidence >= 0.9
    assert route.source == "rule"
    assert "galaxy" in route.search_keywords.lower()


if __name__ == "__main__":
    test_is_combo_accessory_query()
    test_category_browse_blocked_for_combo_with_product()
    test_extract_keywords_strips_combo_noise()
    test_can_fast_combo_reply_positive()
    test_can_fast_combo_reply_blocks_compare()
    test_build_combo_reply_includes_sections()
    test_query_router_combo_query_skips_llm()
    print("OK — fast combo reply tests passed")
