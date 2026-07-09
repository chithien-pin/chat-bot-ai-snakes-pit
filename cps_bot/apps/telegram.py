"""
Telegram Bot tư vấn sản phẩm công nghệ — tích hợp Cellphones + Gemini.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import re
from typing import Any

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import (
    BYTEPLUS_API_KEY,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEY,
    GROUP_CHAT_ID,
    LLM_PROVIDER,
    TELEGRAM_BOT_TOKEN,
)
from cps_bot.core.chat_help import chat_help_telegram
from cps_bot.core.chat_pipeline import process_chat_message
from cps_bot.core.conversation import clear_session
from cps_bot.feedback.feedback import (
    FEEDBACK_HELPFUL,
    FEEDBACK_NOT_HELPFUL,
    TELEGRAM_CB_ACK,
    TELEGRAM_CB_HELPFUL,
    TELEGRAM_CB_NOT_HELPFUL,
    build_telegram_feedback_ack_keyboard,
    build_telegram_feedback_keyboard,
    cache_feedback_context,
    get_feedback_context,
    record_message_feedback,
)
from cps_bot.core.user_display import remember_user_name, telegram_user_display_name
from cps_bot.core.session_store import load_session_store

# Cấu hình logging ra console
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096
WELCOME_TEXT = (
    "👋 *Chào bạn!*\n\n"
    "Tôi là bot tư vấn sản phẩm công nghệ, lấy dữ liệu từ *CellphoneS* "
    "và phân tích bằng *Gemini AI*.\n\n"
    "💬 Hãy hỏi tôi, ví dụ:\n"
    "• _Giá iPhone 16 Pro Max 256GB hôm nay?_\n"
    "• _SVIP/HSSV mua MacBook Air M2 giảm bao nhiêu?_\n"
    "• _Shop còn iPhone 16 Plus 256 màu hồng không?_\n"
    "• _Gần 288 3 Tháng 2 shop nào còn iPhone 16 Pro?_\n"
    "• _Lên đời iPhone được trợ giá thu cũ bao nhiêu?_\n"
    "• _Trả góp Home Credit iPhone 16 trả trước thấp nhất?_\n"
    "• _So sánh S26 Ultra và S25 Ultra_\n\n"
    "Gõ /help để xem hướng dẫn."
)


def _chat_id_str(chat_id: int | str) -> str:
    return str(chat_id)


def is_allowed_chat(chat_id: int) -> bool:
    """Chỉ phản hồi trong group đã cấu hình (nếu có)."""
    if not GROUP_CHAT_ID:
        return True
    return _chat_id_str(chat_id) == GROUP_CHAT_ID


def _chat_label(update: Update) -> str:
    chat = update.effective_chat
    if not chat:
        return "?"
    title = getattr(chat, "title", None) or getattr(chat, "username", None) or ""
    return f"{chat.id} ({chat.type}{': ' + title if title else ''})"


def truncate_message(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    """Cắt tin nhắn nếu vượt giới hạn Telegram."""
    if len(text) <= max_len:
        return text
    suffix = "\n\n… _(đã rút gọn do giới hạn Telegram)_"
    keep = max_len - len(suffix)
    return text[:keep] + suffix


def escape_markdown(text: str) -> str:
    """
    Escape ký tự đặc biệt cho Telegram Markdown (legacy).
    """
    escape_chars = r"_*`["
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)


async def cmd_chatid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Luôn trả lời — dùng để lấy ID group/chat cho .env."""
    if not update.effective_chat or not update.message:
        return
    chat = update.effective_chat
    configured = GROUP_CHAT_ID or "(chưa cấu hình — bot trả lời mọi chat)"
    match = "✅ khớp" if is_allowed_chat(chat.id) else "❌ không khớp"
    await update.message.reply_text(
        f"🆔 *Chat ID:* `{chat.id}`\n"
        f"📋 *Loại:* {chat.type}\n"
        f"⚙️ *GROUP\\_CHAT\\_ID trong .env:* `{configured}`\n"
        f"🔐 *Trạng thái:* {match}\n\n"
        "Copy Chat ID vào `.env` nếu muốn bot chỉ trả lời group này.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        logger.warning(
            "Từ chối /start — chat %s, cấu hình GROUP_CHAT_ID=%s",
            _chat_label(update),
            GROUP_CHAT_ID,
        )
        await update.message.reply_text(
            "⚠️ Bot chưa được cấu hình cho chat này.\n"
            f"Chat ID của bạn: `{chat_id}`\n"
            f"GROUP_CHAT_ID trong .env: `{GROUP_CHAT_ID}`\n\n"
            "Gõ /chatid để xem chi tiết, hoặc sửa `.env` rồi khởi động lại bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xóa ngữ cảnh hội thoại của user trong chat hiện tại."""
    if not update.effective_chat or not update.message:
        return
    if not is_allowed_chat(update.effective_chat.id):
        return
    store = context.application.bot_data.setdefault("sessions", {})
    user_id = update.effective_user.id if update.effective_user else None
    thread_id = getattr(update.message, "message_thread_id", None)
    thread_key = f"thread:{thread_id}" if thread_id else None
    clear_session(store, update.effective_chat.id, user_id, thread_key=thread_key)
    await update.message.reply_text(
        "🧹 Đã xóa ngữ cảnh hội thoại. Bạn có thể hỏi sản phẩm mới từ đầu."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.message:
        return
    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        logger.warning(
            "Từ chối /help — chat %s, cấu hình GROUP_CHAT_ID=%s",
            _chat_label(update),
            GROUP_CHAT_ID,
        )
        await update.message.reply_text(
            "⚠️ Bot chưa được cấu hình cho chat này.\n"
            "Gõ /chatid để lấy ID đúng, cập nhật `.env`, rồi chạy lại `python bot.py`.",
        )
        return
    await update.message.reply_text(
        chat_help_telegram(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Xử lý tin nhắn thường — luồng tìm kiếm + Gemini."""
    if not update.effective_chat or not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    if not is_allowed_chat(chat_id):
        logger.warning(
            "Bỏ qua tin nhắn — chat %s, cấu hình GROUP_CHAT_ID=%s",
            _chat_label(update),
            GROUP_CHAT_ID,
        )
        await update.message.reply_text(
            "⚠️ Bot chỉ được cấu hình cho group khác.\n"
            f"Chat ID hiện tại: `{chat_id}`\n"
            "Gõ /chatid trong group này, cập nhật `GROUP_CHAT_ID` trong `.env`, "
            "rồi khởi động lại bot.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    logger.info("Nhận câu hỏi từ %s", _chat_label(update))
    user_question = update.message.text.strip()
    if not user_question:
        return

    store = context.application.bot_data.setdefault("sessions", {})
    user_id = update.effective_user.id if update.effective_user else None
    thread_id = getattr(update.message, "message_thread_id", None)
    thread_key = f"thread:{thread_id}" if thread_id else None

    tg_user = update.effective_user
    user_name = telegram_user_display_name(tg_user)
    if user_name and user_id:
        remember_user_name("telegram", str(user_id), user_name)

    status_msg = None

    async def on_status(text: str) -> None:
        nonlocal status_msg
        if status_msg is None:
            status_msg = await update.message.reply_text(text)
        else:
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass

    result = await process_chat_message(
        user_question,
        platform="telegram",
        chat_id=str(chat_id),
        user_id=str(user_id or "0"),
        user_name=user_name,
        thread_key=thread_key,
        session_store=store,
        max_reply_length=MAX_MESSAGE_LENGTH,
        mirror_to_chat_level=True,
        cache_feedback=False,
        on_status=on_status,
    )

    if result.status == "success":
        keyboard = build_telegram_feedback_keyboard(result.response_link_url)
        try:
            if status_msg:
                await status_msg.edit_text(
                    result.reply,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
            else:
                status_msg = await update.message.reply_text(
                    result.reply,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
        except Exception:
            if status_msg:
                await status_msg.edit_text(
                    result.reply,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
            else:
                status_msg = await update.message.reply_text(
                    result.reply,
                    disable_web_page_preview=True,
                    reply_markup=keyboard,
                )
        if status_msg:
            cache_feedback_context(
                chat_id=str(chat_id),
                message_id=str(status_msg.message_id),
                user_question=user_question,
                bot_answer=result.reply,
                search_keywords=result.search_keywords,
                product_id=result.product_id,
                product_name=result.product_name,
                product_url=result.product_url,
            )
    elif status_msg:
        await status_msg.edit_text(result.reply)
    else:
        await update.message.reply_text(result.reply)


async def handle_feedback_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    if not query or not query.data:
        return

    if query.data == TELEGRAM_CB_ACK:
        await query.answer()
        return

    if query.data not in (TELEGRAM_CB_HELPFUL, TELEGRAM_CB_NOT_HELPFUL):
        await query.answer()
        return

    rating = (
        FEEDBACK_HELPFUL
        if query.data == TELEGRAM_CB_HELPFUL
        else FEEDBACK_NOT_HELPFUL
    )
    chat_id = ""
    message_id = ""
    if query.message:
        chat_id = _chat_id_str(query.message.chat_id)
        message_id = str(query.message.message_id)
    user_id = ""
    if query.from_user:
        user_id = _chat_id_str(query.from_user.id)

    ctx = get_feedback_context(chat_id, message_id)
    record_message_feedback(
        platform="telegram",
        rating=rating,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        user_question=ctx.get("user_question", ""),
        bot_answer=ctx.get("bot_answer", ""),
        search_keywords=ctx.get("search_keywords", ""),
        product_id=ctx.get("product_id", ""),
        product_name=ctx.get("product_name", ""),
        product_url=ctx.get("product_url", ""),
    )
    await query.answer("Cảm ơn bạn đã đánh giá!")
    try:
        await query.edit_message_reply_markup(
            reply_markup=build_telegram_feedback_ack_keyboard(),
        )
    except Exception:
        pass


def validate_config() -> None:
    """Kiểm tra token/key trước khi chạy."""
    placeholders = ("your_", "placeholder", "here")
    if not TELEGRAM_BOT_TOKEN or any(p in TELEGRAM_BOT_TOKEN for p in placeholders):
        raise ValueError(
            "Thiếu TELEGRAM_BOT_TOKEN — hãy điền vào file .env"
        )
    provider = LLM_PROVIDER
    if provider == "deepseek":
        if not DEEPSEEK_API_KEY or any(p in DEEPSEEK_API_KEY for p in placeholders):
            raise ValueError("LLM_PROVIDER=deepseek — cần DEEPSEEK_API_KEY trong .env")
    elif provider == "byteplus":
        from cps_bot.llm.byteplus_client import validate_byteplus_config

        validate_byteplus_config()
    elif not GEMINI_API_KEY or any(p in GEMINI_API_KEY for p in placeholders):
        raise ValueError("Thiếu GEMINI_API_KEY — hãy điền vào file .env")


def _ensure_event_loop() -> None:
    """
    Python 3.10+ (đặc biệt 3.14) không tự tạo event loop trên MainThread.
    python-telegram-bot cần loop sẵn có trước khi gọi run_polling().
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main() -> None:
    validate_config()
    _ensure_event_loop()
    logger.info("Khởi động bot... (Python %s)", sys.version.split()[0])
    if GROUP_CHAT_ID:
        logger.info("Chỉ phản hồi group/chat ID: %s", GROUP_CHAT_ID)
    else:
        logger.info("Phản hồi mọi chat (GROUP_CHAT_ID trống)")

    async def _post_init(application: Application) -> None:
        application.bot_data["sessions"] = load_session_store()

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(
        CallbackQueryHandler(handle_feedback_callback, pattern=r"^fb:")
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot đang chạy — nhấn Ctrl+C để dừng.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
