"""
Telegram Bot tư vấn sản phẩm công nghệ — tích hợp Cellphones + Gemini.
"""
from __future__ import annotations

import asyncio
import logging
import time
import sys
import re

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

from config import GEMINI_API_KEY, GROUP_CHAT_ID, LLM_PROVIDER, TELEGRAM_BOT_TOKEN
from cps_api import attach_shop_stock_to_payload, fetch_product_for_query
from conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_session,
)
from feedback import (
    FEEDBACK_HELPFUL,
    FEEDBACK_NOT_HELPFUL,
    TELEGRAM_CB_ACK,
    TELEGRAM_CB_HELPFUL,
    TELEGRAM_CB_NOT_HELPFUL,
    build_telegram_feedback_ack_keyboard,
    build_telegram_feedback_keyboard,
    record_message_feedback,
)
from gemini_client import (
    analyze_product_with_meta,
    extract_search_keywords,
    is_contextual_follow_up,
    needs_query_expansion,
)
from metrics import emit_metric
from scraper import build_product_payload, build_response_link_url, product_url_from_record

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
    "• _Samsung Galaxy S25 có còn hàng không?_\n"
    "• _iPhone 16 Pro còn hàng ở cửa hàng nào?_\n"
    "• _Gần 288 3 Tháng 2 shop nào còn iPhone 16 Pro?_\n\n"
    "Gõ /help để xem hướng dẫn."
)
HELP_TEXT = (
    "📖 *Hướng dẫn sử dụng*\n\n"
    "1️⃣ Gửi câu hỏi về sản phẩm công nghệ (tiếng Việt).\n"
    "2️⃣ Bot sẽ tìm trên cellphones.com.vn và phân tích.\n"
    "3️⃣ Nhận câu trả lời kèm nút xem sản phẩm gốc.\n\n"
    "*Lệnh:*\n"
    "/start — Chào mừng\n"
    "/help — Hướng dẫn\n"
    "/clear — Xóa ngữ cảnh hội thoại\n\n"
    "💡 Bot nhớ vài tin gần nhất trong cùng chat để hiểu câu hỏi tiếp "
    "(vd: _còn hàng không?_ sau khi hỏi iPhone).\n\n"
    "🏪 *Kiểm tra tồn cửa hàng:* hỏi shop/chi nhánh còn hàng hoặc gần địa chỉ "
    "(vd: _Gần Nguyễn Trãi shop nào còn Samsung S25?_).\n\n"
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

    store = context.application.bot_data.setdefault("sessions", {})
    user_id = update.effective_user.id if update.effective_user else None
    thread_id = getattr(update.message, "message_thread_id", None)
    thread_key = f"thread:{thread_id}" if thread_id else None
    session = get_session(store, chat_id, user_id, thread_key=thread_key)
    conversation_context = format_context_block(session)
    is_follow_up = is_contextual_follow_up(user_question, conversation_context)
    started = time.perf_counter()
    metric_data: dict[str, object] = {
        "platform": "telegram",
        "chat_id": str(chat_id),
        "user_id": str(user_id or ""),
        "is_follow_up": is_follow_up,
        "question_len": len(user_question),
    }

    status_msg = await update.message.reply_text("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    response_link_url = ""
    try:
        # Bước 0: bóc tách từ khóa từ CÂU MỚI (context chỉ hỗ trợ hỏi tiếp ngắn)
        t0 = time.perf_counter()
        kw_context = conversation_context if is_follow_up else ""
        if needs_query_expansion(user_question):
            await status_msg.edit_text("✍️ Đang hiểu câu hỏi của bạn...")
        search_keywords = await asyncio.to_thread(
            extract_search_keywords, user_question, kw_context
        )
        metric_data["latency_keyword_ms"] = int((time.perf_counter() - t0) * 1000)
        if not search_keywords:
            await status_msg.edit_text("😔 Không hiểu được sản phẩm bạn cần tìm.")
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

        # Bước 1: search / link / CPS GraphQL detail
        await status_msg.edit_text(f"🔍 Đang tìm: _{search_keywords}_...")
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
                f"\n\n_Từ khóa đã tìm: {search_keywords}_"
                if search_keywords != user_question
                else ""
            )
            await status_msg.edit_text(
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

        # Bước 2: đã có chi tiết từ CPS API
        await status_msg.edit_text(
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
            await status_msg.edit_text("🏪 Đang kiểm tra tồn cửa hàng...")
        shop_ctx = await attach_shop_stock_to_payload(
            payload, detail, user_question=user_question
        )
        if shop_ctx:
            metric_data["shop_stock_scenario"] = True
            metric_data["shop_stock_matched"] = shop_ctx.get("matched_shops_count", 0)

        # Bước 3: phân tích bằng Gemini (chạy sync trong thread pool)
        llm_label = "DeepSeek" if LLM_PROVIDER == "deepseek" else "Gemini AI"
        await status_msg.edit_text(f"🤖 Đang phân tích với {llm_label}...")
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

        # Interactive card: đánh giá + link Cellphones
        keyboard = build_telegram_feedback_keyboard(response_link_url)

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
        metric_data["status"] = "error"
        metric_data["error"] = str(exc)[:200]
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )


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

    record_message_feedback(
        platform="telegram",
        rating=rating,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
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
