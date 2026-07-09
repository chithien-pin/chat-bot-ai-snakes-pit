"""Test fast price reply — template trả lời giá/KM không qua LLM."""
from __future__ import annotations

from cps_bot.browse.fast_reply import build_price_reply, can_fast_price_reply


def _price_payload(**overrides) -> tuple[str, dict, dict]:
    question = "giá iphone 17 pro max 1tb"
    detail = {"product_id": "999", "name": "iPhone 17 Pro Max 1TB", "price": "45.990.000₫"}
    payload = {
        "primary_product": {
            "product_id": "999",
            "name": "iPhone 17 Pro Max 1TB | Chính hãng VN/A",
            "price": "45.990.000₫",
            "old_price": "47.990.000₫",
            "stock_status": "Còn hàng",
            "url": "https://cellphones.com.vn/iphone-17-pro-max-1tb.html",
            "member_prices": [{"label": "SMem", "price_formatted": "44.990.000₫"}],
            "promotions": {
                "km_chung": [{"description": "Giảm thêm 500k khi thanh toán qua ví"}],
            },
        }
    }
    payload.update(overrides.pop("payload", {}))
    detail.update(overrides.pop("detail", {}))
    question = overrides.pop("question", question)
    return question, detail, payload


def test_can_fast_price_reply_positive() -> None:
    q, detail, payload = _price_payload()
    assert can_fast_price_reply(q, detail, payload)


def test_can_fast_price_reply_blocks_installment() -> None:
    q, detail, payload = _price_payload(question="iphone 17 pro max trả góp thế nào")
    assert not can_fast_price_reply(q, detail, payload)


def test_can_fast_price_reply_blocks_browse_list() -> None:
    q, detail, payload = _price_payload()
    detail["category_filter_list_mode"] = True
    assert not can_fast_price_reply(q, detail, payload)


def test_can_fast_price_reply_blocks_compare() -> None:
    q, detail, payload = _price_payload(payload={"compare_mode": True})
    assert not can_fast_price_reply(q, detail, payload)


def test_can_fast_price_reply_requires_price_and_id() -> None:
    q, detail, payload = _price_payload()
    payload["primary_product"] = {"name": "iPhone 17 Pro Max 1TB"}
    assert not can_fast_price_reply(q, detail, payload)


def test_build_price_reply_includes_price_promo_link() -> None:
    q, _, payload = _price_payload()
    answer = build_price_reply(q, payload, response_link_url="https://cellphones.com.vn/x.html")
    assert "45.990.000₫" in answer
    assert "SMem" in answer
    assert "Giảm thêm 500k" in answer
    assert "Còn hàng" in answer
    assert "https://cellphones.com.vn/x.html" in answer


if __name__ == "__main__":
    test_can_fast_price_reply_positive()
    test_can_fast_price_reply_blocks_installment()
    test_can_fast_price_reply_blocks_browse_list()
    test_can_fast_price_reply_blocks_compare()
    test_can_fast_price_reply_requires_price_and_id()
    test_build_price_reply_includes_price_promo_link()
    print("OK — fast price reply tests passed")
