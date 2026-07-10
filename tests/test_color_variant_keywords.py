"""Test bóc cụm hỏi màu — tránh product map trúng phụ kiện 'viền màu'."""
from __future__ import annotations

from cps_bot.browse.product_map import clear_product_map_cache, resolve_product_from_map
from cps_bot.cps.cps_api import strip_color_variant_list_phrases_for_keywords
from cps_bot.llm.gemini_client import extract_search_keywords


def test_strip_color_list_phrases() -> None:
    assert strip_color_variant_list_phrases_for_keywords(
        "iphone 17 256gb có màu nào?"
    ) == "iphone 17 256gb"
    assert strip_color_variant_list_phrases_for_keywords(
        "các màu của iphone 17 256gb"
    ) == "iphone 17 256gb"
    assert strip_color_variant_list_phrases_for_keywords(
        "có màu nào khác không?"
    ) == ""


def test_extract_keywords_color_list_strips_noise() -> None:
    kw = extract_search_keywords("iphone 17 256gb có màu nào?", use_llm=False)
    assert kw == "iphone 17 256gb"
    assert "màu" not in kw.lower()


def test_product_map_color_list_query_resolves_iphone_not_accessory() -> None:
    clear_product_map_cache()
    wrong = resolve_product_from_map("iphone 17 256gb có màu nào")
    if wrong is not None:
        assert "dán" not in wrong.name.lower()
        assert "zagg" not in wrong.name.lower()

    hit = resolve_product_from_map("iphone 17 256gb")
    assert hit is not None
    assert hit.product_id == "112580"
    assert "iPhone 17 256GB" in hit.name
