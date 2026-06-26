"""Test bóc từ khóa search — giá / model viết dính."""
from cps_bot.llm.gemini_client import extract_search_keywords, _normalize_keyword_line


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


if __name__ == "__main__":
    test_iphone_promax_price_question()
    test_normalize_promax_compound()
    test_strip_price_how_question()
    test_storage_shorthand_256g()
    test_strip_price_suffix_variants()
    print("OK")
