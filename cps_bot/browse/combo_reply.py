"""
Fast-path phụ kiện / combo mua kèm 1 SP — template không LLM.
"""
from __future__ import annotations

from typing import Any

from cps_bot.cps.scraper import product_url_from_record

_FAST_COMBO_BLOCKING_SCENARIOS = frozenset({
    "shop_stock",
    "trade_in",
    "installment",
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
    "incoming_stock",
})


def _format_combo_line(combo: dict[str, Any]) -> str:
    name = (combo.get("name") or "").strip()
    if not name:
        return ""
    discount = combo.get("discount_percent")
    max_value = combo.get("max_value")
    row = f"• *{name}*"
    perks: list[str] = []
    if discount is not None:
        try:
            perks.append(f"giảm {int(float(discount))}%")
        except (TypeError, ValueError):
            perks.append(f"giảm {discount}%")
    if max_value is not None:
        try:
            val = int(max_value)
            perks.append(f"tối đa {val:,}₫".replace(",", "."))
        except (TypeError, ValueError):
            perks.append(f"tối đa {max_value}")
    if perks:
        row += f" — {', '.join(perks)}"
    return row


def _format_recommended_line(item: dict[str, Any]) -> str:
    name = (item.get("name") or "").strip()
    if not name:
        return ""
    price = (item.get("price") or "").strip()
    stock = (item.get("stock_status") or "").strip()
    url = product_url_from_record(item)
    row = f"• *{name}*"
    if price:
        row += f" — {price}"
    if stock:
        row += f" ({stock})"
    if url:
        row += f"\n  {url}"
    return row


def can_fast_combo_reply(
    user_question: str,
    detail: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """Combo/phụ kiện mua kèm 1 SP đã resolve — không LLM."""
    from cps_bot.cps.cps_api import classify_question_scenarios, is_combo_accessory_query
    from cps_bot.cps.scraper import is_browse_list_mode

    if not is_combo_accessory_query(user_question):
        return False
    if is_browse_list_mode(detail):
        return False
    if payload.get("compare_mode"):
        return False

    scenarios = classify_question_scenarios(user_question)
    if not scenarios.get("combo"):
        return False
    if any(scenarios.get(key) for key in _FAST_COMBO_BLOCKING_SCENARIOS):
        return False

    primary = payload.get("primary_product") or detail or {}
    if not (primary.get("name") or "").strip():
        return False
    if not primary.get("product_id"):
        return False

    included = (primary.get("included_accessories") or "").strip()
    combos = payload.get("product_combos") or []
    recommended = payload.get("recommended_products") or []
    return bool(included or combos or recommended)


def build_combo_reply(
    user_question: str,
    payload: dict[str, Any],
    *,
    response_link_url: str = "",
) -> str:
    """Template phụ kiện/combo mua kèm — không qua LLM."""
    _ = user_question
    primary = payload.get("primary_product") or {}
    name = (primary.get("name") or "Sản phẩm").split("|")[0].strip()

    lines: list[str] = [f"📱 *{name}* — phụ kiện & mua kèm"]

    included = (primary.get("included_accessories") or "").strip()
    if included:
        lines.append("")
        lines.append("*Phụ kiện trong hộp:*")
        for chunk in included.split(";"):
            chunk = chunk.strip()
            if chunk:
                lines.append(f"• {chunk[:180]}")

    combos = payload.get("product_combos") or []
    combo_lines = [_format_combo_line(item) for item in combos[:6] if isinstance(item, dict)]
    combo_lines = [row for row in combo_lines if row]
    if combo_lines:
        lines.append("")
        lines.append("*Gói combo mua kèm (giảm thêm):*")
        lines.extend(combo_lines)

    recommended = payload.get("recommended_products") or []
    rec_lines = [
        _format_recommended_line(item)
        for item in recommended[:8]
        if isinstance(item, dict)
    ]
    rec_lines = [row for row in rec_lines if row]
    if rec_lines:
        lines.append("")
        lines.append("*Gợi ý phụ kiện mua cùng trên CellphoneS:*")
        lines.extend(rec_lines)

    if len(lines) == 1:
        lines.append("")
        lines.append(
            "Hiện chưa có danh sách phụ kiện/combo chi tiết — "
            "bạn xem thêm trên trang sản phẩm nhé."
        )

    link = response_link_url or primary.get("url") or ""
    if link:
        lines.append("")
        lines.append(f"🔗 Xem trên CellphoneS: {link}")
    return "\n".join(lines)
