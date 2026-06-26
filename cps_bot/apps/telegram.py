"""
Telegram Bot tư vấn sản phẩm công nghệ — tích hợp Cellphones + Gemini.
"""
from __future__ import annotations

import asyncio
import logging
import time
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
    FAST_BROWSE_REPLY,
    GEMINI_API_KEY,
    GROUP_CHAT_ID,
    LLM_MAX_SEARCH_RESULTS,
    LLM_PROVIDER,
    SLIM_LLM_PAYLOAD,
    TELEGRAM_BOT_TOKEN,
)
from cps_bot.cps.cps_api import (
    attach_shop_stock_to_payload,
    classify_question_scenarios,
    enrich_payload_for_scenarios,
    fetch_product_for_query,
    is_color_variant_list_query,
    is_stock_status_browse_query,
    should_attach_shop_stock,
)
from cps_bot.core.api_trace import api_trace_scope, trace_phase
from cps_bot.core.conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_session,
    has_product_context,
    mirror_session_to_chat_level,
    resolve_session,
    session_scope_key,
)
from cps_bot.llm.disambiguation import (
    build_disambiguation_message,
    build_telegram_disambiguation_keyboard,
    resolve_disambiguation_choice,
)
from cps_bot.browse.budget_browse import is_budget_browse_query
from cps_bot.core.location_flow import handle_province_gate, shop_question_for_session
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
from cps_bot.llm.gemini_client import (
    analyze_product_with_meta,
    extract_compare_product_queries,
    extract_search_keywords,
    is_contextual_follow_up,
    llm_provider_display_name,
    needs_query_expansion,
    references_prior_product,
    should_reuse_product_identity,
    _mentions_new_product,
)
from cps_bot.browse.fast_reply import (
    build_browse_list_reply,
    build_color_sibling_reply,
    can_fast_browse_reply,
    can_fast_color_sibling_reply,
    slim_payload_for_llm,
)
from cps_bot.llm.message_intent import is_social_message, resolve_message_intent
from cps_bot.core.metrics import emit_metric
from cps_bot.core.user_display import remember_user_name, telegram_user_display_name
from cps_bot.cps.scraper import build_product_payload, build_response_link_url, format_product_links_appendix, is_browse_list_mode, product_url_from_record, should_attach_product_links_appendix
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
HELP_TEXT = (
    "📖 *Hướng dẫn sử dụng*\n\n"
    "1️⃣ Gửi câu hỏi về sản phẩm công nghệ (tiếng Việt).\n"
    "2️⃣ Bot tìm trên cellphones.com.vn và phân tích.\n"
    "3️⃣ Nhận câu trả lời kèm link sản phẩm gốc.\n\n"
    "*Lệnh:* /start · /help · /clear\n\n"
    "*Bot hỗ trợ các kịch bản:*\n"
    "💰 Giá & KM (Smember, HSSV, voucher)\n"
    "🏪 Tồn cửa hàng / shop gần địa chỉ\n"
    "♻️ Thu cũ đổi mới / trợ giá trade\\-in\n"
    "💳 Trả góp \\(thông tin từ trang SP\\)\n"
    "🛡 Bảo hành & gói BH mở rộng\n"
    "⚖️ So sánh 2 sản phẩm\n"
    "📋 Thông số kỹ thuật / tư vấn chọn mua\n\n"
    "💡 Bot nhớ ngữ cảnh vài tin gần nhất \\(vd: _còn hàng không?_\\).\n\n"
    "⚠️ Giá, tồn kho, trả góp chi tiết có thể thay đổi — xem thêm trên website."
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
    session_key = session_scope_key(chat_id, user_id, thread_key=thread_key)

    pending = session.get("pending_disambiguation") or []
    disambig_pick = resolve_disambiguation_choice(user_question, pending) if pending else None
    forced_product_url = ""
    if disambig_pick:
        session.pop("pending_disambiguation", None)
        forced_product_url = product_url_from_record(disambig_pick)

    context_session = resolve_session(
        store, chat_id, user_id, thread_key=thread_key
    )
    conversation_context = format_context_block(context_session)
    social = is_social_message(user_question)
    is_follow_up = (
        not social
        and is_contextual_follow_up(user_question, conversation_context)
    )
    reuse_product_context = not social and (
        is_follow_up
        or references_prior_product(user_question)
        or (
            has_product_context(context_session)
            and not _mentions_new_product(user_question)
        )
    )
    last_product = context_session.get("last_product") or {}
    reuse_product_identity = should_reuse_product_identity(
        user_question,
        conversation_context,
        last_keywords=context_session.get("last_keywords") or "",
        last_product_name=last_product.get("name") or "",
    )
    started = time.perf_counter()
    tg_user = update.effective_user
    user_name = telegram_user_display_name(tg_user)
    if user_name and user_id:
        remember_user_name("telegram", str(user_id), user_name)
    metric_data: dict[str, object] = {
        "platform": "telegram",
        "chat_id": str(chat_id),
        "user_id": str(user_id or ""),
        "user_name": user_name,
        "is_follow_up": is_follow_up,
        "question_len": len(user_question),
        "llm_provider": LLM_PROVIDER,
    }

    intent = resolve_message_intent(
        user_question,
        conversation_context=conversation_context,
        has_product_context=has_product_context(context_session),
        is_follow_up=is_follow_up,
        has_pending_disambiguation=bool(pending),
        has_pending_province=bool(session.get("pending_province_for")),
    )
    if intent.kind != "product" and intent.reply:
        metric_data["intent"] = intent.kind
        metric_data["status"] = f"intent_{intent.kind}"
        await update.message.reply_text(intent.reply)
        append_turn(
            session,
            user=user_question,
            assistant=intent.reply,
            keywords="",
            product_name="",
            product_url="",
            session_key=session_key,
        )
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return

    province_gate = handle_province_gate(
        user_question,
        session,
        has_product_context=has_product_context(context_session),
    )
    if province_gate.should_ask:
        session["pending_province_for"] = province_gate.pending_kind
        metric_data["status"] = "ask_province"
        metric_data["pending_province_for"] = province_gate.pending_kind
        await update.message.reply_text(province_gate.reply, parse_mode=ParseMode.MARKDOWN)
        append_turn(
            session,
            user=user_question,
            assistant=province_gate.reply,
            keywords="",
            product_name="",
            product_url="",
            session_key=session_key,
        )
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return

    query_province_id = province_gate.province_id
    resume_shop_stock = session.pop("resume_shop_stock", False)
    resume_store_locator = session.pop("resume_store_locator", False)
    shop_question = (
        shop_question_for_session(session, user_question)
        if resume_shop_stock or resume_store_locator
        else user_question
    )

    status_msg = await update.message.reply_text("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    response_link_url = ""
    try:
        compare_queries = extract_compare_product_queries(user_question)

        # Bước 0: bóc tách từ khóa từ CÂU MỚI (context chỉ hỗ trợ hỏi tiếp ngắn)
        t0 = time.perf_counter()
        kw_context = conversation_context if reuse_product_context else ""
        if compare_queries:
            search_keywords = compare_queries[0]
        else:
            stock_browse = is_stock_status_browse_query(user_question)
            budget_browse = is_budget_browse_query(user_question)
            if needs_query_expansion(user_question) and not stock_browse and not budget_browse:
                await status_msg.edit_text("✍️ Đang hiểu câu hỏi của bạn...")
            search_keywords = await asyncio.to_thread(
                extract_search_keywords, user_question, kw_context
            )
        metric_data["latency_keyword_ms"] = int((time.perf_counter() - t0) * 1000)
        stock_browse = is_stock_status_browse_query(user_question)
        budget_browse = is_budget_browse_query(user_question)
        if not search_keywords and not stock_browse and not budget_browse:
            clarify = resolve_message_intent(
                user_question,
                conversation_context=conversation_context,
                has_product_context=has_product_context(context_session),
                is_follow_up=is_follow_up,
            ).reply
            await status_msg.edit_text(
                clarify or "😔 Không hiểu được sản phẩm bạn cần tìm."
            )
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
        fallback_product_id: str | int = ""
        session_fallback_parent_id: str | int = ""
        session_last_keywords = context_session.get("last_keywords") or ""
        session_last_product_name = last_product.get("name") or ""
        if forced_product_url:
            fallback_url = forced_product_url
        elif reuse_product_identity or (
            is_color_variant_list_query(user_question)
            and last_product.get("product_id")
            and has_product_context(context_session)
        ):
            fallback_url = last_product.get("url") or ""
            fallback_product_id = last_product.get("product_id") or ""
            session_fallback_parent_id = last_product.get("parent_id") or ""

        # Bước 1: search / link / CPS GraphQL detail (hoặc so sánh 2 SP)
        if (stock_browse or budget_browse) and not search_keywords:
            await status_msg.edit_text("🔍 Đang tìm sản phẩm phù hợp...")
        else:
            await status_msg.edit_text(f"🔍 Đang tìm: _{search_keywords}_...")
        t1 = time.perf_counter()
        compare_products: list[dict[str, Any]] = []
        if compare_queries:
            await status_msg.edit_text("⚖️ Đang so sánh 2 sản phẩm...")
            fetch_stats: dict[str, Any] = {}
            for idx, kw in enumerate(compare_queries[:2]):
                sub_results, sub_detail, sub_stats = await fetch_product_for_query(
                    kw,
                    user_message=user_question,
                )
                for key, val in sub_stats.items():
                    if isinstance(val, int):
                        fetch_stats[key] = int(fetch_stats.get(key, 0)) + val
                    elif key == "resolve_source" and val:
                        fetch_stats[key] = val
                    elif key == "api_calls_detail":
                        from cps_bot.core.api_trace import merge_api_calls_detail

                        merge_api_calls_detail(fetch_stats, sub_stats)
                if sub_detail:
                    compare_products.append(sub_detail)
            results = []
            detail = compare_products[0] if compare_products else {}
        else:
            results, detail, fetch_stats = await fetch_product_for_query(
                search_keywords,
                user_message=user_question,
                fallback_url=fallback_url,
                fallback_product_id=fallback_product_id,
                session_fallback_parent_id=session_fallback_parent_id,
                session_last_keywords=session_last_keywords,
                session_last_product_name=session_last_product_name,
            )
        metric_data["latency_fetch_ms"] = int((time.perf_counter() - t1) * 1000)
        metric_data.update(fetch_stats)
        if fetch_stats.get("resolved_filter_url"):
            metric_data["search_keywords"] = fetch_stats["resolved_filter_url"]
        if compare_queries and len(compare_products) < 2:
            await status_msg.edit_text(
                "😔 Chưa tìm đủ 2 sản phẩm để so sánh.\n"
                "Thử gõ rõ tên từng máy, vd: _So sánh iPhone 16 Pro Max và S25 Ultra_"
            )
            metric_data["status"] = "compare_not_found"
            emit_metric(
                "chat_message",
                **metric_data,
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return
        if not results and not detail:
            scenarios = classify_question_scenarios(shop_question)
            if scenarios.get("store_locator") or resume_store_locator:
                detail = {
                    "name": "Cửa hàng CellphoneS",
                    "product_id": "",
                    "url": "",
                    "price": "",
                }
            else:
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

        if fetch_stats.get("ambiguous_search") and len(results) >= 2:
            session["pending_disambiguation"] = results[:3]
            metric_data["ambiguous_search"] = True

        metric_data["resolve_source"] = fetch_stats.get("resolve_source", "")

        # Bước 2: đã có chi tiết từ CPS API
        await status_msg.edit_text(
            "📦 Đã tìm thấy sản phẩm. Đang phân tích dữ liệu..."
        )
        product_url = product_url_from_record(detail) or (
            product_url_from_record(results[0]) if results else ""
        )
        if compare_products:
            payload = {
                "compare_mode": True,
                "compare_products": compare_products,
                "primary_product": compare_products[0],
                "search_results": [
                    {
                        "name": p.get("name", ""),
                        "price": p.get("price", ""),
                        "url": p.get("url", ""),
                        "product_id": p.get("product_id", ""),
                    }
                    for p in compare_products
                ],
            }
            response_link_url = product_url_from_record(compare_products[0]) or ""
            metric_data["compare_mode"] = True
        else:
            payload = build_product_payload(results, detail)
            response_link_url = build_response_link_url(
                search_results=results,
                detail=detail,
                search_keywords=search_keywords,
            )

        shop_ctx = None
        if (
            detail.get("product_id")
            and not detail.get("stock_browse_list_mode")
            and not detail.get("budget_browse_list_mode")
            and should_attach_shop_stock(
                shop_question,
                resume=resume_shop_stock,
                reuse_product_context=reuse_product_context,
            )
        ):
            metric_data["shop_stock_trigger"] = True
            await status_msg.edit_text("🏪 Đang kiểm tra tồn cửa hàng...")
            async with api_trace_scope(metric_data):
                with trace_phase("shop_stock"):
                    shop_ctx = await attach_shop_stock_to_payload(
                        payload,
                        detail,
                        user_question=shop_question,
                        province_id=query_province_id,
                    )
        if shop_ctx:
            metric_data["shop_stock_scenario"] = True
            metric_data["shop_stock_matched"] = shop_ctx.get("matched_shops_count", 0)

        browse_list = is_browse_list_mode(detail)
        scenario_flags: dict[str, bool] = {}
        if not browse_list:
            scenario_flags = await enrich_payload_for_scenarios(
                payload,
                detail,
                user_question=shop_question,
                province_id=query_province_id,
                api_trace_stats=metric_data,
            )
            if scenario_flags:
                metric_data["scenario_enrich"] = scenario_flags

        t2 = time.perf_counter()
        gemini_meta: dict[str, Any] = {}
        if can_fast_color_sibling_reply(payload, user_question):
            answer = build_color_sibling_reply(
                user_question,
                payload,
                response_link_url=response_link_url,
            )
            metric_data["fast_color_sibling_reply"] = True
            metric_data["gemini_model"] = "template"
        elif FAST_BROWSE_REPLY and can_fast_browse_reply(detail, payload.get("search_results") or []):
            answer = build_browse_list_reply(
                user_question,
                detail,
                payload.get("search_results") or [],
                response_link_url=response_link_url,
            )
            metric_data["fast_browse_reply"] = True
            metric_data["gemini_model"] = "template"
        else:
            llm_label = llm_provider_display_name()
            await status_msg.edit_text(f"🤖 Đang phân tích với {llm_label}...")
            llm_payload = (
                slim_payload_for_llm(payload, max_results=LLM_MAX_SEARCH_RESULTS)
                if SLIM_LLM_PAYLOAD
                else payload
            )
            answer, gemini_meta = await asyncio.to_thread(
                analyze_product_with_meta,
                user_question,
                llm_payload,
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
        search_list = payload.get("search_results") or []
        scenarios = payload.get("question_scenarios") or {}
        if should_attach_product_links_appendix(
            detail,
            scenarios=scenarios,
            compare_mode=bool(metric_data.get("compare_mode")),
            ambiguous_search=bool(fetch_stats.get("ambiguous_search")),
            fast_browse_reply=bool(metric_data.get("fast_browse_reply")),
        ):
            appendix = format_product_links_appendix(search_list)
            if appendix and appendix not in answer:
                answer = truncate_message(f"{answer}{appendix}")

        disambig_msg = build_disambiguation_message(results) if fetch_stats.get("ambiguous_search") else ""
        if disambig_msg and disambig_msg not in answer:
            answer = truncate_message(f"{answer}\n\n{disambig_msg}")

        product_name = (detail.get("name") or (results[0].get("name") if results else "") or "").strip()
        append_turn(
            session,
            user=user_question,
            assistant=answer,
            keywords=search_keywords,
            product_name=product_name,
            product_url=product_url,
            product_id=detail.get("product_id", ""),
            parent_product_id=detail.get("parent_id", ""),
            session_key=session_key,
        )
        mirror_session_to_chat_level(store, chat_id, user_id, session)

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
        cache_feedback_context(
            chat_id=chat_id,
            message_id=str(status_msg.message_id),
            user_question=user_question,
            bot_answer=answer,
            search_keywords=search_keywords,
            product_id=str(detail.get("product_id") or ""),
            product_name=product_name,
            product_url=product_url,
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
