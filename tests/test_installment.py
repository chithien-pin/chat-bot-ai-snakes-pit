"""Test API trả góp — onepay v3 + payment-installment/info."""
from __future__ import annotations

import asyncio

from cps_bot.cps.cps_installment import (
    _parse_card_period_rows,
    _parse_credit_card_banks,
    _summarize_installment_info,
    assess_installment_query,
    build_onepay_catalog,
    extract_installment_hints,
    resolve_bank_swifts,
    wants_credit_card_installment,
)

_SAMPLE_ONEPAY_INFO = {
    "payment_methods": [
        {
            "code": "onepay",
            "information": {
                "list_bank": [
                    {
                        "code": "VTCBVNVX",
                        "short_name": "TechcomBank",
                        "full_name": "NH TMCP Kỹ Thương Việt Nam",
                    },
                    {
                        "code": "VNIBVNVX",
                        "short_name": "VIB",
                        "full_name": "NH Quốc Tế",
                    },
                    {
                        "code": "BFTVVNVX",
                        "short_name": "VietcomBank",
                        "full_name": "NH TMCP Ngoại Thương Việt Nam",
                    },
                ],
                "list_card": [
                    {"code": "Visa", "name": "Visa", "type": "VC"},
                    {"code": "Mastercard", "name": "Mastercard", "type": "MC"},
                    {"code": "JCB", "name": "JCB", "type": "JC"},
                ],
            },
        }
    ]
}


def _sample_catalog() -> dict:
    catalog = build_onepay_catalog(_SAMPLE_ONEPAY_INFO)
    assert catalog is not None
    return catalog


def test_parse_card_period_rows_includes_paid_terms() -> None:
    card = {
        "name": "Visa",
        "times": [
            {"fee_amount": 0, "monthly_amount": 5000000, "time": 6},
            {"fee_amount": 1130172, "monthly_amount": 1385014, "time": 12},
        ],
    }
    all_rows = _parse_card_period_rows(card, zero_fee_only=False)
    zero_rows = _parse_card_period_rows(card, zero_fee_only=True)
    assert len(all_rows) == 2
    assert len(zero_rows) == 1
    term12 = next(r for r in all_rows if r["term_months"] == 12)
    assert term12["fee_amount"] == 1130172
    assert term12["is_zero_fee"] is False


def test_parse_onepay_times_format() -> None:
    card = {
        "name": "Visa",
        "times": [
            {"fee_amount": 0, "monthly_amount": 7916667, "time": 3},
            {"fee_amount": 0, "monthly_amount": 3958333, "time": 6},
            {"fee_amount": 1041232, "monthly_amount": 2754581, "time": 9},
        ],
    }
    rows = _parse_card_period_rows(card)
    assert len(rows) == 2
    assert rows[0]["term_months"] == 3
    assert rows[0]["monthly_payment"] == 7916667


def test_build_onepay_catalog_from_info() -> None:
    catalog = _sample_catalog()
    assert "VTCBVNVX" in catalog["banks_by_swift"]
    assert catalog["banks_by_swift"]["VTCBVNVX"]["short_name"] == "TechcomBank"
    assert "Visa" in catalog["cards_by_code"]
    assert catalog["cards_by_code"]["Visa"]["type"] == "VC"


def test_resolve_bank_swifts_from_list_bank() -> None:
    catalog = _sample_catalog()
    tcb = resolve_bank_swifts("TCB", catalog)
    assert tcb == {"VTCBVNVX"}
    vib = resolve_bank_swifts("vib", catalog)
    assert vib == {"VNIBVNVX"}
    tech = resolve_bank_swifts("techcombank", catalog)
    assert tech == {"VTCBVNVX"}


def test_parse_credit_card_banks_vib_with_catalog() -> None:
    catalog = _sample_catalog()
    response = {
        "VNIBVNVX": {
            "bank_id": "VNIBVNVX",
            "bank_name": "",
            "listCards": {
                "Visa": {
                    "name": "Visa",
                    "type": "VC",
                    "times": [
                        {"fee_amount": 0, "monthly_amount": 5000000, "time": 6},
                    ],
                },
            },
        }
    }
    banks = _parse_credit_card_banks(response, bank_filter="VIB", catalog=catalog)
    assert len(banks) == 1
    assert banks[0]["short_name"] == "VIB"
    assert banks[0]["bank_display_name"] == "VIB"
    assert banks[0]["cards"][0]["card_name"] == "Visa"
    assert banks[0]["cards"][0]["card_type"] == "VC"
    assert banks[0]["zero_fee_periods"][0]["term_months"] == 6


