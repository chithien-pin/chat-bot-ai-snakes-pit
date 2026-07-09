"""
Lark interactive card — so sánh 2 sản phẩm theo cột (column_set).
"""
from __future__ import annotations

from typing import Any

from cps_bot.browse.compare_reply import format_compare_product_lark_md
from cps_bot.cps.scraper import product_url_from_record
from cps_bot.feedback.feedback import (
    FEEDBACK_ACTION_PICK,
    FEEDBACK_HELPFUL,
    FEEDBACK_NOT_HELPFUL,
    build_lark_feedback_button_value,
)


def _lark_card_config() -> dict[str, Any]:
    return {"wide_screen_mode": True, "update_multi": True}


def _compare_column(product: dict[str, Any]) -> dict[str, Any]:
    """Một cột sản phẩm — chỉ div/lark_md (Lark không cho action trong column)."""
    body = format_compare_product_lark_md(product)
    url = product_url_from_record(product) or (product.get("url") or "")
    if url:
        body += f"\n\n[🔗 Xem sản phẩm]({url})"
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "vertical_align": "top",
        "padding": "8px",
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
        ],
    }


def build_lark_compare_card(
    products: list[dict[str, Any]],
    *,
    summary: str = "",
    question: str = "",
    product_name: str = "",
    product_url: str = "",
    thread_id: str = "",
    source_chat_id: str = "",
    max_summary_len: int = 600,
) -> dict[str, Any]:
    """Card 2 cột — mỗi cột 1 sản phẩm (giống layout Lark Base AI | AnyGen)."""
    left, right = products[0], products[1]
    intro = (summary or "").strip()
    if not intro:
        intro = "⚖️ So sánh nhanh 2 sản phẩm CellphoneS"
    if len(intro) > max_summary_len:
        intro = intro[: max_summary_len - 20] + "\n…"

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": intro}},
        {
            "tag": "column_set",
            "flex_mode": "bisect",
            "background_style": "grey",
            "horizontal_spacing": "default",
            "columns": [_compare_column(left), _compare_column(right)],
        },
    ]

    primary_url = product_url or product_url_from_record(left) or ""
    primary_name = product_name or (left.get("name") or "")
    btn_kwargs = dict(
        question=question,
        product_name=primary_name,
        product_url=primary_url,
        thread_id=thread_id,
        source_chat_id=source_chat_id,
        answer_body=intro,
        action=FEEDBACK_ACTION_PICK,
    )
    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "👍 Hữu ích"},
                    "type": "default",
                    "value": build_lark_feedback_button_value(
                        FEEDBACK_HELPFUL,
                        **btn_kwargs,
                    ),
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "👎 Không hữu ích"},
                    "type": "default",
                    "value": build_lark_feedback_button_value(
                        FEEDBACK_NOT_HELPFUL,
                        **btn_kwargs,
                    ),
                },
            ],
        }
    )

    return {
        "config": _lark_card_config(),
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "So sánh sản phẩm"},
        },
        "elements": elements,
    }
