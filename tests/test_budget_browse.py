"""Tests — tìm SP theo ngân sách và không reuse keyword cũ."""
from __future__ import annotations

from cps_bot.browse.budget_browse import (
    filter_results_by_budget,
    is_budget_browse_query,
    parse_budget_constraint,
    strip_budget_phrases_for_keywords,
)
from cps_bot.llm.gemini_client import (
    extract_search_keywords,
    is_contextual_follow_up,
    _mentions_new_product,
)


def _ctx(keywords: str, product: str) -> str:
    return (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        f"Sản phẩm đang thảo luận: {product}\n"
        f"Từ khóa tìm gần nhất: {keywords}\n"
        "Khách: iphone 17 pro max\n"
        "Bot: Giá từ ..."
    )


def test_budget_query_detected() -> None:
    assert is_budget_browse_query("điện thoại dưới 15 triệu")
    assert is_budget_browse_query("laptop từ 15 đến 20 triệu")
    assert is_budget_browse_query("Mua nồi chiên tầm 8 lít, giá 600k đổ lại")
    assert not is_budget_browse_query("iPhone 17 Pro Max giá bao nhiêu")
    assert not is_budget_browse_query("máy hút bụi lực hút trên 10000Pa")


def test_pa_suction_not_parsed_as_budget() -> None:
    q = "máy hút bụi lực hút trên 10000Pa"
    assert parse_budget_constraint(q) is None
    kw = strip_budget_phrases_for_keywords(q)
    assert "10000" in kw.lower() or "10000pa" in kw.lower().replace(" ", "")


def test_air_fryer_600k() -> None:
    q = "Mua nồi chiên tầm 8 lít, giá 600k đổ lại"
    c = parse_budget_constraint(q)
    assert c is not None
    assert c.max_vnd == 600_000
    assert c.category == "nồi chiên"
    kw = strip_budget_phrases_for_keywords(q)
    assert "nồi chiên" in kw.lower()
    assert "8" in kw and "lít" in kw


def test_budget_keyword_strip() -> None:
    kw = strip_budget_phrases_for_keywords("điện thoại dưới 15 triệu")
    assert "điện thoại" in kw.lower()
    assert "15" not in kw


def test_budget_constraint_parse() -> None:
    c = parse_budget_constraint("điện thoại dưới 15 triệu")
    assert c is not None
    assert c.max_vnd == 15_000_000
    assert c.category == "điện thoại"


def test_bare_million_budget_range() -> None:
    c = parse_budget_constraint("Điện thoại 5 triệu")
    assert c is not None
    assert c.min_vnd == 4_000_000
    assert c.max_vnd == 6_000_000


def test_budget_filter_results() -> None:
    c = parse_budget_constraint("điện thoại dưới 15 triệu")
    assert c is not None
    rows = [
        {"name": "A", "price": "12.990.000₫"},
        {"name": "B", "price": "18.990.000₫"},
    ]
    out = filter_results_by_budget(rows, c)
    assert len(out) == 1
    assert out[0]["name"] == "A"


def test_budget_query_not_reuse_ip17_context() -> None:
    ctx = _ctx("ip17 pro max", "iPhone 17 Pro Max 256GB")
    q = "điện thoại dưới 15 triệu"
    assert _mentions_new_product(q)
    assert not is_contextual_follow_up(q, ctx)
    kw = extract_search_keywords(q, ctx, use_llm=False)
    assert "ip17" not in kw.lower()
    assert "17 pro" not in kw.lower()
    assert "điện thoại" in kw.lower() or ".html?price=" in kw


if __name__ == "__main__":
    test_budget_query_detected()
    test_air_fryer_600k()
    test_budget_keyword_strip()
    test_budget_constraint_parse()
    test_budget_filter_results()
    test_budget_query_not_reuse_ip17_context()
    print("OK — budget browse tests passed")
