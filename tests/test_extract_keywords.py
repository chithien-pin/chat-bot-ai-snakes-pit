"""Test bóc từ khóa search — giá / model viết dính."""
from unittest.mock import patch

from cps_bot.llm.gemini_client import (
    _llm_keywords_acceptable,
    _llm_keywords_preserve_model_identity,
    _normalize_keyword_line,
    extract_search_keywords,
)


def test_iphone_promax_price_question():
    q = "iphone 16 promax hôm nay bao nhiêu?"
    assert extract_search_keywords(q) == "iphone 16 pro max"


def test_normalize_promax_compound():
    assert _normalize_keyword_line("iphone 16 promax") == "iphone 16 pro max"


def test_strip_price_how_question():
    q = "iphone 16 hồng 256g giá như thế nào?"
    kw = extract_search_keywords(q, use_llm=False)
    assert "16" in kw
    assert "256" in kw.lower()
    assert "hồng" in kw.lower() or "hong" in kw.lower()
    assert "giá" not in kw.lower()
    assert "thế nào" not in kw.lower()


def test_storage_shorthand_256g():
    from cps_bot.browse.product_term_synonyms import normalize_product_terms

    assert "256gb" in normalize_product_terms("iphone 16 hồng 256g").lower()


def test_strip_price_suffix_variants():
    assert _normalize_keyword_line("Samsung S24 Ultra giá bao nhiêu") == "Samsung S24 Ultra"
    assert _normalize_keyword_line("macbook air m2 bao nhiêu tiền") == "macbook air m2"
    assert _normalize_keyword_line("ip 16 pro max hôm nay bao nhiêu") == "ip 16 pro max"


def test_ip16_shorthand_expands():
    assert _normalize_keyword_line("ip16 xanh lưu ly") == "iphone 16 xanh lưu ly"
    kw = extract_search_keywords("ip16 xanh lưu ly giá bao nhiêu?", use_llm=False)
    assert kw == "iphone 16 xanh lưu ly"


def test_llm_rejects_macbook_neo_to_air_swap():
    original = "Giá macbook neo vangf 512g"
    bad_llm = "Macbook Air 512GB Vàng"
    assert not _llm_keywords_preserve_model_identity(original, bad_llm)
    assert not _llm_keywords_acceptable(bad_llm, original)


def test_macbook_neo_falls_back_when_llm_swaps_to_air():
    with patch(
        "cps_bot.llm.gemini_client._generate_with_fallback",
        return_value="Macbook Air 512GB Vàng",
    ):
        kw = extract_search_keywords("Giá macbook neo vangf 512g", use_llm=True)
    assert "neo" in kw.lower()
    assert "macbook" in kw.lower()


def test_installment_question_strips_to_product_keywords():
    kw = extract_search_keywords(
        "Thông tin trả góp MacBook Neo 256GB, gói nào ưu đãi nhất",
        use_llm=False,
    )
    assert "macbook" in kw.lower()
    assert "neo" in kw.lower()
    assert "256" in kw.lower()
    assert "trả góp" not in kw.lower()
    assert "ưu đãi" not in kw.lower()


if __name__ == "__main__":
    test_iphone_promax_price_question()
    test_normalize_promax_compound()
    test_strip_price_how_question()
    test_storage_shorthand_256g()
    test_strip_price_suffix_variants()
    print("OK")
