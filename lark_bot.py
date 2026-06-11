"""
Lark Bot tư vấn sản phẩm công nghệ — tích hợp Cellphones + Gemini.
Nhận sự kiện qua WebSocket (persistent connection).
"""
from __future__ import annotations

# Python 3.14 trên macOS không gắn certifi cho requests/websockets → SSL fail.
import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import asyncio
import json
import logging
import re
import sys
import threading
import time
from typing import Any

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    ReplyMessageRequest,
    ReplyMessageRequestBody,
    UpdateMessageRequest,
    UpdateMessageRequestBody,
)

from config import (
    GEMINI_API_KEY,
    LLM_PROVIDER,
    LARK_API_DOMAIN,
    LARK_APP_ID,
    LARK_APP_SECRET,
    LARK_CHAT_ID,
    LARK_THREAD_AUTO_REPLY,
)
from feedback import (
    FEEDBACK_HELPFUL,
    build_lark_card_action_response,
    build_lark_feedback_form_card,
    build_lark_feedback_thanks_card,
    build_lark_interactive_card,
    lark_interactive_content,
    parse_lark_feedback_payload,
    record_message_feedback,
)
from lark_bitable import bitable_is_configured, save_feedback_to_bitable
from lark_feedback_notify import build_lark_topic_link, send_feedback_admin_notification
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_ws_patch import apply_lark_ws_card_patch
from cps_api import attach_shop_stock_to_payload, fetch_product_for_query
from conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_session,
)
from gemini_client import (
    analyze_product_with_meta,
    extract_search_keywords,
    is_contextual_follow_up,
    needs_query_expansion,
)
from metrics import emit_metric
from scraper import build_product_payload, build_response_link_url, product_url_from_record

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4000
WELCOME_TEXT = (
    "👋 Chào bạn!\n\n"
    "Tôi là bot tư vấn sản phẩm công nghệ, lấy dữ liệu từ CellphoneS "
    "và phân tích bằng Gemini AI.\n\n"
    "💬 Hãy hỏi tôi, ví dụ:\n"
    "• iPhone 15 Pro Max giá bao nhiêu?\n"
    "• Laptop gaming dưới 20 triệu\n"
    "• Samsung Galaxy S25 có còn hàng không?\n"
    "• iPhone 16 Pro còn hàng ở cửa hàng nào?\n"
    "• Gần 288 3 Tháng 2 shop nào còn iPhone 16 Pro?\n\n"
    "Trong group: @bot + câu hỏi.\n"
    "Gõ /help để xem hướng dẫn."
)
HELP_TEXT = (
    "📖 Hướng dẫn sử dụng\n\n"
    "1️⃣ Gửi câu hỏi về sản phẩm công nghệ (tiếng Việt).\n"
    "2️⃣ Bot sẽ tìm trên cellphones.com.vn và phân tích.\n"
    "3️⃣ Nhận câu trả lời kèm link sản phẩm gốc.\n\n"
    "Lệnh:\n"
    "/start — Chào mừng\n"
    "/help — Hướng dẫn\n"
    "/clear — Xóa ngữ cảnh hội thoại\n"
    "/chatid — Lấy chat ID cho .env\n\n"
    "💡 Bot nhớ vài tin gần nhất trong cùng chat để hiểu câu hỏi tiếp "
    "(vd: còn hàng không? sau khi hỏi iPhone).\n\n"
    "🏪 Kiểm tra tồn cửa hàng: hỏi shop/chi nhánh còn hàng hoặc gần địa chỉ.\n\n"
    "⚠️ Giá và tồn kho có thể thay đổi theo thời gian thực tế trên website."
)

_sessions: dict[str, Any] = {}
# Topic/thread đã @bot hoặc bot đã trả lời — cho phép tin tiếp không cần @
_active_threads: set[str] = set()
_async_loop: asyncio.AbstractEventLoop | None = None
_lark_client: lark.Client | None = None


def _api_domain() -> str:
    if LARK_API_DOMAIN == "feishu":
        return lark.FEISHU_DOMAIN
    return lark.LARK_DOMAIN


def is_allowed_chat(chat_id: str) -> bool:
    if not LARK_CHAT_ID:
        return True
    return chat_id == LARK_CHAT_ID


