"""Test phân tích ý định tin nhắn."""
from __future__ import annotations

from message_intent import is_social_message, resolve_message_intent


def _run() -> None:
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


if __name__ == "__main__":
    _run()
    print("OK — message intent tests passed")
