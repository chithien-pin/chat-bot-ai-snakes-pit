"""
Telegram Bot tư vấn sản phẩm công nghệ — tích hợp Cellphones + Gemini.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import GEMINI_API_KEY, GROUP_CHAT_ID, TELEGRAM_BOT_TOKEN
from gemini_client import analyze_product
from scraper import build_product_payload, get_product_detail, search_products

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
    "• _iPhone 15 Pro Max giá bao nhiêu?_\n"
    "• _Laptop gaming dưới 20 triệu_\n"
    "• _Samsung Galaxy S25 có còn hàng không?_\n\n"
    "Gõ /help để xem hướng dẫn."
)
HELP_TEXT = (
    "📖 *Hướng dẫn sử dụng*\n\n"
    "1️⃣ Gửi câu hỏi về sản phẩm công nghệ (tiếng Việt).\n"
    "2️⃣ Bot sẽ tìm trên cellphones.com.vn và phân tích.\n"
    "3️⃣ Nhận câu trả lời kèm nút xem sản phẩm gốc.\n\n"
    "*Lệnh:*\n"
    "/start — Chào mừng\n"
    "/help — Hướng dẫn\n\n"
    "⚠️ Giá và tồn kho có thể thay đổi theo thời gian thực tế trên website."
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
        HELP_TEXT,
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

    status_msg = await update.message.reply_text("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    try:
        # Bước 1: tìm kiếm sản phẩm
        results = await search_products(user_question)
        if not results:
            await status_msg.edit_text(
                "😔 Không tìm thấy sản phẩm phù hợp trên CellphoneS.\n"
                "Thử hỏi lại với tên sản phẩm cụ thể hơn nhé!"
            )
            return

        # Bước 2: lấy chi tiết sản phẩm đầu tiên
        await status_msg.edit_text(
            "📦 Đã tìm thấy sản phẩm. Đang lấy thông số chi tiết..."
        )
        product_url = results[0].get("url", "")
        detail = await get_product_detail(product_url) if product_url else {}
        payload = build_product_payload(results, detail)

        # Bước 3: phân tích bằng Gemini (chạy sync trong thread pool)
        await status_msg.edit_text("🤖 Đang phân tích với Gemini AI...")
        answer = await asyncio.to_thread(
            analyze_product,
            user_question,
            payload,
        )
        answer = truncate_message(answer)

        # Nút xem trên Cellphones
        keyboard = None
        if product_url:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔗 Xem trên Cellphones",
                            url=product_url,
                        )
                    ]
                ]
            )

        try:
            await status_msg.edit_text(
                answer,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )
        except Exception:
            # Markdown lỗi định dạng → gửi plain text
            await status_msg.edit_text(
                answer,
                disable_web_page_preview=True,
                reply_markup=keyboard,
            )

    except Exception as exc:
        logger.exception("Lỗi xử lý tin nhắn: %s", exc)
        friendly = (
            "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu.\n"
            "Vui lòng thử lại sau ít phút.\n\n"
            f"_Chi tiết: {escape_markdown(str(exc)[:200])}_"
        )
        try:
            await status_msg.edit_text(friendly, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            await update.message.reply_text(
                "⚠️ Đã xảy ra lỗi. Vui lòng thử lại sau."
            )


def validate_config() -> None:
    """Kiểm tra token/key trước khi chạy."""
    placeholders = ("your_", "placeholder", "here")
    if not TELEGRAM_BOT_TOKEN or any(p in TELEGRAM_BOT_TOKEN for p in placeholders):
        raise ValueError(
            "Thiếu TELEGRAM_BOT_TOKEN — hãy điền vào file .env"
        )
    if not GEMINI_API_KEY or any(p in GEMINI_API_KEY for p in placeholders):
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

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("chatid", cmd_chatid))
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Bot đang chạy — nhấn Ctrl+C để dừng.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
