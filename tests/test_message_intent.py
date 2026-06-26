"""Test phân tích ý định tin nhắn."""
from __future__ import annotations

from cps_bot.llm.message_intent import is_social_message, resolve_message_intent


def test_basic_intents():
    ctx = "Sản phẩm đang thảo luận: iPhone 17 Pro Max\nTừ khóa tìm gần nhất: iPhone 17 Pro Max"

    r = resolve_message_intent("hello tôi cần giúp đỡ")
    assert r.kind in ("greeting", "help"), r.kind
    assert r.reply
    r2 = resolve_message_intent(
        "hello tôi cần giúp đỡ",
        conversation_context=ctx,
        has_product_context=True,
        is_follow_up=True,
    )
    assert r2.kind in ("greeting", "help")
    assert is_social_message("hello tôi cần giúp đỡ")
    assert resolve_message_intent("xin chào bạn").kind == "greeting"
    assert resolve_message_intent("cảm ơn nhé").kind == "thanks"
    assert resolve_message_intent("bot làm được gì").kind == "help"
    assert resolve_message_intent("thời tiết hôm nay sao").kind == "off_topic"
    assert resolve_message_intent("tư vấn giúp mình").kind == "clarify"

    assert resolve_message_intent("giá iPhone 16 Pro Max").kind == "product"
    assert resolve_message_intent("còn hàng không?", conversation_context=ctx, has_product_context=True).kind == "product"
    assert resolve_message_intent(
        "có hỗ trợ trả góp không?",
        conversation_context=ctx,
        has_product_context=True,
        is_follow_up=True,
    ).kind == "product"
    assert resolve_message_intent("cửa hàng cellphones gần quận 1").kind == "product"


def test_off_topic_meta_and_code():
    assert resolve_message_intent("bạn đang dùng công nghệ gì").kind == "off_topic"
    assert resolve_message_intent("viết code python giùm em").kind == "off_topic"
    assert resolve_message_intent("phân tích kinh tế việt nam").kind == "off_topic"
    assert resolve_message_intent("giải thích thuật toán quicksort").kind == "off_topic"


def test_product_advice_still_product():
    assert resolve_message_intent("Sạc dự phòng có thể mang lên máy bay").kind == "product"
    assert resolve_message_intent("phân tích ưu nhược iPhone 17 Pro Max").kind == "product"


def test_should_llm_normalize_keywords():
    from cps_bot.llm.gemini_client import should_llm_normalize_keywords

    assert should_llm_normalize_keywords("Sạc dự phòng có thể mang lên máy bay")
    assert not should_llm_normalize_keywords(
        "còn hàng không?",
        "Sản phẩm đang thảo luận: iPhone 17 Pro Max",
    )


if __name__ == "__main__":
    test_basic_intents()
    test_off_topic_meta_and_code()
    test_product_advice_still_product()
    test_should_llm_normalize_keywords()
    print("OK — message intent tests passed")
