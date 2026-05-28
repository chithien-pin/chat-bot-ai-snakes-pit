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
    LARK_API_DOMAIN,
    LARK_APP_ID,
    LARK_APP_SECRET,
    LARK_CHAT_ID,
)
from cps_api import fetch_product_for_query
from conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_session,
)
from gemini_client import (
    _is_follow_up_question,
    analyze_product,
    extract_search_keywords,
    needs_query_expansion,
)
from scraper import build_product_payload

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
    "• Samsung Galaxy S25 có còn hàng không?\n\n"
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
    "⚠️ Giá và tồn kho có thể thay đổi theo thời gian thực tế trên website."
)

_sessions: dict[str, Any] = {}
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
            if self._update(self.status_message_id, text):
                return
        self.reply(text)

    def _update(self, message_id: str, text: str) -> bool:
        request = (
            UpdateMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                UpdateMessageRequestBody.builder()
                .msg_type("text")
                .content(text_content(text))
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
) -> None:
    if not is_allowed_chat(chat_id):
        return
    clear_session(_sessions, chat_id, user_id)
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
            await _cmd_clear(messenger, chat_id, user_id)
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

    logger.info("Nhận câu hỏi từ chat %s (%s)", chat_id, chat_type)
    user_question = raw_text

    session = get_session(_sessions, chat_id, user_id)
    conversation_context = format_context_block(session)
    messenger.update_status("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    try:
        kw_context = (
            conversation_context if _is_follow_up_question(user_question) else ""
        )
        if needs_query_expansion(user_question):
            messenger.update_status("✍️ Đang hiểu câu hỏi của bạn...")
        search_keywords = await asyncio.to_thread(
            extract_search_keywords, user_question, kw_context
        )
        if not search_keywords:
            messenger.send_final("😔 Không hiểu được sản phẩm bạn cần tìm.")
            return

        logger.info(
            "Tìm sản phẩm: keywords=%r | câu gốc=%r",
            search_keywords,
            user_question,
        )

        fallback_url = ""
        if _is_follow_up_question(user_question):
            last_product = session.get("last_product") or {}
            fallback_url = last_product.get("url") or ""

        messenger.update_status(f"🔍 Đang tìm: {search_keywords}...")
        results, detail = await fetch_product_for_query(
            search_keywords,
            user_message=user_question,
            fallback_url=fallback_url,
        )
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
            return

        messenger.update_status(
            "📦 Đã tìm thấy sản phẩm. Đang phân tích dữ liệu..."
        )
        product_url = detail.get("url") or (results[0].get("url", "") if results else "")
        payload = build_product_payload(results, detail)

        messenger.update_status("🤖 Đang phân tích với Gemini AI...")
        answer = await asyncio.to_thread(
            analyze_product,
            user_question,
            payload,
            conversation_context,
        )
        answer = truncate_message(answer)
        if product_url:
            answer = f"{answer}\n\n🔗 Xem trên Cellphones: {product_url}"

        product_name = (detail.get("name") or results[0].get("name") or "").strip()
        append_turn(
            session,
            user=user_question,
            assistant=answer,
            keywords=search_keywords,
            product_name=product_name,
            product_url=product_url,
        )
        messenger.send_final(answer)

    except Exception as exc:
        logger.exception("Lỗi xử lý tin nhắn Lark: %s", exc)
        messenger.send_final(
            "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu.\n"
            "Vui lòng thử lại sau ít phút.\n\n"
            f"Chi tiết: {str(exc)[:200]}"
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
        .build()
    )

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
