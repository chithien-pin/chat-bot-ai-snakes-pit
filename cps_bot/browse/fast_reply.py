"""
Trả lời nhanh không qua LLM — browse danh sách SP (category filter, budget, stock).
Mục tiêu: < 3s (chỉ fetch CPS + format text).
"""
from __future__ import annotations

from typing import Any

from cps_bot.cps.scraper import category_browse_url, format_product_links_appendix, product_url_from_record


def _color_label_from_name(name: str) -> str:
    text = (name or "").strip()
    if "-" in text:
        return text.rsplit("-", 1)[-1].strip()
    return text


def can_fast_color_sibling_reply(
    payload: dict[str, Any],
    user_question: str = "",
) -> bool:
    from cps_bot.cps.cps_api import is_color_variant_list_query

    ctx = payload.get("color_sibling_variants") or {}
    if not is_color_variant_list_query(user_question):
        return False
    try:
        return int(ctx.get("count") or 0) > 1 and bool(ctx.get("variants"))
    except (TypeError, ValueError):
        return False


def build_color_sibling_reply(
    user_question: str,
    payload: dict[str, Any],
    *,
    response_link_url: str = "",
) -> str:
    """Liệt kê màu sibling — không qua LLM (tránh slim payload làm mất dữ liệu)."""
    ctx = payload.get("color_sibling_variants") or {}
    variants = ctx.get("variants") or []
    current_id = str(ctx.get("current_product_id") or "")
    primary = payload.get("primary_product") or {}
    base_name = (primary.get("name") or "").split("|")[0].strip()
    if not base_name and variants:
        base_name = (variants[0].get("name") or "").split("|")[0].strip()

    lines: list[str] = []
    if base_name:
        lines.append(f"📱 *{base_name}* — các màu đang có trên CellphoneS:")
    else:
        lines.append("📱 Các màu đang có trên CellphoneS:")

    for item in variants:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("product_id") or "")
        color = _color_label_from_name(str(item.get("name") or ""))
        price = (item.get("price") or "").strip()
        stock = (item.get("stock_status") or "").strip()
        row = f"• *{color}*"
        if price:
            row += f" — {price}"
        if stock:
            row += f" ({stock})"
        if pid and pid == current_id:
            row += " ← màu bạn đang xem"
        lines.append(row)

    link = response_link_url or primary.get("url") or ""
    if link:
        lines.append("")
        lines.append(f"🔗 Xem thêm: {link}")
    return "\n".join(lines)


def can_fast_browse_reply(detail: dict[str, Any], search_results: list[dict[str, Any]]) -> bool:
    if not search_results:
        return False
    return bool(
        detail.get("category_filter_list_mode")
        or detail.get("budget_browse_list_mode")
        or detail.get("stock_browse_list_mode")
    )


def build_browse_list_reply(
    user_question: str,
    detail: dict[str, Any],
    search_results: list[dict[str, Any]],
    *,
    response_link_url: str = "",
) -> str:
    """Template tiếng Việt — liệt kê SP từ search_results, không gọi LLM."""
    count = int(detail.get("product_count") or len(search_results))
    lines: list[str] = []

    if detail.get("category_filter_list_mode"):
        label = detail.get("category_filter_name") or detail.get("name") or "danh mục"
        matched = detail.get("category_filter_matched") or []
        filters = ", ".join(
            ", ".join(item.get("labels") or [])
            for item in matched
            if item.get("labels")
        )
        intro = f"📱 *{label}*"
        if filters:
            intro += f" — lọc: {filters}"
        lines.append(intro)
        lines.append(f"Có *{count}* sản phẩm phù hợp câu hỏi của bạn.")
    elif detail.get("budget_browse_list_mode"):
        budget = detail.get("budget_label") or ""
        cat = detail.get("budget_category") or "sản phẩm"
        lines.append(f"💰 *{cat.title()}* {budget}".strip())
        lines.append(f"Tìm thấy *{count}* sản phẩm trong tầm giá.")
    elif detail.get("stock_browse_list_mode"):
        lines.append("📦 Danh sách sản phẩm theo trạng thái tồn:")
        lines.append(f"Có *{count}* sản phẩm.")

    lines.append("")
    lines.append("*Gợi ý:*")
    for idx, item in enumerate(search_results[:8], start=1):
        name = (item.get("name") or "Sản phẩm").strip()
        price = (item.get("price") or "").strip()
        stock = (item.get("stock_status") or "").strip()
        row = f"{idx}. {name}"
        if price:
            row += f" — {price}"
        if stock:
            row += f" ({stock})"
        lines.append(row)

    list_url = response_link_url or detail.get("category_filter_url") or detail.get("url") or ""
    if list_url:
        full = category_browse_url(list_url) if not str(list_url).startswith("http") else list_url
        lines.append("")
        lines.append(f"🔗 Xem đầy đủ: {full}")

    appendix = format_product_links_appendix(search_results, max_items=8)
    body = "\n".join(lines)
    if appendix and appendix not in body:
        body = f"{body}{appendix}"
    return body


def slim_payload_for_llm(payload: dict[str, Any], *, max_results: int = 5) -> dict[str, Any]:
    """Giảm token gửi LLM — chỉ giữ trường cần trả lời."""
    slim: dict[str, Any] = {}

    results = payload.get("search_results") or []
    slim_results = []
    for item in results[:max_results]:
        if not isinstance(item, dict):
            continue
        slim_results.append(
            {
                k: item[k]
                for k in ("name", "price", "url", "stock_status", "product_id")
                if item.get(k)
            }
        )
    if slim_results:
        slim["search_results"] = slim_results

    primary = payload.get("primary_product") or {}
    if primary:
        keep = (
            "name",
            "price",
            "old_price",
            "url",
            "stock_status",
            "stock_available_id",
            "stock_quantity",
            "product_id",
            "specifications",
            "member_prices",
            "promotions",
            "description",
        )
        slim_primary = {k: primary[k] for k in keep if primary.get(k)}
        if slim_primary:
            slim["primary_product"] = slim_primary

    for key in (
        "compare_mode",
        "compare_products",
        "shop_stock",
        "online_stock",
        "question_scenarios",
        "browse_list_mode",
        "browse_product_count",
        "color_sibling_variants",
        "trade_promo",
        "installment",
        "extended_warranty",
        "instock_other_provinces",
        "recommended_products",
        "similar_products",
    ):
        if payload.get(key):
            slim[key] = payload[key]

    return slim if slim else payload
