"""Fast-path trả lời tồn cửa hàng — không qua LLM."""
from cps_bot.browse.fast_reply import build_shop_stock_reply, can_fast_shop_stock_reply
from cps_bot.cps.cps_api import format_shop_stock_summary
from cps_bot.llm.query_router import resolve_query_route


def test_can_fast_shop_stock_reply_pure_stock():
    payload = {
        "shop_stock": {
            "product_id": 123,
            "product_name": "Samsung Galaxy A17 5G",
            "province_name": "Hồ Chí Minh",
            "location_hint": "quận 10",
            "total_shops_in_province": 2,
            "matched_shops_count": 1,
            "shops": [
                {
                    "address": "347 Nguyễn Tri Phương, Phường 5, Quận 10",
                    "district_name": "Quận 10",
                    "phone": "02871000347",
                }
            ],
        },
        "primary_product": {
            "product_id": 123,
            "name": "Samsung Galaxy A17 5G",
            "url": "https://cellphones.com.vn/samsung-galaxy-a17.html",
        },
    }
    detail = {"product_id": 123, "name": "Samsung Galaxy A17 5G"}
    q = "Q10 có tồn Galaxy A17"
    assert can_fast_shop_stock_reply(q, detail, payload)


def test_can_fast_shop_stock_reply_blocks_price():
    payload = {
        "shop_stock": {"product_id": 1, "product_name": "iPhone 17", "shops": []},
        "primary_product": {"product_id": 1, "name": "iPhone 17", "price": "20.000.000đ"},
    }
    detail = {"product_id": 1}
    assert not can_fast_shop_stock_reply("giá và tồn iphone 17 q10", detail, payload)


def test_build_shop_stock_reply_uses_template():
    payload = {
        "shop_stock": {
            "product_name": "Samsung Galaxy A17 5G",
            "province_name": "Hồ Chí Minh",
            "location_hint": "quận 10",
            "total_shops_in_province": 1,
            "shops": [
                {
                    "address": "347 Nguyễn Tri Phương, Quận 10",
                    "district_name": "Quận 10",
                    "phone": "02871000347",
                }
            ],
        },
        "primary_product": {
            "url": "https://cellphones.com.vn/samsung-galaxy-a17.html",
        },
    }
    answer = build_shop_stock_reply("Q10 có tồn Galaxy A17", payload)
    assert "Samsung Galaxy A17 5G" in answer
    assert "347 Nguyễn Tri Phương" in answer
    assert "02871000347" in answer
    assert "cellphones.com.vn" in answer


def test_format_shop_stock_summary_no_shops_in_district():
    ctx = {
        "product_name": "Galaxy A17",
        "province_name": "Hồ Chí Minh",
        "location_hint": "quận 10",
        "total_shops_in_province": 3,
        "shops": [],
    }
    text = format_shop_stock_summary(ctx)
    assert "Không tìm thấy cửa hàng khớp" in text


def test_query_router_stock_query_skips_llm():
    route = resolve_query_route("Q10 có tồn Galaxy A17", use_llm=False)
    assert route.mode == "product_search"
    assert route.confidence >= 0.9
    assert route.source == "rule"
    assert "galaxy" in route.search_keywords.lower()
