"""
Fast-path trả góp 1 SP — template từ payload installment, không LLM.
"""
from __future__ import annotations

from typing import Any

_FAST_INSTALLMENT_BLOCKING_SCENARIOS = frozenset({
    "shop_stock",
    "trade_in",
    "warranty",
    "compare",
    "specs",
    "advice",
    "stock_browse",
    "budget_browse",
    "category_filter_browse",
    "reviews",
    "faq_policy",
    "flash_sale",
    "trade_in_device",
    "store_locator",
    "combo",
    "incoming_stock",
})

_PAY_LATER_LABELS = {
    "kredivo": "Kredivo",
    "fundiin": "Fundiin",
    "momo_vts": "Momo VTS",
}


def _format_package_line(pkg: dict[str, Any]) -> str:
    company = (pkg.get("company_name") or "").strip()
    if not company:
        return ""
    term = pkg.get("term_months")
    prepaid = (pkg.get("prepaid_amount_formatted") or "").strip()
    monthly = (pkg.get("monthly_payment_formatted") or "").strip()
    row = f"• *{company}*"
    if term:
        row += f" — {term} tháng"
    detail_bits: list[str] = []
    if prepaid:
        detail_bits.append(f"trả trước {prepaid}")
    if monthly:
        detail_bits.append(f"~{monthly}/tháng")
    if detail_bits:
        row += f" — {', '.join(detail_bits)}"
    return row


def _format_card_bank_section(card_block: dict[str, Any]) -> list[str]:
    """Chi tiết theo ngân hàng — dùng khi khách hỏi cụ thể thẻ/bank/kỳ."""
    lines: list[str] = []
    for summary in card_block.get("zero_fee_by_bank") or []:
        if not isinstance(summary, dict):
            continue
        amount_fmt = (summary.get("amount_formatted") or "").strip()
        for bank in summary.get("banks") or []:
            if not isinstance(bank, dict):
                continue
            bank_name = (
                bank.get("bank_display_name")
                or bank.get("short_name")
                or bank.get("bank_name")
                or ""
            ).strip()
            if not bank_name:
                continue
            for card in bank.get("cards") or []:
                if not isinstance(card, dict):
                    continue
                card_name = (card.get("card_name") or "").strip()
                periods = card.get("requested_term_periods") or card.get("zero_fee_periods") or []
                for period in periods[:3]:
                    if not isinstance(period, dict):
                        continue
                    term = period.get("term_months")
                    monthly = (period.get("monthly_payment_formatted") or "").strip()
                    row = f"• *{bank_name}*"
                    if card_name:
                        row += f" ({card_name})"
                    if term:
                        row += f" — {term} tháng"
                    if monthly:
                        row += f", ~{monthly}/tháng"
                    if amount_fmt:
                        row += f" (giá {amount_fmt})"
                    lines.append(row)
    return lines


def _format_credit_card_summary_by_term(card_block: dict[str, Any]) -> list[str]:
    """Gom theo kỳ hạn — không list từng ngân hàng."""
    lines: list[str] = []
    for row in card_block.get("zero_fee_by_term") or []:
        if not isinstance(row, dict):
            continue
        term = row.get("term_months")
        monthly = (row.get("monthly_payment_formatted") or "").strip()
        if term and monthly:
            lines.append(f"• {term} tháng — ~*{monthly}*/tháng")
    amount_fmt = (card_block.get("amount_formatted") or "").strip()
    if lines and amount_fmt:
        lines.append(f"_(Tham chiếu giá {amount_fmt}; Visa/Mastercard/JCB — các ngân hàng hỗ trợ tương tự.)_")
    elif not lines:
        methods = card_block.get("payment_methods") or []
        names = [
            (m.get("name") or m.get("code") or "").strip()
            for m in methods
            if isinstance(m, dict) and (m.get("name") or m.get("code"))
        ]
        if names:
            lines.append(f"• Hỗ trợ: {', '.join(names[:3])}")
    return lines


