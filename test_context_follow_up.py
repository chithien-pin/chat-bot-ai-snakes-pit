"""Test nhận diện câu hỏi tiếp theo (ngữ cảnh SP)."""
from __future__ import annotations

from gemini_client import (
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


def test_follow_up_mau_sac_gia_ban() -> None:
    ctx = _ctx("iPhone 17 Pro Max", "iPhone 17 Pro Max 256GB")
    q = "mau sac va gia ban"
    assert is_contextual_follow_up(q, ctx), "phải nhận là hỏi tiếp"
    assert not _mentions_new_product(q), "không nhắc SP mới"
    kw = extract_search_keywords(q, ctx)
    assert "17" in kw.lower() or "iphone" in kw.lower(), f"keyword sai: {kw!r}"


def test_new_product_not_follow_up() -> None:
    ctx = _ctx("iPhone 17 Pro Max", "iPhone 17 Pro Max")
    q = "Samsung Galaxy S25 Ultra giá bao nhiêu"
    assert _mentions_new_product(q)
    assert not is_contextual_follow_up(q, ctx)


def test_budget_not_follow_up() -> None:
    ctx = _ctx("ip17 pro max", "iPhone 17 Pro Max")
    q = "điện thoại dưới 15 triệu"
    assert not is_contextual_follow_up(q, ctx)


if __name__ == "__main__":
    test_follow_up_mau_sac_gia_ban()
    test_new_product_not_follow_up()
    test_budget_not_follow_up()
    print("OK — context follow-up tests passed")
