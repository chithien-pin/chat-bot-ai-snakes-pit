"""Test bóc từ khóa SP từ câu hỏi tồn cửa hàng."""
from cps_api import (
    needs_shop_stock_keyword_strip,
    strip_shop_stock_phrases_for_keywords,
)
from gemini_client import extract_search_keywords


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


def test_extract_search_keywords_shop_stock():
    q = "Shop gần quận 1 còn Samsung S26 Ultra không?"
    assert extract_search_keywords(q) == "Samsung S26 Ultra"


if __name__ == "__main__":
    test_strip_shop_near_district()
    test_strip_shop_district_without_gan()
    test_strip_shop_near_me()
    test_strip_product_before_location_suffix()
    test_extract_search_keywords_shop_stock()
    print("OK")
