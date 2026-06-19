"""
Disambiguation — gợi ý chọn SP khi search mơ hồ.
"""
from __future__ import annotations

from typing import Any

from scraper import format_product_links_appendix, product_url_from_record


def build_disambiguation_message(
    search_results: list[dict[str, Any]],
    *,
    max_items: int = 3,
) -> str:
    """Tạo tin nhắn gợi ý chọn 1 trong N sản phẩm."""
    items = search_results[:max_items]
    if len(items) < 2:
        return ""
    lines = ["🤔 Tìm thấy nhiều sản phẩm — bạn muốn hỏi về sản phẩm nào?\n"]
    for idx, item in enumerate(items, start=1):
        name = item.get("name") or "Sản phẩm"
        price = item.get("price") or ""
        url = product_url_from_record(item)
        line = f"{idx}. {name}"
        if price:
            line += f" — {price}"
        if url:
            line += f"\n   {url}"
        lines.append(line)
    lines.append("\nGõ số thứ tự hoặc tên cụ thể hơn (vd: màu, dung lượng).")
    return "\n".join(lines)


def build_telegram_disambiguation_keyboard(
    search_results: list[dict[str, Any]],
    *,
    max_items: int = 3,
) -> list[list[dict[str, str]]]:
    """Inline keyboard Telegram — callback_data disambig:0, disambig:1, ..."""
    from telegram import InlineKeyboardButton

    rows: list[list[InlineKeyboardButton]] = []
    for idx, item in enumerate(search_results[:max_items]):
        name = (item.get("name") or "SP")[:40]
        rows.append(
            [InlineKeyboardButton(f"{idx + 1}. {name}", callback_data=f"disambig:{idx}")]
        )
    return rows


def resolve_disambiguation_choice(
    user_text: str,
    search_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Chọn SP từ câu '1', '2' hoặc tên."""
    text = (user_text or "").strip()
    if text.isdigit():
        idx = int(text) - 1
        if 0 <= idx < len(search_results):
            return search_results[idx]
    lower = text.lower()
    for item in search_results:
        name = (item.get("name") or "").lower()
        if name and (name in lower or lower in name):
            return item
    return None