def _format_pay_later_section(pay_block: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    details = pay_block.get("details") or {}
    for code, detail in details.items():
        if not isinstance(detail, dict):
            continue
        label = _PAY_LATER_LABELS.get(str(code).lower(), str(code).upper())
        terms = detail.get("terms") or []
        if terms:
            term_lines: list[str] = []
            for term in terms[:4]:
                if not isinstance(term, dict):
                    continue
                months = term.get("term_months")
                monthly = (term.get("monthly_payment_formatted") or "").strip()
                rate = term.get("interest_rate")
                zero = term.get("is_zero_percent")
                if months and monthly:
                    suffix = " (0%)" if zero else (f" (lãi {rate}%)" if rate not in (None, "") else "")
                    term_lines.append(f"  - {months} tháng — ~{monthly}/tháng{suffix}")
            if term_lines:
                lines.append(f"• *{label}*")
                lines.extend(term_lines)
                continue
        lines.append(f"• *{label}* — có hỗ trợ trả góp")

    if not lines:
        for method in pay_block.get("payment_methods") or []:
            if not isinstance(method, dict):
                continue
            name = (method.get("name") or method.get("code") or "").strip()
            if name:
                lines.append(f"• {name}")
    return lines[:10]


def can_fast_installment_reply(
    user_question: str,
    detail: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """Trả góp 1 SP đã resolve — không so sánh/browse/clarification."""
    from cps_bot.cps.cps_api import classify_question_scenarios
    from cps_bot.cps.scraper import is_browse_list_mode

    if is_browse_list_mode(detail):
        return False
    if payload.get("compare_mode"):
        return False

    scenarios = classify_question_scenarios(user_question)
    if not scenarios.get("installment"):
        return False
    if any(scenarios.get(key) for key in _FAST_INSTALLMENT_BLOCKING_SCENARIOS):
        return False

    inst = payload.get("installment")
    if not isinstance(inst, dict):
        return False
    if inst.get("needs_clarification"):
        return False

    assessment = inst.get("query_assessment") or {}
    intent = assessment.get("intent") or "general"
    if intent == "credit_card_calculate":
        card = inst.get("credit_card") or {}
        return bool(card.get("zero_fee_by_bank"))
    if intent == "finance_calculate":
        finance = inst.get("finance_companies") or {}
        return bool(finance.get("calculated_packages"))
    if intent == "pay_later_calculate":
        pay = inst.get("pay_later") or {}
        return bool(pay.get("details"))

    if not inst.get("available"):
        return bool((inst.get("reason") or "").strip())

    finance = inst.get("finance_companies") or {}
    packages = finance.get("best_zero_percent_packages") or []
    lowest = inst.get("lowest_zero_prepaid")
    companies = finance.get("companies") or []
    card = inst.get("credit_card") or {}
    pay = inst.get("pay_later") or {}
    return bool(
        packages
        or lowest
        or companies
        or card.get("zero_fee_by_term")
        or pay.get("details")
    )


def build_installment_reply(
    user_question: str,
    payload: dict[str, Any],
    *,
    response_link_url: str = "",
) -> str:
    """Template trả góp — không qua LLM."""
    _ = user_question
    inst = payload.get("installment") or {}
    primary = payload.get("primary_product") or {}
    name = (
        (primary.get("name") or inst.get("product_name") or "Sản phẩm").split("|")[0].strip()
    )
    price = (primary.get("price") or inst.get("sale_price_formatted") or "").strip()

    lines: list[str] = [f"📱 *{name}* — trả góp"]
    if price:
        lines.append(f"💰 Giá tham chiếu: *{price}*")

    if not inst.get("available"):
        reason = (inst.get("reason") or "Không có thông tin trả góp cho sản phẩm này.").strip()
        lines.append("")
        lines.append(reason)
        link = response_link_url or primary.get("url") or ""
        if link:
            lines.append("")
            lines.append(f"🔗 Xem trên CellphoneS: {link}")
        return "\n".join(lines)

    assessment = inst.get("query_assessment") or {}
    intent = assessment.get("intent") or "general"
    finance = inst.get("finance_companies") or {}
    card_block = inst.get("credit_card") or {}
    pay_block = inst.get("pay_later") or {}

    lowest = inst.get("lowest_zero_prepaid") or {}
    packages = finance.get("best_zero_percent_packages") or []

    if lowest.get("amount_formatted") and intent in ("general", "lowest_prepaid"):
        lines.append("")
        lines.append("*1. Công ty tài chính — trả trước thấp nhất (0% lãi/tháng):*")
        pkg = lowest.get("package") if isinstance(lowest.get("package"), dict) else {}
        row = _format_package_line(pkg) if pkg else ""
        if row:
            lines.append(row)
        else:
            source = (lowest.get("source") or "").strip()
            amt = lowest["amount_formatted"]
            if source:
                lines.append(f"• {source} — trả trước *{amt}*")
            else:
                lines.append(f"• Trả trước thấp nhất: *{amt}*")

    if packages and intent in ("general", "lowest_prepaid"):
        if not lowest.get("amount_formatted"):
            lines.append("")
            lines.append("*1. Công ty tài chính (0% lãi/tháng):*")
        else:
            lines.append("")
            lines.append("*Các gói 0% khác:*")
        shown = 0
        for pkg in packages[:5]:
            if not isinstance(pkg, dict):
                continue
            row = _format_package_line(pkg)
            if row:
                lines.append(row)
                shown += 1
        if shown == 0:
            for co in (finance.get("companies") or [])[:5]:
                if not isinstance(co, dict):
                    continue
                co_name = (co.get("name") or "").strip()
                if co_name:
                    lines.append(f"• {co_name}")

    if intent == "finance_calculate":
        calculated = finance.get("calculated_packages") or []
        if calculated:
            lines.append("")
            lines.append("*Gói công ty tài chính (theo yêu cầu):*")
            for pkg in calculated[:4]:
                if isinstance(pkg, dict):
                    row = _format_package_line(pkg)
                    if row:
                        lines.append(row)

    if intent == "credit_card_calculate":
        card_lines = _format_card_bank_section(card_block)
        if card_lines:
            lines.append("")
            lines.append("*2. Trả góp qua thẻ tín dụng (phí chuyển đổi 0₫):*")
            lines.extend(card_lines[:8])
    elif intent in ("general", "lowest_prepaid"):
        card_lines = _format_credit_card_summary_by_term(card_block)
        if card_lines:
            lines.append("")
            lines.append("*2. Trả góp qua thẻ tín dụng (OnePay — phí chuyển đổi 0₫):*")
            lines.extend(card_lines)
            lines.append(
                "_Hỏi cụ thể ngân hàng + kỳ (vd: HSBC Visa 12 tháng) để xem chi tiết theo thẻ bạn._"
            )

    if intent == "pay_later_calculate":
        pay_lines = _format_pay_later_section(pay_block)
        if pay_lines:
            lines.append("")
            lines.append("*3. Mua trước trả sau:*")
            lines.extend(pay_lines)
    elif intent in ("general", "lowest_prepaid"):
        pay_lines = _format_pay_later_section(pay_block)
        if pay_lines:
            lines.append("")
            lines.append("*3. Mua trước trả sau:*")
            lines.extend(pay_lines)

    note = (inst.get("note") or finance.get("installment_note") or "").strip()
    if note:
        lines.append("")
        lines.append(f"_{note[:220]}_")

    link = response_link_url or primary.get("url") or ""
    if link:
        lines.append("")
        lines.append(f"🔗 Xem trên CellphoneS: {link}")
    return "\n".join(lines)