def test_parse_credit_card_banks_techcombank_visa_6_months() -> None:
    catalog = _sample_catalog()
    response = {
        "VTCBVNVX": {
            "bank_id": "VTCBVNVX",
            "listCards": {
                "Visa": {
                    "name": "Visa",
                    "type": "VC",
                    "times": [
                        {"fee_amount": 0, "monthly_amount": 6915000, "time": 6},
                    ],
                },
                "Mastercard": {
                    "name": "Mastercard",
                    "type": "MC",
                    "times": [
                        {"fee_amount": 0, "monthly_amount": 6915000, "time": 6},
                    ],
                },
            },
        },
        "BFTVVNVX": {
            "bank_id": "BFTVVNVX",
            "listCards": {
                "Visa": {
                    "name": "Visa",
                    "type": "VC",
                    "times": [
                        {"fee_amount": 0, "monthly_amount": 6915000, "time": 6},
                    ],
                },
            },
        },
    }
    banks = _parse_credit_card_banks(
        response,
        bank_filter="TCB",
        card_filter="Visa",
        term_months=6,
        catalog=catalog,
    )
    assert len(banks) == 1
    assert banks[0]["short_name"] == "TechcomBank"
    assert banks[0]["cards"][0]["card_name"] == "Visa"
    assert banks[0]["requested_term_periods"][0]["monthly_payment"] == 6915000


def test_summarize_installment_info() -> None:
    raw = {
        "companies": [
            {
                "key": "home_credit",
                "name": "Home Credit",
                "is_active": True,
                "term_in_months": [6, 12],
                "min_prepaid_percent": 0,
                "information": {"default_term": 6, "required_documents": "<p>CCCD</p>"},
            }
        ],
        "payment_methods": [
            {
                "code": "onepay",
                "title": "Trả góp qua Onepay",
                "min_installment_amount": 3000000,
                "information": _SAMPLE_ONEPAY_INFO["payment_methods"][0]["information"],
            }
        ],
    }
    summary = _summarize_installment_info(raw)
    assert len(summary["finance_companies_catalog"]) == 1
    assert summary["onepay"]["list_bank"][0]["short_name"] == "TechcomBank"
    assert summary["onepay"]["list_card"][0]["code"] == "Visa"


def test_credit_card_query_hints() -> None:
    hints = extract_installment_hints("iphone trả góp qua thẻ VIB được không")
    assert hints.get("bank") == "VIB"
    assert hints.get("credit_card") == "1"
    assert wants_credit_card_installment(hints, "iphone trả góp qua thẻ VIB được không")

    tcb_hints = extract_installment_hints("thông tin trả góp 6 tháng qua thẻ techcombank visa")
    assert tcb_hints.get("bank") == "TCB"
    assert tcb_hints.get("term_months") == "6"
    assert tcb_hints.get("card_type") == "Visa"


def test_assess_installment_query_incomplete_credit_card() -> None:
    catalog = _sample_catalog()
    hints = extract_installment_hints("trả góp qua thẻ tín dụng")
    result = assess_installment_query("trả góp qua thẻ tín dụng", hints, catalog=catalog)
    assert result["needs_clarification"]
    assert "bank" in result["missing_fields"]
    assert "clarification_message" in result


def test_assess_installment_query_partial_bank_only() -> None:
    catalog = _sample_catalog()
    hints = extract_installment_hints("trả góp techcombank 6 tháng")
    result = assess_installment_query("trả góp techcombank 6 tháng", hints, catalog=catalog)
    assert result["needs_clarification"]
    assert result["missing_fields"] == ["card_type"]


def test_assess_installment_query_complete_tcb_visa_6() -> None:
    catalog = _sample_catalog()
    q = "trả góp techcombank visa 6 tháng"
    hints = extract_installment_hints(q)
    result = assess_installment_query(q, hints, catalog=catalog)
    assert result["complete"]
    assert not result["needs_clarification"]


def test_assess_installment_query_complete_hsbc_visa_12() -> None:
    catalog = _sample_catalog()
    q = "hsbc 12 tháng VISA"
    hints = extract_installment_hints(q)
    result = assess_installment_query(q, hints, catalog=catalog)
    assert result["complete"]
    assert hints.get("bank") == "HSBC"
    assert hints.get("card_type") == "Visa"
    assert hints.get("term_months") == "12"


def test_is_installment_query_bank_card_term() -> None:
    from cps_bot.cps.cps_installment import is_installment_query

    assert is_installment_query("hsbc 12 tháng VISA")
    assert is_installment_query("trả góp techcombank visa 6 tháng")
    assert not is_installment_query("giá bao nhiêu")


def test_fetch_installment_info_live() -> None:
    async def _run() -> None:
        from cps_bot.cps.cps_installment import fetch_installment_info

        data = await fetch_installment_info()
        assert data is not None
        catalog = build_onepay_catalog(data)
        assert catalog is not None
        assert len(catalog.get("list_bank") or []) >= 20
        assert len(catalog.get("list_card") or []) >= 3
        summary = _summarize_installment_info(data)
        assert summary.get("onepay")
        assert any(
            m.get("code") == "onepay"
            for m in (summary.get("payment_methods_catalog") or [])
        )

    asyncio.run(_run())