def truncate_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    suffix = "\n\n… (đã rút gọn do giới hạn Lark)"
    keep = max_len - len(suffix)
    return text[:keep] + suffix


def text_content(text: str) -> str:
    return json.dumps({"text": text}, ensure_ascii=False)


def parse_text_content(content: str) -> str:
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return (data.get("text") or "").strip()
    except json.JSONDecodeError:
        pass
    return content.strip()


def strip_mentions(text: str) -> str:
    text = re.sub(r"@_user_\d+\s*", "", text)
    return text.strip()


def _resolve_thread_key(msg: lark.im.v1.EventMessage) -> str:
    """Khóa topic/thread — ưu tiên thread_id, rồi root_id, rồi message_id."""
    thread_id = (msg.thread_id or "").strip()
    if thread_id:
        return f"thread:{thread_id}"
    root_id = (msg.root_id or "").strip()
    if root_id:
        return f"root:{root_id}"
    message_id = (msg.message_id or "").strip()
    return f"msg:{message_id}" if message_id else ""


def _message_mentions_bot(msg: lark.im.v1.EventMessage) -> bool:
    mentions = msg.mentions or []
    if not mentions:
        return False
    for mention in mentions:
        name = (mention.name or "").lower()
        if any(
            token in name
            for token in ("snake", "gemini", "bot", "cellphone", "tư vấn", "tu van")
        ):
            return True
    return True


def _should_process_group_message(
    msg: lark.im.v1.EventMessage,
    *,
    thread_key: str,
) -> tuple[bool, str]:
    """
    Quyết định có xử lý tin nhắn group/topic.
    Trả (should_process, reason).
    """
    chat_type = (msg.chat_type or "").lower()
    if chat_type in ("p2p", "private"):
        return True, "p2p"

    if _message_mentions_bot(msg):
        if thread_key:
            _active_threads.add(thread_key)
        return True, "mention"

    if (
        LARK_THREAD_AUTO_REPLY
        and thread_key
        and thread_key in _active_threads
    ):
        return True, "active_thread"

    return False, "no_mention"


def _sender_user_id(data: lark.im.v1.P2ImMessageReceiveV1) -> str | None:
    sender = data.event.sender if data.event else None
    if not sender or not sender.sender_id:
        return None
    sid = sender.sender_id
    return sid.open_id or sid.user_id or sid.union_id


