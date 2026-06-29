"""Test nhận diện câu hỏi tiếp theo (ngữ cảnh SP)."""
from __future__ import annotations

from cps_bot.llm.gemini_client import (
    extract_search_keywords,
    is_contextual_follow_up,
    references_prior_product,
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


def test_deictic_stock_follow_up_q1() -> None:
    ctx = _ctx("ip17prm 1tb màu cam", "iPhone 17 Pro Max 1TB Cam")
    q = "sản phẩm này có hàng ở q1 ko?"
    assert references_prior_product(q)
    assert is_contextual_follow_up(q, ctx)
    kw = extract_search_keywords(q, ctx, use_llm=False)
    assert "1tb" in kw.lower() or "ip17" in kw.lower() or "iphone" in kw.lower(), f"keyword sai: {kw!r}"


def test_variant_color_switch_in_follow_up() -> None:
    from cps_bot.cps.cps_api import merge_follow_up_variant_into_keywords

    base = "iPhone 17 Pro 1TB Xanh"
    q = "Vậy màu bạc thì có hàng ở bình dương ko?"
    merged = merge_follow_up_variant_into_keywords(base, q)
    assert "bạc" in merged.lower(), merged
    assert "xanh" not in merged.lower(), merged


def test_extract_keywords_variant_switch_from_context() -> None:
    ctx = _ctx("iPhone 17 Pro 1TB Xanh", "iPhone 17 Pro 1TB Xanh Đậm")
    q = "Vậy màu bạc thì có hàng ở bình dương ko?"
    kw = extract_search_keywords(q, ctx, use_llm=False)
    assert "bạc" in kw.lower(), kw
    assert "xanh" not in kw.lower(), kw


def test_resolve_session_chat_level_on_new_topic() -> None:
    from cps_bot.core.conversation import (
        get_session,
        has_product_context,
        mirror_session_to_chat_level,
        resolve_session,
    )

    store: dict = {}
    chat_id, user_id = "lark-chat", "user-1"
    topic_a = get_session(store, chat_id, user_id, thread_key="topic:A")
    topic_a["last_keywords"] = "ip17prm 1tb màu cam"
    topic_a["last_product"] = {"name": "iPhone 17 Pro Max 1TB Cam", "product_id": 112630}
    topic_a["turns"] = [("u", "q1"), ("b", "a1")]
    mirror_session_to_chat_level(store, chat_id, user_id, topic_a)

    topic_b = resolve_session(store, chat_id, user_id, thread_key="topic:B")
    assert has_product_context(topic_b), "topic mới phải kế thừa mirror chat-level"
    assert "1tb" in (topic_b.get("last_keywords") or "").lower()


def test_screen_inch_variant_switch() -> None:
    from cps_bot.cps.cps_api import (
        merge_follow_up_variant_into_keywords,
        screen_size_conflicts_with_session,
    )

    base = "MacBook Pro M5"
    q = "có bản 16inch không?"
    merged = merge_follow_up_variant_into_keywords(base, q)
    assert "16" in merged, merged
    assert "inch" in merged.lower(), merged
    assert screen_size_conflicts_with_session(
        q,
        last_keywords=base,
        last_product_name="MacBook Pro 14 M5 16GB/512GB",
    )


def test_extract_keywords_screen_inch_from_context() -> None:
    from cps_bot.llm.gemini_client import (
        extract_search_keywords,
        identity_compatible_with_session,
        should_reuse_product_identity,
    )

    ctx = (
        "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n"
        "Sản phẩm đang thảo luận: MacBook Pro 14 M5 16GB/512GB\n"
        "Từ khóa tìm gần nhất: MacBook Pro M5\n"
    )
    q = "có bản 16inch không?"
    kw = extract_search_keywords(q, ctx, use_llm=False)
    assert "16" in kw, kw
    assert not should_reuse_product_identity(
        q, ctx, last_keywords="MacBook Pro M5", last_product_name="MacBook Pro 14 M5"
    )
    assert not identity_compatible_with_session(
        q, last_keywords="MacBook Pro M5", last_product_name="MacBook Pro 14 M5"
    )


if __name__ == "__main__":
    test_follow_up_mau_sac_gia_ban()
    test_new_product_not_follow_up()
    test_budget_not_follow_up()
    print("OK — context follow-up tests passed")
