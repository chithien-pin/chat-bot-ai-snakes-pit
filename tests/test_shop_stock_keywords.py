"""Test bóc từ khóa SP từ câu hỏi tồn cửa hàng."""
from cps_bot.cps.cps_api import (
    needs_shop_stock_keyword_strip,
    should_attach_shop_stock,
    strip_shop_stock_phrases_for_keywords,
)
from cps_bot.llm.gemini_client import extract_search_keywords


def test_strip_shop_near_district():
    q = "Shop gần quận 1 còn Samsung S26 Ultra không?"
    assert needs_shop_stock_keyword_strip(q)
    assert strip_shop_stock_phrases_for_keywords(q) == "Samsung S26 Ultra"


def test_strip_shop_district_without_gan():
    q = "shop quận 1 còn iPhone không"
    assert needs_shop_stock_keyword_strip(q)
    assert strip_shop_stock_phrases_for_keywords(q) == "iPhone"


def test_strip_shop_near_me():
    q = "cửa hàng gần tôi còn iPhone 16 Pro Max không"
    assert strip_shop_stock_phrases_for_keywords(q) == "iPhone 16 Pro Max"


def test_strip_product_before_location_suffix():
    q = "Còn hàng Samsung S24 ở shop quận 9 không?"
    assert strip_shop_stock_phrases_for_keywords(q) == "Samsung S24"


def test_strip_product_before_location_suffix():
    q = "Còn hàng Samsung S24 ở shop quận 9 không?"
    assert strip_shop_stock_phrases_for_keywords(q) == "Samsung S24"


def test_strip_product_first_shop_stock():
    q = "iphone 17 256gb còn hàng ở cửa hàng nào?"
    assert needs_shop_stock_keyword_strip(q)
    assert strip_shop_stock_phrases_for_keywords(q) == "iphone 17 256gb"
    assert extract_search_keywords(q, use_llm=False) == "iphone 17 256gb"


def test_strip_stock_colors():
    q = "iPhone 17prm còn tồn những màu nào"
    assert strip_shop_stock_phrases_for_keywords(q) == "iPhone 17prm"


def test_strip_combo_stock():
    q = "Tìm cửa hàng gần nhất có đủ combo sạc và cáp Baseus Dura"
    assert "baseus" in strip_shop_stock_phrases_for_keywords(q).lower()


def test_extract_search_keywords_shop_stock():
    q = "Shop gần quận 1 còn Samsung S26 Ultra không?"
    assert extract_search_keywords(q) == "Samsung S26 Ultra"


def test_should_attach_shop_stock_follow_up_stock_status():
    assert should_attach_shop_stock("loa này còn hàng không?")
    assert should_attach_shop_stock(
        "loa này còn hàng không?",
        reuse_product_context=True,
    )


def test_should_attach_shop_stock_first_message_stock():
    assert should_attach_shop_stock("iPhone 16 Pro còn hàng không?")
    assert not should_attach_shop_stock("giá iPhone 16 Pro bao nhiêu?")


def test_province_stock_query_binh_phuoc():
    from cps_bot.cps.cps_api import is_province_stock_query
    from cps_bot.cps.cps_provinces import resolve_province_from_text

    q = "Có hàng ở Bình Phước ko?"
    assert resolve_province_from_text(q) == 10
    assert is_province_stock_query(q)
    assert should_attach_shop_stock(q)
    assert should_attach_shop_stock(q, reuse_product_context=True)


def test_should_attach_shop_stock_explicit_shop():
    assert should_attach_shop_stock("shop nào còn hàng?")
    assert should_attach_shop_stock("", resume=True)


def test_ton_kho_tai_quan_10_triggers_shop_stock():
    q = "tồn kho tại Quận 10 hồ chí minh cho iPhone 17 Pro Max 256GB bạc"
    from cps_bot.cps.cps_api import (
        extract_location_hint,
        is_shop_stock_question,
        strip_shop_stock_phrases_for_keywords,
    )
    from cps_bot.cps.cps_provinces import resolve_province_from_text

    assert is_shop_stock_question(q)
    assert should_attach_shop_stock(q)
    assert needs_shop_stock_keyword_strip(q)
    assert strip_shop_stock_phrases_for_keywords(q) == "iPhone 17 Pro Max 256GB bạc"
    assert extract_location_hint(q).lower() == "quận 10"
    assert resolve_province_from_text(q) == 30


def test_follow_up_o_quan_10_co_khong():
    q = "ở quận 10 có không?"
    from cps_bot.cps.cps_api import extract_location_hint, is_district_stock_query

    assert extract_location_hint(q) == "quận 10"
    assert is_district_stock_query(q)
    assert should_attach_shop_stock(q, reuse_product_context=True)
    assert should_attach_shop_stock(q)
    from cps_bot.cps.cps_api import _flatten_shops

    districts = [
        {
            "district_id": "10",
            "district_name": "Quận 10",
            "province_id": 30,
            "province_name": "Hồ Chí Minh",
            "shops": [
                {
                    "id": 196,
                    "external_id": 1165,
                    "address": "347 Nguyễn Tri Phương, Phường 5, Quận 10, TP. HCM",
                    "phone": "02871000347",
                },
                {
                    "id": 5,
                    "external_id": 159,
                    "address": "Số 296 đường 3 tháng 2, Phường Hòa Hưng, Thành phố Hồ Chí Minh, Việt Nam",
                    "phone": "02871066288",
                },
            ],
        }
    ]
    shops = _flatten_shops(districts, location_hint="quận 10")
    assert len(shops) == 2
    addresses = {s["address"] for s in shops}
    assert any("Nguyễn Tri Phương" in a for a in addresses)
    assert any("3 tháng 2" in a for a in addresses)


if __name__ == "__main__":
    test_strip_shop_near_district()
    test_strip_shop_district_without_gan()
    test_strip_shop_near_me()
    test_strip_product_before_location_suffix()
    test_strip_product_first_shop_stock()
    test_strip_stock_colors()
    test_strip_combo_stock()
    test_extract_search_keywords_shop_stock()
    print("OK")