class LarkMessenger:
    """Gửi / cập nhật tin nhắn reply trên Lark."""

    def __init__(self, client: lark.Client, reply_to_message_id: str) -> None:
        self.client = client
        self.reply_to = reply_to_message_id
        self.status_message_id: str | None = None

    def reply(self, text: str) -> str:
        request = (
            ReplyMessageRequest.builder()
            .message_id(self.reply_to)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("text")
                .content(text_content(text))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.reply(request)
        if not response.success():
            logger.error(
                "Lark reply lỗi: code=%s msg=%s",
                response.code,
                response.msg,
            )
            return ""
        if response.data and response.data.message_id:
            return response.data.message_id
        return ""

    def update_status(self, text: str) -> None:
        if not self.status_message_id:
            self.status_message_id = self.reply(text)
            return
        if not self._update(self.status_message_id, text):
            logger.warning("Không cập nhật được trạng thái — giữ tin cũ")

    def send_final(self, text: str) -> None:
        if self.status_message_id:
            if self._update(self.status_message_id, text, msg_type="text"):
                return
        self.reply(text)

    def send_final_interactive(self, card: dict[str, Any]) -> None:
        # Lark không cho update tin text → interactive (lỗi invalid msg_type).
        # Rút gọn tin trạng thái cũ, gửi card interactive reply mới.
        if self.status_message_id:
            self._update(self.status_message_id, "✅", msg_type="text")
        self.reply_interactive(card)

    def reply_interactive(self, card: dict[str, Any]) -> str:
        request = (
            ReplyMessageRequest.builder()
            .message_id(self.reply_to)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("interactive")
                .content(lark_interactive_content(card))
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.reply(request)
        if not response.success():
            logger.error(
                "Lark interactive reply lỗi: code=%s msg=%s",
                response.code,
                response.msg,
            )
            return ""
        if response.data and response.data.message_id:
            return response.data.message_id
        return ""

    def _update(
        self,
        message_id: str,
        content: str,
        *,
        msg_type: str = "text",
    ) -> bool:
        if msg_type == "text":
            body_content = text_content(content)
        else:
            body_content = content
        request = (
            UpdateMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                UpdateMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(body_content)
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.update(request)
        if not response.success():
            logger.warning(
                "Lark update lỗi: code=%s msg=%s",
                response.code,
                response.msg,
            )
            return False
        return True


async def _cmd_chatid(
    messenger: LarkMessenger,
    chat_id: str,
    chat_type: str,
) -> None:
    configured = LARK_CHAT_ID or "(chưa cấu hình — bot trả lời mọi chat)"
    match = "✅ khớp" if is_allowed_chat(chat_id) else "❌ không khớp"
    messenger.reply(
        "🆔 Chat ID: "
        f"{chat_id}\n"
        f"📋 Loại: {chat_type}\n"
        f"⚙️ LARK_CHAT_ID trong .env: {configured}\n"
        f"🔐 Trạng thái: {match}\n\n"
        "Copy Chat ID vào `.env` nếu muốn bot chỉ trả lời chat này."
    )


async def _cmd_start(messenger: LarkMessenger, chat_id: str) -> None:
    if not is_allowed_chat(chat_id):
        messenger.reply(
            "⚠️ Bot chưa được cấu hình cho chat này.\n"
            f"Chat ID: {chat_id}\n"
            f"LARK_CHAT_ID trong .env: {LARK_CHAT_ID or '(trống)'}\n\n"
            "Gõ /chatid để xem chi tiết, hoặc sửa `.env` rồi khởi động lại bot."
        )
        return
    messenger.reply(WELCOME_TEXT)


async def _cmd_help(messenger: LarkMessenger, chat_id: str) -> None:
    if not is_allowed_chat(chat_id):
        messenger.reply(
            "⚠️ Bot chưa được cấu hình cho chat này.\n"
            "Gõ /chatid để lấy ID đúng, cập nhật `.env`, rồi chạy lại `python lark_bot.py`."
        )
        return
    messenger.reply(HELP_TEXT)


async def _cmd_clear(
    messenger: LarkMessenger,
    chat_id: str,
    user_id: str | None,
    *,
    thread_key: str | None = None,
) -> None:
    if not is_allowed_chat(chat_id):
        return
    clear_session(_sessions, chat_id, user_id, thread_key=thread_key)
    if thread_key:
        _active_threads.discard(thread_key)
    messenger.reply(
        "🧹 Đã xóa ngữ cảnh hội thoại. Bạn có thể hỏi sản phẩm mới từ đầu."
    )


async def process_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    if not data.event or not data.event.message:
        return
    if _lark_client is None:
        return

    msg = data.event.message
    chat_id = msg.chat_id or ""
    chat_type = msg.chat_type or "?"
    message_id = msg.message_id or ""

    if msg.message_type != "text":
        return

    sender = data.event.sender
    if sender and sender.sender_type == "app":
        return

    user_id = _sender_user_id(data)
    thread_key = _resolve_thread_key(msg)
    raw_text = strip_mentions(parse_text_content(msg.content or ""))
    if not raw_text or not message_id:
        return

    messenger = LarkMessenger(_lark_client, message_id)

    if raw_text.startswith("/"):
        command = raw_text.split()[0].lower()
        if command == "/chatid":
            await _cmd_chatid(messenger, chat_id, chat_type)
        elif command == "/start":
            await _cmd_start(messenger, chat_id)
        elif command == "/help":
            await _cmd_help(messenger, chat_id)
        elif command == "/clear":
            await _cmd_clear(
                messenger, chat_id, user_id, thread_key=thread_key or None
            )
        return

    should_process, process_reason = _should_process_group_message(
        msg, thread_key=thread_key
    )
    if not should_process:
        logger.debug(
            "Bỏ qua tin group không @bot — chat=%s thread=%s",
            chat_id,
            thread_key,
        )
        return

    if not is_allowed_chat(chat_id):
        logger.warning(
            "Bỏ qua tin nhắn — chat %s, cấu hình LARK_CHAT_ID=%s",
            chat_id,
            LARK_CHAT_ID,
        )
        messenger.reply(
            "⚠️ Bot chỉ được cấu hình cho chat khác.\n"
            f"Chat ID hiện tại: {chat_id}\n"
            "Gõ /chatid, cập nhật `LARK_CHAT_ID` trong `.env`, rồi khởi động lại bot."
        )
        return

    logger.info(
        "Nhận câu hỏi từ chat %s (%s) thread=%s reason=%s",
        chat_id,
        chat_type,
        thread_key,
        process_reason,
    )
    user_question = raw_text

    session = get_session(
        _sessions,
        chat_id,
        user_id,
        thread_key=thread_key or None,
    )
    conversation_context = format_context_block(session)
    is_follow_up = is_contextual_follow_up(user_question, conversation_context)
    started = time.perf_counter()
    metric_data: dict[str, object] = {
        "platform": "lark",
        "chat_id": str(chat_id),
        "user_id": str(user_id or ""),
        "thread_key": thread_key,
        "process_reason": process_reason,
        "is_follow_up": is_follow_up,
        "question_len": len(user_question),
    }
    messenger.update_status("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    response_link_url = ""
    try:
        t0 = time.perf_counter()
        kw_context = (
            conversation_context if is_follow_up else ""
        )
        if needs_query_expansion(user_question):
            messenger.update_status("✍️ Đang hiểu câu hỏi của bạn...")
        search_keywords = await asyncio.to_thread(
            extract_search_keywords, user_question, kw_context
        )
        metric_data["latency_keyword_ms"] = int((time.perf_counter() - t0) * 1000)
        if not search_keywords:
            messenger.send_final("😔 Không hiểu được sản phẩm bạn cần tìm.")
            metric_data["status"] = "keyword_empty"
            emit_metric(
                "chat_message",
                **metric_data,
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return

        logger.info(
            "Tìm sản phẩm: keywords=%r | câu gốc=%r",
            search_keywords,
            user_question,
        )

        fallback_url = ""
        if is_follow_up:
            last_product = session.get("last_product") or {}
            fallback_url = last_product.get("url") or ""

        messenger.update_status(f"🔍 Đang tìm: {search_keywords}...")
        response_link_url = ""
        t1 = time.perf_counter()
        results, detail, fetch_stats = await fetch_product_for_query(
            search_keywords,
            user_message=user_question,
            fallback_url=fallback_url,
        )
        metric_data["latency_fetch_ms"] = int((time.perf_counter() - t1) * 1000)
        metric_data.update(fetch_stats)
        if not results and not detail:
            hint = (
                f"\n\nTừ khóa đã tìm: {search_keywords}"
                if search_keywords != user_question
                else ""
            )
            messenger.send_final(
                "😔 Không tìm thấy sản phẩm phù hợp trên CellphoneS.\n"
                "Thử hỏi lại với tên sản phẩm cụ thể hơn nhé!"
                f"{hint}"
            )
            metric_data["status"] = "not_found"
            metric_data["search_keywords"] = search_keywords
            emit_metric(
                "chat_message",
                **metric_data,
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return

        messenger.update_status(
            "📦 Đã tìm thấy sản phẩm. Đang phân tích dữ liệu..."
        )
        product_url = product_url_from_record(detail) or (
            product_url_from_record(results[0]) if results else ""
        )
        payload = build_product_payload(results, detail)
        response_link_url = build_response_link_url(
            search_results=results,
            detail=detail,
            search_keywords=search_keywords,
        )

        if detail.get("product_id"):
            messenger.update_status("🏪 Đang kiểm tra tồn cửa hàng...")
        shop_ctx = await attach_shop_stock_to_payload(
            payload, detail, user_question=user_question
        )
        if shop_ctx:
            metric_data["shop_stock_scenario"] = True
            metric_data["shop_stock_matched"] = shop_ctx.get("matched_shops_count", 0)

        llm_label = "DeepSeek" if LLM_PROVIDER == "deepseek" else "Gemini AI"
        messenger.update_status(f"🤖 Đang phân tích với {llm_label}...")
        t2 = time.perf_counter()
        answer, gemini_meta = await asyncio.to_thread(
            analyze_product_with_meta,
            user_question,
            payload,
            conversation_context,
        )
        metric_data["latency_gemini_ms"] = int((time.perf_counter() - t2) * 1000)
        if gemini_meta:
            metric_data.update(
                {
                    "gemini_model": gemini_meta.get("model", ""),
                    "prompt_tokens": int(gemini_meta.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(gemini_meta.get("completion_tokens", 0) or 0),
                    "total_tokens": int(gemini_meta.get("total_tokens", 0) or 0),
                }
            )
        answer = truncate_message(answer)

        product_name = (detail.get("name") or results[0].get("name") or "").strip()
        append_turn(
            session,
            user=user_question,
            assistant=answer,
            keywords=search_keywords,
            product_name=product_name,
            product_url=product_url,
        )
        thread_id_for_link = (msg.thread_id or msg.root_id or "").strip()
        card = build_lark_interactive_card(
            answer,
            product_url=response_link_url,
            question=user_question,
            product_name=product_name,
            thread_id=thread_id_for_link,
            source_chat_id=chat_id,
        )
        messenger.send_final_interactive(card)
        if thread_key:
            _active_threads.add(thread_key)
        metric_data["status"] = "success"
        metric_data["search_keywords"] = search_keywords
        metric_data["product_id"] = detail.get("product_id", "")
        metric_data["product_url"] = product_url
        metric_data["response_link_url"] = response_link_url
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )

    except Exception as exc:
        logger.exception("Lỗi xử lý tin nhắn Lark: %s", exc)
        messenger.send_final(
            "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu.\n"
            "Vui lòng thử lại sau ít phút.\n\n"
            f"Chi tiết: {str(exc)[:200]}"
        )
        metric_data["status"] = "error"
        metric_data["error"] = str(exc)[:200]
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )


def _start_async_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    thread = threading.Thread(target=run_loop, name="lark-async", daemon=True)
    thread.start()
    return loop


def _schedule_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    if _async_loop is None:
        return
    asyncio.run_coroutine_threadsafe(process_message(data), _async_loop)


def on_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _schedule_message(data)


def _persist_feedback_async(
    *,
    rating: str,
    reviewer_open_id: str,
    chat_id: str,
    message_id: str,
    thread_id: str,
    question: str,
    product_name: str,
    product_url: str,
    user_comment: str = "",
) -> None:
    """Ghi metrics + Lark Base + noti admin — không chặn card.action.trigger."""
    record_message_feedback(
        platform="lark",
        rating=rating,
        chat_id=chat_id,
        user_id=reviewer_open_id,
        message_id=message_id,
        user_comment=user_comment,
    )
    if _lark_client is None:
        return

    topic_link = build_lark_topic_link(
        chat_id=chat_id,
        message_id=message_id,
        thread_id=thread_id,
    )
    save_result = None
    if bitable_is_configured():
        save_result = save_feedback_to_bitable(
            _lark_client,
            rating=rating,
            reviewer_open_id=reviewer_open_id,
            question=question,
            product_name=product_name,
            product_url=product_url,
            topic_link=topic_link,
            user_comment=user_comment,
        )

    desc_parts: list[str] = []
    if product_name:
        desc_parts.append(f"Sản phẩm: {product_name}")
    if question:
        desc_parts.append(f"Câu hỏi: {question}")
    if product_url:
        desc_parts.append(f"Link SP: {product_url}")
    if user_comment:
        desc_parts.append(f"Ý kiến: {user_comment}")
    description = "\n".join(desc_parts)
    rating_label = "👍 Hữu ích" if rating == FEEDBACK_HELPFUL else "👎 Không hữu ích"
    content = save_result.content if save_result else (user_comment or rating_label)
    base_url = save_result.record_url if save_result else ""

    send_feedback_admin_notification(
        _lark_client,
        reviewer_open_id=reviewer_open_id,
        content=content,
        description=description,
        topic_link=topic_link,
        base_record_url=base_url,
    )


def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    event = data.event
    action = event.action if event else None
    form_value = action.form_value if action else None
    payload = parse_lark_feedback_payload(
        action.value if action else None,
        form_value=form_value,
    )
    if not payload:
        return P2CardActionTriggerResponse()

    rating = payload["rating"]
    step = payload.get("step", "submit")

    if step == "pick":
        form_card = build_lark_feedback_form_card(
            rating,
            question=payload.get("question", ""),
            product_name=payload.get("product_name", ""),
            product_url=payload.get("product_url", ""),
            thread_id=payload.get("thread_id", ""),
            source_chat_id=payload.get("chat_id", ""),
            answer_body=payload.get("answer_body", ""),
        )
        return P2CardActionTriggerResponse(
            build_lark_card_action_response(card=form_card)
        )

    operator = event.operator if event else None
    ctx = event.context if event else None
    reviewer_open_id = (
        (operator.open_id or operator.user_id or operator.union_id)
        if operator
        else ""
    ) or ""
    chat_id = (ctx.open_chat_id if ctx else "") or ""
    message_id = (ctx.open_message_id if ctx else "") or ""
    user_comment = payload.get("user_comment", "")

    feedback_chat_id = payload.get("chat_id") or chat_id
    feedback_thread_id = payload.get("thread_id") or ""

    threading.Thread(
        target=_persist_feedback_async,
        kwargs={
            "rating": rating,
            "reviewer_open_id": reviewer_open_id,
            "chat_id": feedback_chat_id,
            "message_id": message_id,
            "thread_id": feedback_thread_id,
            "question": payload.get("question", ""),
            "product_name": payload.get("product_name", ""),
            "product_url": payload.get("product_url", ""),
            "user_comment": user_comment,
        },
        name="lark-feedback-persist",
        daemon=True,
    ).start()

    toast_text = (
        "Cảm ơn bạn đã đánh giá 👍"
        if rating == FEEDBACK_HELPFUL
        else "Cảm ơn phản hồi của bạn — chúng tôi sẽ cải thiện"
    )
    thanks_card = build_lark_feedback_thanks_card(
        rating,
        user_comment,
        answer_body=payload.get("answer_body", ""),
    )
    return P2CardActionTriggerResponse(
        build_lark_card_action_response(
            toast_type="success",
            toast_content=toast_text,
            card=thanks_card,
        )
    )


def validate_config() -> None:
    placeholders = ("your_", "placeholder", "here", "xxxxxxxx")
    if not LARK_APP_ID or any(p in LARK_APP_ID for p in placeholders):
        raise ValueError("Thiếu LARK_APP_ID — hãy điền vào file .env")
    if not LARK_APP_SECRET or any(p in LARK_APP_SECRET for p in placeholders):
        raise ValueError("Thiếu LARK_APP_SECRET — hãy điền vào file .env")
    if not GEMINI_API_KEY or any(p in GEMINI_API_KEY for p in placeholders):
        raise ValueError("Thiếu GEMINI_API_KEY — hãy điền vào file .env")


def main() -> None:
    global _async_loop, _lark_client

    validate_config()
    _async_loop = _start_async_loop()
    domain = _api_domain()

    _lark_client = (
        lark.Client.builder()
        .app_id(LARK_APP_ID)
        .app_secret(LARK_APP_SECRET)
        .domain(domain)
        .log_level(lark.LogLevel.INFO)
        .build()
    )

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )
    apply_lark_ws_card_patch()

    logger.info("Khởi động Lark bot... (Python %s)", sys.version.split()[0])
    logger.info("API domain: %s", LARK_API_DOMAIN)
    if LARK_CHAT_ID:
        logger.info("Chỉ phản hồi chat ID: %s", LARK_CHAT_ID)
    else:
        logger.info("Phản hồi mọi chat (LARK_CHAT_ID trống)")
    logger.info(
        "Giữ terminal mở → vào Lark Developer Console → Event Configuration → "
        "Verify persistent connection → Save."
    )

    ws_client = lark.ws.Client(
        LARK_APP_ID,
        LARK_APP_SECRET,
        event_handler=handler,
        domain=domain,
        log_level=lark.LogLevel.INFO,
    )
    logger.info("Bot đang chạy — nhấn Ctrl+C để dừng.")
    try:
        ws_client.start()
    except KeyboardInterrupt:
        logger.info("Đã dừng bot.")


if __name__ == "__main__":
    main()
