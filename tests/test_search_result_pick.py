"""Test chọn kết quả search — ưu tiên đúng thế hệ iPhone."""
from __future__ import annotations

from cps_bot.cps.cps_api import _pick_best_search_result


def test_pick_iphone_16_over_17() -> None:
    results = [
        {
            "name": "iPhone 17 256GB",
            "url_path": "iphone-17-256gb.html",
            "url": "https://cellphones.com.vn/iphone-17-256gb.html",
        },
        {
            "name": "iPhone 16 256GB | Chính hãng VN/A",
            "url_path": "iphone-16-256gb.html",
            "url": "https://cellphones.com.vn/iphone-16-256gb.html",
        },
    ]
    best = _pick_best_search_result(results, "iPhone 16 256GB Hồng")
    assert best is not None
    assert "16" in best["name"]
    assert "17" not in best["name"]


def test_pick_base_iphone_16_over_plus() -> None:
    results = [
        {
            "name": "iPhone 16 Pro 256GB",
            "url_path": "iphone-16-pro-256gb.html",
        },
        {
            "name": "iPhone 16 256GB | Chính hãng VN/A",
            "url_path": "iphone-16-256gb.html",
        },
    ]
    best = _pick_best_search_result(results, "iPhone 16 256GB Hồng")
    assert best is not None
    assert best["url_path"] == "iphone-16-256gb.html"


def test_pick_base_iphone_16_128_over_plus_128() -> None:
    results = [
        {
            "name": "iPhone 16 Plus 128GB | Chính hãng VN/A",
            "url_path": "iphone-16-plus-128gb.html",
        },
        {
            "name": "iPhone 16 128GB | Chính hãng VN/A",
            "url_path": "iphone-16-128gb.html",
        },
    ]
    best = _pick_best_search_result(results, "iPhone 16 128GB Xanh Mỏng Két")
    assert best is not None
    assert "Plus" not in best["name"]


def test_xanh_mong_ket_color_hint() -> None:
    from cps_bot.cps.cps_api import _extract_variant_hints

    hints = _extract_variant_hints("iphone 16 xanh mỏng két 128g")
    assert "xanh mỏng két" in hints
    assert "128gb" in hints
    hints_luu_ly = _extract_variant_hints("iphone 16 xanh lưu ly")
    assert "xanh lưu ly" in hints_luu_ly
    assert "xanh" not in hints_luu_ly


def test_color_variant_list_query() -> None:
    from cps_bot.cps.cps_api import is_color_variant_list_query

    assert is_color_variant_list_query("còn màu nào khác không?")
    assert is_color_variant_list_query("còn màu khác không?")
    assert is_color_variant_list_query("có màu khác không")
    assert is_color_variant_list_query("màu gì còn tồn")
    assert is_color_variant_list_query("các màu của ip17 pro")
    assert not is_color_variant_list_query("giá iphone 16 bao nhiêu")
