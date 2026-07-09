"""
Fast-path so sánh 2 sản phẩm — template không LLM + nội dung cột Lark.
"""
from __future__ import annotations

import re
from typing import Any

from cps_bot.cps.scraper import product_url_from_record
from cps_bot.llm.answer_guard import parse_price_to_vnd

_COMPARE_BLOCKING_SCENARIOS = frozenset({
    "trade_in",
    "installment",
    "warranty",
    "specs",
    "advice",
    "reviews",
    "faq_policy",
    "flash_sale",
    "trade_in_device",
    "store_locator",
    "combo",
    "incoming_stock",
    "budget_browse",
    "category_filter_browse",
    "stock_browse",
    "shop_stock",
    "price_promotion",
})

_COMPARE_SPEC_PRIORITY = (
    "màn hình",
    "man hinh",
    "chip",
    "cpu",
    "ram",
    "bộ nhớ",
    "bo nho",
    "rom",
    "camera sau",
    "camera trước",
    "camera",
    "pin",
    "sạc",
    "sac",
    "hệ điều hành",
    "he dieu hanh",
    "kích thước",
    "kich thuoc",
    "trọng lượng",
    "trong luong",
)


def can_fast_compare_reply(
    user_question: str,
    detail: dict[str, Any],
    payload: dict[str, Any],
) -> bool:
    """So sánh 2 SP đã resolve — không LLM."""
    from cps_bot.cps.cps_api import classify_question_scenarios
    from cps_bot.cps.scraper import is_browse_list_mode

    if not payload.get("compare_mode"):
        return False
    if is_browse_list_mode(detail):
        return False

    products = payload.get("compare_products") or []
    if len(products) < 2:
        return False

    scenarios = classify_question_scenarios(user_question)
    if not scenarios.get("compare"):
        return False
    if any(scenarios.get(key) for key in _COMPARE_BLOCKING_SCENARIOS):
        return False

    for product in products[:2]:
        if not isinstance(product, dict):
            return False
        if not (product.get("name") or "").strip():
            return False
    return True


def pick_compare_specs(product: dict[str, Any], *, limit: int = 7) -> list[tuple[str, str]]:
    specs = product.get("specifications") or {}
    if not isinstance(specs, dict):
        return []

    picked: list[tuple[str, str]] = []
    used: set[str] = set()

    for hint in _COMPARE_SPEC_PRIORITY:
        for label, value in specs.items():
            if not label or not value or label in used:
                continue
            if hint in label.lower():
                picked.append((str(label), str(value)))
                used.add(str(label))
                break
        if len(picked) >= limit:
            return picked[:limit]

    for label, value in specs.items():
        if label in used or not value:
            continue
        picked.append((str(label), str(value)))
        if len(picked) >= limit:
            break
    return picked[:limit]


def _member_price_line(product: dict[str, Any]) -> str:
    for tier in product.get("member_prices") or []:
        if not isinstance(tier, dict):
            continue
        label = (tier.get("label") or tier.get("tier") or "").strip()
        price = (tier.get("price_formatted") or tier.get("price") or "").strip()
        if label and price and "smember" in label.lower():
            return f"👤 {label}: **{price}**"
    return ""


def _product_price_vnd(product: dict[str, Any]) -> int | None:
    raw = product.get("price_value")
    if raw is not None:
        try:
            value = int(raw)
            return value if value > 0 else None
        except (TypeError, ValueError):
            pass
    return parse_price_to_vnd(str(product.get("price") or ""))


def _short_name(product: dict[str, Any]) -> str:
    name = (product.get("name") or "Sản phẩm").strip()
    return name if len(name) <= 36 else name[:33] + "…"


def _stock_available(product: dict[str, Any]) -> bool | None:
    stock = (product.get("stock_status") or "").strip().lower()
    if not stock:
        return None
    if any(x in stock for x in ("hết hàng", "het hang", "tạm hết", "tam het", "ngừng")):
        return False
    if any(x in stock for x in ("còn hàng", "con hang", "sẵn hàng", "san hang")):
        return True
    return None


def _spec_text(product: dict[str, Any], *hints: str) -> str:
    specs = product.get("specifications") or {}
    if not isinstance(specs, dict):
        return ""
    for hint in hints:
        hint_l = hint.lower()
        for label, value in specs.items():
            if hint_l in str(label).lower() and value:
                return str(value).strip()
    return ""


def _extract_gb(text: str) -> int | None:
    match = re.search(r"(\d+)\s*gb", text.lower())
    return int(match.group(1)) if match else None


def _extract_mah(text: str) -> int | None:
    match = re.search(r"(\d+)\s*mah", text.lower())
    return int(match.group(1)) if match else None


