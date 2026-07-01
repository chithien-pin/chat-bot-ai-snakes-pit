"""
Thông báo admin khi có feedback mới — gửi interactive card vào group Lark.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from config import (
    LARK_API_DOMAIN,
    LARK_BITABLE_APP_TOKEN,
    LARK_BITABLE_TABLE_ID,
    LARK_FEEDBACK_NOTIFY_CHAT_ID,
)

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))


def _applink_base() -> str:
    if LARK_API_DOMAIN == "feishu":
        return "https://applink.feishu.cn"
    return "https://applink.larksuite.com"


def build_lark_topic_link(
    *,
    chat_id: str,
    message_id: str = "",
    thread_id: str = "",
) -> str:
    """Deep link mở đúng topic / tin nhắn trong Lark."""
    if not chat_id:
        return ""
    base = _applink_base()
    params = [f"openChatId={chat_id}"]
    if thread_id:
        params.append(f"threadId={thread_id}")
    elif message_id:
        params.append(f"openMessageId={message_id}")
    return f"{base}/client/chat/open?{'&'.join(params)}"


def build_lark_contact_link(open_id: str) -> str:
    """Mở chat 1-1 với người đánh giá."""
    if not open_id:
        return ""
    return f"{_applink_base()}/client/chat/open?openId={open_id}"


def build_bitable_record_url(record_id: str, record_url: str = "") -> str:
    if record_url:
        return record_url
    if not record_id or not LARK_BITABLE_APP_TOKEN or not LARK_BITABLE_TABLE_ID:
        return ""
    web = "https://feishu.cn" if LARK_API_DOMAIN == "feishu" else "https://larksuite.com"
    return (
        f"{web}/base/{LARK_BITABLE_APP_TOKEN}"
        f"?table={LARK_BITABLE_TABLE_ID}&record={record_id}"
    )


def build_admin_feedback_card(
    *,
    reviewer_open_id: str,
    content: str,
    description: str,
    topic_link: str,
    base_record_url: str,
    feedback_time: str | None = None,
) -> dict[str, Any]:
    """Card thông báo admin — khớp mẫu 'Bạn có đánh giá mới !!!'."""
    when = feedback_time or datetime.now(VN_TZ).strftime("%d/%m/%Y %H:%M")
    at_user = f"<at id={reviewer_open_id}></at>" if reviewer_open_id else "Một người dùng"
    body = (
        f"{at_user} đã gửi một đánh giá cho bạn như sau:\n"
        f"- **Nội dung:** {content or '—'}\n"
        f"- **Mô tả chi tiết:** \n{description or '—'}\n"
        f"- **Thời gian:** {when}"
    )

    actions: list[dict[str, Any]] = []
    contact_url = build_lark_contact_link(reviewer_open_id)
    if contact_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Liên hệ người đánh giá"},
                "type": "default",
                "url": contact_url,
            }
        )
    if topic_link:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Mở hội thoại"},
                "type": "default",
                "url": topic_link,
            }
        )
    if base_record_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Mở dashboard"},
                "type": "primary",
                "url": base_record_url,
            }
        )

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": body}},
    ]
    if actions:
        elements.append({"tag": "action", "actions": actions})
    elements.append(
        {
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": "From Sale Expert AI Data"},
            ],
        }
    )

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "purple",
            "title": {"tag": "plain_text", "content": "Bạn có đánh giá mới !!!"},
        },
        "elements": elements,
    }


def send_feedback_admin_notification(
    client: Any,
    *,
    reviewer_open_id: str,
    content: str,
    description: str,
    topic_link: str,
    base_record_url: str,
) -> bool:
    """Gửi card thông báo vào group admin."""
    chat_id = (LARK_FEEDBACK_NOTIFY_CHAT_ID or "").strip()
    if not chat_id:
        return False

    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    card = build_admin_feedback_card(
        reviewer_open_id=reviewer_open_id,
        content=content,
        description=description,
        topic_link=topic_link,
        base_record_url=base_record_url,
    )
    content_json = json.dumps(card, ensure_ascii=False)
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(content_json)
            .build()
        )
        .build()
    )
    try:
        response = client.im.v1.message.create(request)
    except Exception as exc:
        logger.exception("Gửi noti feedback admin lỗi: %s", exc)
        return False

    if not response.success():
        logger.warning(
            "Noti feedback admin thất bại: code=%s msg=%s",
            response.code,
            response.msg,
        )
        return False

    logger.info("Đã gửi noti feedback tới group %s", chat_id)
    return True
