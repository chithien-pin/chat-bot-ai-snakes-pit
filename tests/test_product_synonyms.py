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


def test_glued_iphone_shorthands_expand() -> None:
    assert normalize_product_terms("ip17prm") == "iphone 17 pro max"
    assert normalize_product_terms("iphone16prm") == "iphone 16 pro max"
    assert normalize_product_terms("ip16plus") == "iphone 16 plus"


def test_glued_samsung_shorthands_expand() -> None:
    assert normalize_product_terms("s26u") == "samsung galaxy s26 ultra"
    assert normalize_product_terms("s26+") == "samsung galaxy s26 plus"
    assert normalize_product_terms("galaxy s25u") == "samsung galaxy s25 ultra"


def test_glued_apple_and_xiaomi_shorthands_expand() -> None:
    assert normalize_product_terms("ipadpro m4") == "ipad pro m4"
    assert normalize_product_terms("mbair m4") == "macbook air m4"
    assert normalize_product_terms("mi14t") == "xiaomi 14t"
    assert normalize_product_terms("pocket3") == "pocket 3"
    assert normalize_product_terms("redmi note 14 pro+") == "redmi note 14 pro plus"
    assert normalize_product_terms("airpodspro3") == "airpods pro 3"
    assert normalize_product_terms("watchultra2") == "watch ultra 2"
    assert normalize_product_terms("macbookneo") == "macbook neo"
    assert normalize_product_terms("opporeno14") == "oppo reno 14"


def test_glued_shorthands_resolve_product_map() -> None:
    cases = {
        "ip17prm": "17 Pro Max",
        "s26+": "S26 Plus",
        "redmi note 14 pro+": "Pro Plus",
        "mbair m4": "MacBook Air M4",
        "pocket3": "Pocket 3",
    }
    for query, want in cases.items():
        kw = extract_search_keywords(query, use_llm=False)
        hit = resolve_product_from_map(kw)
        assert hit is not None, f"no map for {query!r} -> {kw!r}"
        assert want.lower() in hit.name.lower(), f"{query!r}: {hit.name!r}"


if __name__ == "__main__":
    test_sac_du_phong_normalized_to_pin()
    test_sac_du_phong_airplane_query_keywords()
    test_sac_du_phong_resolves_same_category_as_pin()
    test_sac_du_phong_product_map_hit()
    test_glued_iphone_shorthands_expand()
    test_glued_samsung_shorthands_expand()
    test_glued_apple_and_xiaomi_shorthands_expand()
    test_glued_shorthands_resolve_product_map()
    print("OK")
