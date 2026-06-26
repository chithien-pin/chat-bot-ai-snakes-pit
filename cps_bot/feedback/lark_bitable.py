"""
Ghi đánh giá phản hồi (nút card Lark) vào Lark Base (Bitable).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import (
    LARK_BITABLE_APP_TOKEN,
    LARK_BITABLE_CATEGORY,
    LARK_BITABLE_COL_TOPIC_LINK,
    LARK_BITABLE_ENABLED,
    LARK_BITABLE_STATUS,
    LARK_BITABLE_TABLE_ID,
    LARK_BITABLE_TOPIC_LINK_FORMAT,
)
from cps_bot.feedback.feedback import FEEDBACK_HELPFUL, FEEDBACK_NOT_HELPFUL
from cps_bot.feedback.lark_feedback_notify import build_bitable_record_url

logger = logging.getLogger(__name__)

COL_REVIEWER = "Người đánh giá"
COL_CONTENT = "Nội dung đánh giá"
COL_DESCRIPTION = "Mô tả (nếu có)"
COL_CATEGORY = "Phân loại"
COL_STATUS = "Trạng thái xử lý"
COL_RATING_TYPE = "Loại đánh giá"
COL_QUESTION = "Câu hỏi"

_RATING_LABELS = {
    FEEDBACK_HELPFUL: "Hữu ích",
    FEEDBACK_NOT_HELPFUL: "Không hữu ích",
}

_CONTENT_LABELS = {
    FEEDBACK_HELPFUL: "👍 Hữu ích",
    FEEDBACK_NOT_HELPFUL: "👎 Không hữu ích",
}


@dataclass
class FeedbackSaveResult:
    ok: bool
    record_id: str = ""
    record_url: str = ""
    topic_link: str = ""
    content: str = ""
    description: str = ""


def bitable_is_configured() -> bool:
    return bool(
        LARK_BITABLE_ENABLED
        and LARK_BITABLE_APP_TOKEN
        and LARK_BITABLE_TABLE_ID
    )


def build_bitable_fields(
    *,
    rating: str,
    reviewer_open_id: str = "",
    question: str = "",
    product_name: str = "",
    product_url: str = "",
    topic_link: str = "",
    user_comment: str = "",
) -> dict[str, Any]:
    """Map feedback → fields Lark Base."""
    rating_label = _RATING_LABELS.get(rating, rating)
    content_label = _CONTENT_LABELS.get(rating, rating_label)

    description_parts: list[str] = []
    if product_name:
        description_parts.append(f"Sản phẩm: {product_name}")
    if product_url:
        description_parts.append(f"Link SP: {product_url}")
    if question:
        description_parts.append(f"Câu hỏi: {question}")

    # Nội dung đánh giá = ý kiến user; không có thì dùng nhãn 👍/👎
    if user_comment:
        content_value = user_comment[:2000]
    else:
        content_value = content_label

    fields: dict[str, Any] = {
        COL_CONTENT: content_value,
        COL_RATING_TYPE: rating_label,
        COL_CATEGORY: LARK_BITABLE_CATEGORY,
        COL_STATUS: LARK_BITABLE_STATUS,
    }
    if question:
        fields[COL_QUESTION] = question[:2000]
    if description_parts:
        fields[COL_DESCRIPTION] = "\n".join(description_parts)[:2000]
    if reviewer_open_id:
        fields[COL_REVIEWER] = [{"id": reviewer_open_id}]
    if topic_link and LARK_BITABLE_COL_TOPIC_LINK:
        if LARK_BITABLE_TOPIC_LINK_FORMAT == "url":
            fields[LARK_BITABLE_COL_TOPIC_LINK] = {
                "text": "Mở topic hội thoại",
                "link": topic_link,
            }
        else:
            fields[LARK_BITABLE_COL_TOPIC_LINK] = topic_link
    return fields


def save_feedback_to_bitable(
    client: Any,
    *,
    rating: str,
    reviewer_open_id: str = "",
    question: str = "",
    product_name: str = "",
    product_url: str = "",
    topic_link: str = "",
    user_comment: str = "",
) -> FeedbackSaveResult:
    """Tạo 1 dòng feedback trong Lark Base."""
    content_label = _CONTENT_LABELS.get(rating, rating)
    display_content = user_comment or content_label
    desc_parts = [p for p in [product_name, question] if p]
    description = "\n".join(desc_parts)
    if user_comment:
        description = f"{description}\nÝ kiến: {user_comment}".strip()

    if not bitable_is_configured():
        return FeedbackSaveResult(
            ok=False,
            topic_link=topic_link,
            content=display_content,
            description=description,
        )

    from lark_oapi.api.bitable.v1 import AppTableRecord, CreateAppTableRecordRequest

    fields = build_bitable_fields(
        rating=rating,
        reviewer_open_id=reviewer_open_id,
        question=question,
        product_name=product_name,
        product_url=product_url,
        topic_link=topic_link,
        user_comment=user_comment,
    )
    request = (
        CreateAppTableRecordRequest.builder()
        .app_token(LARK_BITABLE_APP_TOKEN)
        .table_id(LARK_BITABLE_TABLE_ID)
        .user_id_type("open_id")
        .request_body(AppTableRecord.builder().fields(fields).build())
        .build()
    )
    try:
        response = client.bitable.v1.app_table_record.create(request)
    except Exception as exc:
        logger.exception("Lark Base create record lỗi: %s", exc)
        return FeedbackSaveResult(
            ok=False,
            topic_link=topic_link,
            content=display_content,
            description=description,
        )

    if not response.success():
        logger.warning(
            "Lark Base từ chối ghi: code=%s msg=%s fields=%s",
            response.code,
            response.msg,
            list(fields.keys()),
        )
        return FeedbackSaveResult(
            ok=False,
            topic_link=topic_link,
            content=display_content,
            description=description,
        )

    record_id = ""
    record_url = ""
    if response.data and response.data.record:
        record_id = str(response.data.record.record_id or "")
        record_url = str(response.data.record.record_url or "")
    record_url = build_bitable_record_url(record_id, record_url)

    logger.info(
        "Đã ghi feedback vào Lark Base — rating=%s user=%s record=%s",
        rating,
        reviewer_open_id,
        record_id,
    )
    return FeedbackSaveResult(
        ok=True,
        record_id=record_id,
        record_url=record_url,
        topic_link=topic_link,
        content=display_content,
        description=description,
    )
