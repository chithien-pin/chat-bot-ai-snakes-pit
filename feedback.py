"""
Nút đánh giá phản hồi (👍 Hữu ích / 👎 Không hữu ích) — Telegram + Lark.
"""
from __future__ import annotations

import json
from typing import Any

from metrics import emit_metric

FEEDBACK_HELPFUL = "helpful"
FEEDBACK_NOT_HELPFUL = "not_helpful"

TELEGRAM_CB_HELPFUL = "fb:up"
TELEGRAM_CB_NOT_HELPFUL = "fb:down"
TELEGRAM_CB_ACK = "fb:ack"

FEEDBACK_ACTION_PICK = "feedback_pick"
FEEDBACK_ACTION_SUBMIT = "feedback_submit"
FEEDBACK_ACTION_LEGACY = "feedback"
FEEDBACK_COMMENT_INPUT = "feedback_comment"
FEEDBACK_FORM_NAME = "feedback_form"
# Lark giới hạn value nút card — lưu bản rút gọn câu trả lời để giữ khi cập nhật card
FEEDBACK_ANSWER_META_LEN = 1500

_RATING_DISPLAY = {
    FEEDBACK_HELPFUL: "👍 Hữu ích",
    FEEDBACK_NOT_HELPFUL: "👎 Không hữu ích",
}


