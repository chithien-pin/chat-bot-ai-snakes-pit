"""Test fast installment reply — template trả góp không qua LLM."""
from __future__ import annotations

from cps_bot.browse.installment_reply import build_installment_reply, can_fast_installment_reply
from cps_bot.llm.query_router import resolve_query_route


def _installment_payload(**overrides) -> tuple[str, dict, dict]:
    question = "Trả góp Galaxy A17 5G ưu đãi nhất"
    detail = {
        "product_id": 12345,
        "name": "Samsung Galaxy A17 5G",
        "price": "5.990.000₫",
    }
    payload = {
        "primary_product": {
            "product_id": 12345,
            "name": "Samsung Galaxy A17 5G | Chính hãng",
            "price": "5.990.000₫",
            "url": "https://cellphones.com.vn/samsung-galaxy-a17-5g.html",
        },
        "installment": {
            "available": True,
            "product_name": "Samsung Galaxy A17 5G",
            "sale_price_formatted": "5.990.000₫",
            "query_assessment": {
                "intent": "lowest_prepaid",
                "complete": True,
                "needs_clarification": False,
            },
            "lowest_zero_prepaid": {
                "amount": 1198000,
                "amount_formatted": "1.198.000₫",
                "source": "Home Credit 6 tháng (0%/tháng)",
                "package": {
                    "company_name": "Home Credit",
                    "term_months": 6,
                    "prepaid_amount_formatted": "1.198.000₫",
                    "monthly_payment_formatted": "798.000₫",
                },
            },
            "finance_companies": {
                "best_zero_percent_packages": [
                    {
                        "company_name": "Home Credit",
                        "term_months": 6,
                        "prepaid_amount_formatted": "1.198.000₫",
                        "monthly_payment_formatted": "798.000₫",
                    },
                    {
                        "company_name": "FE Credit",
                        "term_months": 6,
                        "prepaid_amount_formatted": "1.198.000₫",
                        "monthly_payment_formatted": "798.000₫",
                    },
                ],
            },
            "note": "Giá trả góp tham chiếu API payment-installment CellphoneS.",
        },
    }
    payload.update(overrides.pop("payload", {}))
    detail.update(overrides.pop("detail", {}))
    question = overrides.pop("question", question)
    inst = payload.get("installment")
    if isinstance(inst, dict):
        inst.update(overrides.pop("installment", {}))
    return question, detail, payload


def test_can_fast_installment_reply_positive() -> None:
    q, detail, payload = _installment_payload()
    assert can_fast_installment_reply(q, detail, payload)


def test_can_fast_installment_reply_blocks_compare() -> None:
    q, detail, payload = _installment_payload(payload={"compare_mode": True})
    assert not can_fast_installment_reply(q, detail, payload)


def test_can_fast_installment_reply_blocks_clarification() -> None:
    q, detail, payload = _installment_payload(
        question="trả góp thẻ HSBC Galaxy A17",
        installment={
            "needs_clarification": True,
            "query_assessment": {
                "intent": "credit_card_calculate",
                "complete": False,
                "needs_clarification": True,
            },
        },
    )
    assert not can_fast_installment_reply(q, detail, payload)


def test_can_fast_installment_reply_unavailable_with_reason() -> None:
    q, detail, payload = _installment_payload(
        installment={
            "available": False,
            "reason": "Sản phẩm không hỗ trợ trả góp trên CellphoneS.",
            "query_assessment": {"intent": "general", "complete": True},
        },
    )
    assert can_fast_installment_reply(q, detail, payload)


def test_build_installment_reply_includes_packages_and_link() -> None:
    q, _, payload = _installment_payload()
    answer = build_installment_reply(
        q,
        payload,
        response_link_url="https://cellphones.com.vn/samsung-galaxy-a17-5g.html",
    )
    assert "Samsung Galaxy A17 5G" in answer
    assert "5.990.000₫" in answer
    assert "Home Credit" in answer
    assert "1.198.000₫" in answer
    assert "798.000₫" in answer
    assert "cellphones.com.vn" in answer


def test_query_router_installment_query_skips_llm() -> None:
    route = resolve_query_route("Trả góp Galaxy A17 5G ưu đãi nhất", use_llm=False)
    assert route.mode == "product_search"
    assert route.confidence >= 0.9
    assert route.source == "rule"
    assert "galaxy" in route.search_keywords.lower()


if __name__ == "__main__":
    test_can_fast_installment_reply_positive()
    test_can_fast_installment_reply_blocks_compare()
    test_can_fast_installment_reply_blocks_clarification()
    test_can_fast_installment_reply_unavailable_with_reason()
    test_build_installment_reply_includes_packages_and_link()
    test_query_router_installment_query_skips_llm()
    print("OK — fast installment reply tests passed")
