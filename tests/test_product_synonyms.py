"""Test product term synonym normalization."""
from __future__ import annotations

from cps_bot.browse.category_filter_browse import resolve_category_filter_request
from cps_bot.browse.category_resolver import refine_to_deepest_category_match, resolve_category_match
from cps_bot.browse.product_map import resolve_product_from_map
from cps_bot.browse.product_term_synonyms import normalize_product_terms
from cps_bot.llm.gemini_client import extract_search_keywords


def test_sac_du_phong_normalized_to_pin():
    assert normalize_product_terms("Sạc dự phòng Anker") == "pin dự phòng Anker"


def test_sac_du_phong_airplane_query_keywords():
    text = "Sạc dự phòng có thể mang lên máy bay"
    keywords = extract_search_keywords(text, use_llm=False)
    assert "pin" in keywords.lower()
    assert "máy bay" not in keywords.lower()


def test_sac_du_phong_resolves_same_category_as_pin():
    from cps_bot.browse.category_resolver import _category_match_index

    _category_match_index.cache_clear()
    sac = resolve_category_match("Sạc dự phòng có thể mang lên máy bay")
    pin = resolve_category_match("Pin dự phòng có thể mang lên máy bay")
    assert sac is not None and pin is not None
    assert refine_to_deepest_category_match("Sạc dự phòng có thể mang lên máy bay", sac).category_id == "122"
    assert pin.category_id == "122"


def test_sac_du_phong_product_map_hit():
    hit = resolve_product_from_map("Sạc dự phòng có thể mang lên máy bay")
    assert hit is not None
    assert "pin" in hit.name.lower() or "sạc" in hit.name.lower()


if __name__ == "__main__":
    test_sac_du_phong_normalized_to_pin()
    test_sac_du_phong_airplane_query_keywords()
    test_sac_du_phong_resolves_same_category_as_pin()
    test_sac_du_phong_product_map_hit()
    print("OK")