def build_telegram_feedback_keyboard(
    product_url: str = "",
) -> Any:
    """Inline keyboard: đánh giá + link sản phẩm (Telegram)."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    rows = [
        [
            InlineKeyboardButton("👍 Hữu ích", callback_data=TELEGRAM_CB_HELPFUL),
            InlineKeyboardButton("👎 Không hữu ích", callback_data=TELEGRAM_CB_NOT_HELPFUL),
        ],
    ]
    if product_url:
        rows.append(
            [
                InlineKeyboardButton(
                    "🔗 Xem trên Cellphones",
                    url=product_url,
                )
            ]
        )
    return InlineKeyboardMarkup(rows)


def build_telegram_feedback_ack_keyboard() -> Any:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Cảm ơn bạn đã đánh giá!", callback_data=TELEGRAM_CB_ACK)]]
    )


def _answer_body_for_meta(text: str) -> str:
    body = (text or "").strip()
    if len(body) <= FEEDBACK_ANSWER_META_LEN:
        return body
    return body[: FEEDBACK_ANSWER_META_LEN - 20] + "\n\n… (đã rút gọn)"


def _feedback_card_prefix_elements(answer_body: str) -> list[dict[str, Any]]:
    """Giữ nội dung tư vấn gốc phía trên khi card chuyển sang form/cảm ơn."""
    if not (answer_body or "").strip():
        return []
    return [
        {"tag": "div", "text": {"tag": "lark_md", "content": answer_body}},
        {"tag": "hr"},
    ]


def build_lark_feedback_button_value(
    rating: str,
    *,
    question: str = "",
    product_name: str = "",
    product_url: str = "",
    thread_id: str = "",
    source_chat_id: str = "",
    answer_body: str = "",
    action: str = FEEDBACK_ACTION_PICK,
) -> dict[str, str]:
    """Metadata gắn vào nút card — đọc lại khi user bấm đánh giá."""
    return {
        "action": action,
        "rating": rating,
        "question": (question or "")[:200],
        "product_name": (product_name or "")[:120],
        "product_url": (product_url or "")[:200],
        "thread_id": (thread_id or "")[:80],
        "chat_id": (source_chat_id or "")[:80],
        "answer_body": _answer_body_for_meta(answer_body),
    }


def _feedback_metadata_from_value(value: dict[str, Any]) -> dict[str, str]:
    rating = str(value.get("rating") or "").strip()
    return {
        "rating": rating,
        "question": str(value.get("question") or "").strip(),
        "product_name": str(value.get("product_name") or "").strip(),
        "product_url": str(value.get("product_url") or "").strip(),
        "thread_id": str(value.get("thread_id") or "").strip(),
        "chat_id": str(value.get("chat_id") or "").strip(),
        "answer_body": str(value.get("answer_body") or "").strip(),
    }


def parse_lark_feedback_payload(
    raw: Any,
    *,
    form_value: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    """Trích metadata từ card.action.trigger (pick hoặc submit)."""
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None

    action_name = str(value.get("action") or "").strip()
    if action_name not in (
        FEEDBACK_ACTION_PICK,
        FEEDBACK_ACTION_SUBMIT,
        FEEDBACK_ACTION_LEGACY,
    ):
        return None

    meta = _feedback_metadata_from_value(value)
    if meta["rating"] not in (FEEDBACK_HELPFUL, FEEDBACK_NOT_HELPFUL):
        return None

    if action_name == FEEDBACK_ACTION_PICK:
        return {**meta, "step": "pick"}

    user_comment = ""
    if form_value and isinstance(form_value, dict):
        user_comment = str(form_value.get(FEEDBACK_COMMENT_INPUT) or "").strip()
    return {**meta, "step": "submit", "user_comment": user_comment}


def build_lark_interactive_card(
    text: str,
    *,
    product_url: str = "",
    question: str = "",
    product_name: str = "",
    thread_id: str = "",
    source_chat_id: str = "",
    max_text_len: int = 3800,
) -> dict[str, Any]:
    """Interactive card Lark/Feishu — nội dung + nút đánh giá."""
    body = (text or "").strip()
    if len(body) > max_text_len:
        body = body[: max_text_len - 20] + "\n\n… (đã rút gọn)"

    actions: list[dict[str, Any]] = []
    if product_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "🔗 Xem trên Cellphones"},
                "type": "primary",
                "url": product_url,
            }
        )

    btn_kwargs = dict(
        question=question,
        product_name=product_name,
        product_url=product_url,
        thread_id=thread_id,
        source_chat_id=source_chat_id,
        answer_body=body,
        action=FEEDBACK_ACTION_PICK,
    )
    actions.extend(
        [
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
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Tư vấn CellphoneS"},
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
            {"tag": "action", "actions": actions},
        ],
    }


def build_lark_feedback_form_card(
    rating: str,
    *,
    question: str = "",
    product_name: str = "",
    product_url: str = "",
    thread_id: str = "",
    source_chat_id: str = "",
    answer_body: str = "",
) -> dict[str, Any]:
    """Card bước 2 — giữ câu trả lời gốc + form nhập thêm nội dung / lý do."""
    rating_text = _RATING_DISPLAY.get(rating, rating)
    prompt = (
        f"Bạn đã chọn **{rating_text}**.\n\n"
        "Hãy ghi thêm nội dung hoặc lý do (không bắt buộc):"
    )
    submit_value = build_lark_feedback_button_value(
        rating,
        question=question,
        product_name=product_name,
        product_url=product_url,
        thread_id=thread_id,
        source_chat_id=source_chat_id,
        answer_body=answer_body,
        action=FEEDBACK_ACTION_SUBMIT,
    )
    elements = _feedback_card_prefix_elements(answer_body)
    elements.extend(
        [
            {"tag": "div", "text": {"tag": "lark_md", "content": prompt}},
            {
                "tag": "form",
                "name": FEEDBACK_FORM_NAME,
                "elements": [
                    {
                        "tag": "input",
                        "name": FEEDBACK_COMMENT_INPUT,
                        "placeholder": {
                            "tag": "plain_text",
                            "content": "Nhập ý kiến, lý do của bạn...",
                        },
                        "max_length": 500,
                        "width": "fill",
                        "multiline": True,
                        "rows": 3,
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Gửi đánh giá"},
                        "type": "primary",
                        "action_type": "form_submit",
                        "name": "feedback_submit_btn",
                        "value": submit_value,
                    },
                ],
            },
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Tư vấn CellphoneS"},
        },
        "elements": elements,
    }


def build_lark_feedback_thanks_card(
    rating: str,
    user_comment: str = "",
    *,
    answer_body: str = "",
) -> dict[str, Any]:
    """Card sau khi gửi — giữ câu trả lời gốc + lời cảm ơn."""
    rating_text = _RATING_DISPLAY.get(rating, rating)
    thanks = f"✅ Cảm ơn bạn đã đánh giá: **{rating_text}**"
    if user_comment:
        thanks += f"\n\n**Ý kiến của bạn:**\n{user_comment[:400]}"
    elements = _feedback_card_prefix_elements(answer_body)
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": thanks}})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "Tư vấn CellphoneS"},
        },
        "elements": elements,
    }


def build_lark_card_action_response(
    *,
    toast_type: str = "info",
    toast_content: str = "",
    card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Response cho card.action.trigger — toast và/hoặc cập nhật card."""
    resp: dict[str, Any] = {}
    if toast_content:
        resp["toast"] = {"type": toast_type, "content": toast_content}
    if card:
        resp["card"] = {"type": "raw", "data": card}
    return resp


def lark_interactive_content(card: dict[str, Any]) -> str:
    return json.dumps(card, ensure_ascii=False)


def parse_lark_feedback_value(raw: Any) -> str | None:
    """Trích rating từ card.action.trigger."""
    payload = parse_lark_feedback_payload(raw)
    return payload.get("rating") if payload else None


def record_message_feedback(
    *,
    platform: str,
    rating: str,
    chat_id: str = "",
    user_id: str = "",
    message_id: str = "",
    user_comment: str = "",
) -> None:
    emit_metric(
        "message_feedback",
        platform=platform,
        rating=rating,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        user_comment=user_comment[:200] if user_comment else "",
    )