def build_compare_advice(products: list[dict[str, Any]]) -> str:
    """Gợi ý ngắn giúp user chọn SP — rule-based, không LLM."""
    if len(products) < 2:
        return ""

    left, right = products[0], products[1]
    left_name, right_name = _short_name(left), _short_name(right)
    tips: list[str] = []

    left_price = _product_price_vnd(left)
    right_price = _product_price_vnd(right)
    if left_price and right_price and left_price != right_price:
        diff = abs(left_price - right_price)
        if diff >= 200_000:
            cheaper = left if left_price < right_price else right
            cheaper_name = _short_name(cheaper)
            if diff >= 1_000_000:
                diff_text = f"{diff / 1_000_000:.1f}".rstrip("0").rstrip(".") + " triệu"
            else:
                diff_text = f"{diff // 1000}k"
            tips.append(
                f"**{cheaper_name}** rẻ hơn ~{diff_text} — hợp nếu ưu tiên tiết kiệm."
            )

    left_stock = _stock_available(left)
    right_stock = _stock_available(right)
    if left_stock is False and right_stock is not False:
        tips.append(f"**{right_name}** đang còn hàng — **{left_name}** tạm hết, có thể chọn {right_name} để mua ngay.")
    elif right_stock is False and left_stock is not False:
        tips.append(f"**{left_name}** đang còn hàng — **{right_name}** tạm hết, có thể chọn {left_name} để mua ngay.")

    left_ram = _extract_gb(_spec_text(left, "ram"))
    right_ram = _extract_gb(_spec_text(right, "ram"))
    if left_ram and right_ram and left_ram != right_ram:
        better = left if left_ram > right_ram else right
        tips.append(
            f"**{_short_name(better)}** RAM {max(left_ram, right_ram)} GB — mượt hơn khi mở nhiều app."
        )

    left_pin = _extract_mah(_spec_text(left, "pin", "dung lượng pin"))
    right_pin = _extract_mah(_spec_text(right, "pin", "dung lượng pin"))
    if left_pin and right_pin and abs(left_pin - right_pin) >= 200:
        better = left if left_pin > right_pin else right
        tips.append(
            f"**{_short_name(better)}** pin {max(left_pin, right_pin)} mAh — trụ pin lâu hơn nếu dùng nhiều."
        )

    left_rom = _extract_gb(_spec_text(left, "bộ nhớ", "bo nho", "rom"))
    right_rom = _extract_gb(_spec_text(right, "bộ nhớ", "bo nho", "rom"))
    if left_rom and right_rom and left_rom != right_rom:
        better = left if left_rom > right_rom else right
        tips.append(
            f"**{_short_name(better)}** bộ nhớ {max(left_rom, right_rom)} GB — thoải mái hơn khi chụp ảnh/quay video."
        )

    left_promo = (left.get("promotion_info") or "").strip()
    right_promo = (right.get("promotion_info") or "").strip()
    if left_promo and not right_promo:
        tips.append(f"**{left_name}** đang có KM — xem thêm ở cột bên trái nếu quan tâm ưu đãi.")
    elif right_promo and not left_promo:
        tips.append(f"**{right_name}** đang có KM — xem thêm ở cột bên phải nếu quan tâm ưu đãi.")

    if not tips:
        tips.append(
            "Hai máy khá cân sức — cân nhắc giá, pin và KM đang chạy trước khi quyết định."
        )

    closing = (
        "Bạn ưu tiên **giá rẻ**, **pin trâu** hay **hiệu năng**? "
        "Hỏi thêm để mình gợi ý chi tiết hơn nhé!"
    )
    shown = tips[:4] + [closing]
    body = "\n".join(f"• {tip}" for tip in shown)
    return f"💡 **Gợi ý chọn máy:**\n{body}"


def build_compare_summary(
    products: list[dict[str, Any]],
    *,
    fast: bool = True,
) -> str:
    """Intro + gợi ý — dùng cho Lark card compare."""
    intro = (
        "⚖️ So sánh nhanh 2 sản phẩm CellphoneS"
        if fast
        else "⚖️ So sánh sản phẩm"
    )
    advice = build_compare_advice(products)
    return f"{intro}\n\n{advice}" if advice else intro


def format_compare_product_lark_md(product: dict[str, Any]) -> str:
    """Nội dung 1 cột so sánh — Lark markdown."""
    name = (product.get("name") or "Sản phẩm").strip()
    lines: list[str] = [f"**{name}**", ""]

    price = (product.get("price") or "").strip()
    old_price = (product.get("old_price") or "").strip()
    if price:
        lines.append(f"💰 **{price}**")
    if old_price and old_price != price:
        lines.append(f"~~{old_price}~~")

    member = _member_price_line(product)
    if member:
        lines.append(member)

    stock = (product.get("stock_status") or "").strip()
    if stock:
        lines.append(f"📦 {stock}")

    specs = pick_compare_specs(product)
    if specs:
        lines.append("")
        lines.append("**Thông số:**")
        for label, value in specs:
            short_val = value if len(value) <= 80 else value[:77] + "…"
            lines.append(f"• {label}: {short_val}")

    promo = (product.get("promotion_info") or "").strip()
    if promo:
        lines.append("")
        lines.append(f"🎁 {promo[:120]}{'…' if len(promo) > 120 else ''}")

    return "\n".join(lines)


def format_compare_product_plain(product: dict[str, Any]) -> str:
    """Fallback text — Telegram / web chat."""
    body = format_compare_product_lark_md(product)
    link = product_url_from_record(product) or (product.get("url") or "")
    if link:
        body += f"\n\n🔗 {link}"
    return body


def build_compare_reply(
    user_question: str,
    payload: dict[str, Any],
    *,
    response_link_url: str = "",
) -> str:
    """Template so sánh 2 cột (plain text) — Lark dùng card riêng."""
    _ = user_question
    products = payload.get("compare_products") or []
    if len(products) < 2:
        return "😔 Chưa đủ dữ liệu để so sánh 2 sản phẩm."

    left = format_compare_product_plain(products[0])
    right = format_compare_product_plain(products[1])
    advice = build_compare_advice(products)
    lines = [
        "⚖️ **So sánh sản phẩm**",
        "",
    ]
    if advice:
        lines.extend([advice, ""])
    lines.extend([
        f"📱 **Cột 1**\n{left}",
        "",
        "────────────",
        "",
        f"📱 **Cột 2**\n{right}",
    ])
    if response_link_url:
        lines.extend(["", f"🔗 Xem thêm: {response_link_url}"])
    return "\n".join(lines)
