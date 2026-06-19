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
    BYTEPLUS_API_KEY,
    DEEPSEEK_API_KEY,
    GEMINI_API_KEY,
    LLM_PROVIDER,
    LARK_API_DOMAIN,
    LARK_APP_ID,
    LARK_APP_SECRET,
    LARK_CHAT_ID,
    LARK_THREAD_AUTO_REPLY,
    LARK_BOT_MENTION_NAMES,
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
from cps_api import (
    attach_shop_stock_to_payload,
    classify_question_scenarios,
    enrich_payload_for_scenarios,
    fetch_product_for_query,
    is_shop_stock_question,
    is_stock_status_browse_query,
)
from conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_any_session_in_topic,
    get_session,
    has_product_context,
    has_thread_conversation,
    mirror_session_to_chat_level,
    resolve_session,
    session_scope_key,
)
from disambiguation import build_disambiguation_message, resolve_disambiguation_choice
from gemini_client import (
    analyze_product_with_meta,
    extract_compare_product_queries,
    extract_search_keywords,
    is_contextual_follow_up,
    llm_provider_display_name,
    needs_query_expansion,
    _mentions_new_product,
)
from metrics import emit_metric
from message_intent import is_social_message, resolve_message_intent
from budget_browse import is_budget_browse_query
from location_flow import handle_province_gate, shop_question_for_session
from scraper import build_product_payload, build_response_link_url, format_product_links_appendix, product_url_from_record
from session_store import (
    delete_active_topic,
    load_active_topics,
    load_session_store,
    load_topic_aliases,
    persist_active_topic,
    persist_topic_alias,
    rebuild_active_topics_from_sessions,
)

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
    "• Giá iPhone 16 Pro Max 256GB hôm nay?\n"
    "• SVIP/HSSV mua MacBook Air M2 giảm bao nhiêu?\n"
    "• Shop còn iPhone 16 Plus 256 màu hồng không?\n"
    "• Gần 288 3 Tháng 2 shop nào còn iPhone 16 Pro?\n"
    "• Lên đời iPhone được trợ giá thu cũ bao nhiêu?\n"
    "• So sánh S26 Ultra và S25 Ultra\n\n"
    "Trong topic: @bot lần đầu, các câu tiếp theo không cần @.\n"
    "Gõ /help để xem hướng dẫn."
)
HELP_TEXT = (
    "📖 Hướng dẫn sử dụng\n\n"
    "1️⃣ Gửi câu hỏi về sản phẩm công nghệ (tiếng Việt).\n"
    "2️⃣ Bot tìm trên cellphones.com.vn và phân tích.\n"
    "3️⃣ Nhận câu trả lời kèm link sản phẩm gốc.\n\n"
    "Lệnh: /start · /help · /clear · /chatid\n\n"
    "Trong topic Lark: @bot một lần, hỏi tiếp không cần @ lại.\n\n"
    "Bot hỗ trợ: giá & KM (Smember/HSSV), tồn cửa hàng, thu cũ đổi mới, "
    "trả góp, bảo hành, so sánh 2 SP, thông số & tư vấn chọn mua.\n\n"
    "💡 Bot nhớ ngữ cảnh vài tin gần nhất.\n\n"
    "⚠️ Giá và tồn kho có thể thay đổi theo thời gian thực trên website."
)

_sessions: dict[str, Any] = load_session_store()
# Topic đã @bot hoặc bot đã trả lời — scope = chat_id:canonical
_active_topics: set[str] = load_active_topics() | rebuild_active_topics_from_sessions(_sessions)
# Alias chat_id:thread_id|root_id|parent_id|message_id → canonical topic id
_topic_alias_map: dict[str, str] = load_topic_aliases()
for _scope in list(_active_topics):
    if ":" not in _scope:
        continue
    _cid, _canon = _scope.split(":", 1)
    if _cid and _canon:
        _topic_alias_map[f"{_cid}:{_canon}"] = _canon
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


def _collect_topic_aliases(msg: lark.im.v1.EventMessage) -> list[str]:
    """Mọi định danh có thể của cùng một topic Lark."""
    aliases: list[str] = []
    for raw in (msg.thread_id, msg.root_id, msg.parent_id, msg.message_id):
        value = (raw or "").strip()
        if value and value not in aliases:
            aliases.append(value)
    return aliases


def _topic_scope_key(chat_id: str, canonical: str) -> str:
    return f"{chat_id}:{canonical}"


def _alias_map_key(chat_id: str, alias: str) -> str:
    return f"{chat_id}:{alias}"


def _active_canonical_for_aliases(chat_id: str, aliases: list[str]) -> str:
    """Khớp alias với topic đã active (root_id thường = message_id tin đầu)."""
    prefix = f"{chat_id}:"
    active_suffixes = {
        scope[len(prefix) :]
        for scope in _active_topics
        if scope.startswith(prefix)
    }
    for alias in aliases:
        if alias in active_suffixes:
            return alias
    return ""


def _canonical_topic_id(
    msg: lark.im.v1.EventMessage,
    *,
    chat_id: str = "",
) -> str:
    """
    Gộp thread_id / root_id / parent_id / message_id thành một id topic ổn định.
    Ưu tiên alias đã biết hoặc topic active — tránh lệch thread_id vs root_id.
    """
    cid = (chat_id or msg.chat_id or "").strip()
    aliases = _collect_topic_aliases(msg)
    if not aliases:
        return ""

    canonical: str | None = None
    if cid:
        for alias in aliases:
            mapped = _topic_alias_map.get(_alias_map_key(cid, alias))
            if mapped:
                canonical = mapped
                break
        if not canonical:
            canonical = _active_canonical_for_aliases(cid, aliases) or None

    if not canonical:
        thread_id = (msg.thread_id or "").strip()
        root_id = (msg.root_id or "").strip()
        parent_id = (msg.parent_id or "").strip()
        message_id = (msg.message_id or "").strip()
        canonical = thread_id or root_id or parent_id or message_id

    if cid:
        for alias in aliases:
            key = _alias_map_key(cid, alias)
            _topic_alias_map[key] = canonical
            persist_topic_alias(cid, alias, canonical)
    return canonical


def _thread_key_for_session(
    msg: lark.im.v1.EventMessage,
    *,
    chat_id: str = "",
) -> str:
    canonical = _canonical_topic_id(msg, chat_id=chat_id)
    return f"topic:{canonical}" if canonical else ""


def _link_bot_message_to_topic(
    trigger_msg: lark.im.v1.EventMessage,
    bot_message_id: str,
    *,
    chat_id: str = "",
) -> None:
    """Follow-up reply vào tin bot vẫn map về cùng topic."""
    mid = (bot_message_id or "").strip()
    cid = (chat_id or trigger_msg.chat_id or "").strip()
    if not mid or not cid:
        return
    canonical = _canonical_topic_id(trigger_msg, chat_id=cid)
    if canonical:
        _topic_alias_map[_alias_map_key(cid, mid)] = canonical
        persist_topic_alias(cid, mid, canonical)


def _after_bot_reply(
    msg: lark.im.v1.EventMessage,
    bot_message_id: str,
    *,
    chat_id: str,
) -> None:
    _link_bot_message_to_topic(msg, bot_message_id, chat_id=chat_id)
    _activate_topic(msg, chat_id=chat_id)


def _activate_topic(msg: lark.im.v1.EventMessage, *, chat_id: str = "") -> None:
    cid = (chat_id or msg.chat_id or "").strip()
    canonical = _canonical_topic_id(msg, chat_id=cid)
    if canonical and cid:
        scope = _topic_scope_key(cid, canonical)
        _active_topics.add(scope)
        persist_active_topic(scope)


def _is_active_topic(msg: lark.im.v1.EventMessage, *, chat_id: str = "") -> bool:
    cid = (chat_id or msg.chat_id or "").strip()
    if not cid:
        return False
    for alias in _collect_topic_aliases(msg):
        mapped = _topic_alias_map.get(_alias_map_key(cid, alias))
        if mapped and _topic_scope_key(cid, mapped) in _active_topics:
            return True
        if _topic_scope_key(cid, alias) in _active_topics:
            return True
    canonical = _canonical_topic_id(msg, chat_id=cid)
    if not canonical:
        return False
    return _topic_scope_key(cid, canonical) in _active_topics


def _deactivate_topic_by_key(thread_key: str | None, *, chat_id: str = "") -> None:
    if not thread_key:
        return
    prefix = "topic:"
    if thread_key.startswith(prefix):
        canonical = thread_key[len(prefix) :]
        if chat_id and canonical:
            scope = _topic_scope_key(chat_id, canonical)
            _active_topics.discard(scope)
            delete_active_topic(scope)


def _message_mentions_bot(msg: lark.im.v1.EventMessage) -> bool:
    mentions = msg.mentions or []
    if not mentions:
        return False
    custom_names = [
        n.strip().lower()
        for n in LARK_BOT_MENTION_NAMES.split(",")
        if n.strip()
    ]
    default_tokens = (
        "snake", "gemini", "bot", "cellphone", "tư vấn", "tu van",
        "chatbot", "chat bot", "ai bot",
    )
    for mention in mentions:
        if (mention.mentioned_type or "").lower() == "app":
            return True
        name = (mention.name or "").lower()
        if custom_names and any(cn in name or name in cn for cn in custom_names):
            return True
        if any(token in name for token in default_tokens):
            return True
    return False


def _should_process_group_message(
    msg: lark.im.v1.EventMessage,
    *,
    chat_id: str = "",
    user_id: str | None = None,
    user_text: str = "",
) -> tuple[bool, str]:
    """
    Quyết định có xử lý tin nhắn group/topic.
    Trả (should_process, reason).
    """
    chat_type = (msg.chat_type or "").lower()
    if chat_type in ("p2p", "private"):
        return True, "p2p"

    if _message_mentions_bot(msg):
        _activate_topic(msg, chat_id=chat_id)
        return True, "mention"

    if LARK_THREAD_AUTO_REPLY and _is_active_topic(msg, chat_id=chat_id):
        return True, "active_thread"

    # Bot đã từng trả lời trong thread/topic này (session có turns)
    if LARK_THREAD_AUTO_REPLY and chat_id:
        canonical = _canonical_topic_id(msg, chat_id=chat_id)
        topic_session = get_any_session_in_topic(_sessions, chat_id, canonical)
        if has_thread_conversation(topic_session):
            _activate_topic(msg, chat_id=chat_id)
            return True, "thread_history"

    # Đã hỏi SP trước đó — câu tiếp không nhắc SP mới thì không cần @
    if LARK_THREAD_AUTO_REPLY and chat_id and user_text:
        canonical = _canonical_topic_id(msg, chat_id=chat_id)
        topic_session = get_any_session_in_topic(_sessions, chat_id, canonical)
        user_session = resolve_session(
            _sessions,
            chat_id,
            user_id,
            thread_key=f"topic:{canonical}" if canonical else None,
        )
        session = topic_session if has_product_context(topic_session) else user_session
        if has_product_context(session) and not _mentions_new_product(user_text):
            _activate_topic(msg, chat_id=chat_id)
            return True, "session_product_context"

    # Fallback: câu hỏi tiếp ngắn (còn hàng?, giá sao?, …)
    if LARK_THREAD_AUTO_REPLY and chat_id and user_text:
        canonical = _canonical_topic_id(msg, chat_id=chat_id)
        topic_session = get_any_session_in_topic(_sessions, chat_id, canonical)
        user_session = resolve_session(
            _sessions,
            chat_id,
            user_id,
            thread_key=f"topic:{canonical}" if canonical else None,
        )
        session = topic_session if topic_session.get("turns") else user_session
        ctx = format_context_block(session)
        if ctx and is_contextual_follow_up(user_text, ctx):
            _activate_topic(msg, chat_id=chat_id)
            return True, "session_follow_up"

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

    def send_final(self, text: str) -> str:
        if self.status_message_id:
            if self._update(self.status_message_id, text, msg_type="text"):
                return self.status_message_id
        return self.reply(text)

    def send_final_interactive(self, card: dict[str, Any]) -> str:
        # Lark không cho update tin text → interactive (lỗi invalid msg_type).
        # Rút gọn tin trạng thái cũ, gửi card interactive reply mới.
        if self.status_message_id:
            self._update(self.status_message_id, "✅", msg_type="text")
        return self.reply_interactive(card)

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
    clear_session(_sessions, chat_id, user_id, thread_key=None)
    _deactivate_topic_by_key(thread_key, chat_id=chat_id)
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
    thread_key = _thread_key_for_session(msg, chat_id=chat_id)
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
        msg,
        chat_id=chat_id,
        user_id=user_id,
        user_text=raw_text,
    )
    if not should_process:
        logger.info(
            "Bỏ qua tin group không @bot — chat=%s topic=%s parent=%s aliases=%s active=%s",
            chat_id,
            _canonical_topic_id(msg, chat_id=chat_id),
            (msg.parent_id or "").strip(),
            _collect_topic_aliases(msg),
            sorted(_active_topics),
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
    session_key = session_scope_key(chat_id, user_id, thread_key=thread_key or None)

    pending = session.get("pending_disambiguation") or []
    disambig_pick = resolve_disambiguation_choice(user_question, pending) if pending else None
    forced_product_url = ""
    if disambig_pick:
        session.pop("pending_disambiguation", None)
        forced_product_url = product_url_from_record(disambig_pick)

    context_session = resolve_session(
        _sessions,
        chat_id,
        user_id,
        thread_key=thread_key or None,
    )
    conversation_context = format_context_block(context_session)
    social = is_social_message(user_question)
    is_follow_up = (
        not social
        and is_contextual_follow_up(user_question, conversation_context)
    )
    reuse_product_context = not social and (
        is_follow_up
        or (
            has_product_context(context_session)
            and not _mentions_new_product(user_question)
        )
    )
    started = time.perf_counter()
    metric_data: dict[str, object] = {
        "platform": "lark",
        "chat_id": str(chat_id),
        "user_id": str(user_id or ""),
        "thread_key": thread_key,
        "process_reason": process_reason,
        "is_follow_up": is_follow_up,
        "reuse_product_context": reuse_product_context,
        "question_len": len(user_question),
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
        bot_mid = messenger.send_final(intent.reply)
        _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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
        bot_mid = messenger.send_final(province_gate.reply)
        _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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

    messenger.update_status("🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    response_link_url = ""
    try:
        compare_queries = extract_compare_product_queries(user_question)
        t0 = time.perf_counter()
        kw_context = (
            conversation_context if reuse_product_context else ""
        )
        if compare_queries:
            search_keywords = compare_queries[0]
        else:
            stock_browse = is_stock_status_browse_query(user_question)
            budget_browse = is_budget_browse_query(user_question)
            if needs_query_expansion(user_question) and not stock_browse and not budget_browse:
                messenger.update_status("✍️ Đang hiểu câu hỏi của bạn...")
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
            bot_mid = messenger.send_final(
                clarify or "😔 Không hiểu được sản phẩm bạn cần tìm."
            )
            _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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
        if forced_product_url:
            fallback_url = forced_product_url
        elif reuse_product_context:
            last_product = context_session.get("last_product") or {}
            fallback_url = last_product.get("url") or ""

        if (stock_browse or budget_browse) and not search_keywords:
            messenger.update_status("🔍 Đang tìm sản phẩm phù hợp...")
        else:
            messenger.update_status(f"🔍 Đang tìm: {search_keywords}...")
        response_link_url = ""
        t1 = time.perf_counter()
        compare_products: list[dict[str, Any]] = []
        if compare_queries:
            messenger.update_status("⚖️ Đang so sánh 2 sản phẩm...")
            fetch_stats: dict[str, Any] = {}
            for kw in compare_queries[:2]:
                sub_results, sub_detail, sub_stats = await fetch_product_for_query(
                    kw,
                    user_message=user_question,
                )
                for key, val in sub_stats.items():
                    if isinstance(val, int):
                        fetch_stats[key] = int(fetch_stats.get(key, 0)) + val
                    elif key == "resolve_source" and val:
                        fetch_stats[key] = val
                if sub_detail:
                    compare_products.append(sub_detail)
            results = []
            detail = compare_products[0] if compare_products else {}
        else:
            results, detail, fetch_stats = await fetch_product_for_query(
                search_keywords,
                user_message=user_question,
                fallback_url=fallback_url,
            )
        metric_data["latency_fetch_ms"] = int((time.perf_counter() - t1) * 1000)
        metric_data.update(fetch_stats)
        if compare_queries and len(compare_products) < 2:
            bot_mid = messenger.send_final(
                "😔 Chưa tìm đủ 2 sản phẩm để so sánh.\n"
                "Thử gõ rõ tên từng máy, vd: So sánh iPhone 16 Pro Max và S25 Ultra"
            )
            _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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
                    f"\n\nTừ khóa đã tìm: {search_keywords}"
                    if search_keywords != user_question
                    else ""
                )
                bot_mid = messenger.send_final(
                    "😔 Không tìm thấy sản phẩm phù hợp trên CellphoneS.\n"
                    "Thử hỏi lại với tên sản phẩm cụ thể hơn nhé!"
                    f"{hint}"
                )
                _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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

        messenger.update_status(
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
            and (is_shop_stock_question(shop_question) or resume_shop_stock)
        ):
            messenger.update_status("🏪 Đang kiểm tra tồn cửa hàng...")
            shop_ctx = await attach_shop_stock_to_payload(
                payload,
                detail,
                user_question=shop_question,
                province_id=query_province_id,
            )
        if shop_ctx:
            metric_data["shop_stock_scenario"] = True
            metric_data["shop_stock_matched"] = shop_ctx.get("matched_shops_count", 0)

        scenario_flags = await enrich_payload_for_scenarios(
            payload,
            detail,
            user_question=shop_question,
            province_id=query_province_id,
        )
        if scenario_flags:
            metric_data["scenario_enrich"] = scenario_flags

        llm_label = llm_provider_display_name()
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
        search_list = payload.get("search_results") or []
        scenarios = payload.get("question_scenarios") or {}
        if len(search_list) > 1 or scenarios.get("stock_browse") or scenarios.get("budget_browse"):
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
            session_key=session_key,
        )
        mirror_session_to_chat_level(_sessions, chat_id, user_id, session)
        thread_id_for_link = (msg.thread_id or msg.root_id or "").strip()
        card = build_lark_interactive_card(
            answer,
            product_url=response_link_url,
            question=user_question,
            product_name=product_name,
            thread_id=thread_id_for_link,
            source_chat_id=chat_id,
        )
        bot_mid = messenger.send_final_interactive(card)
        _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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
        bot_mid = messenger.send_final(
            "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu.\n"
            "Vui lòng thử lại sau ít phút.\n\n"
            f"Chi tiết: {str(exc)[:200]}"
        )
        _after_bot_reply(msg, bot_mid, chat_id=chat_id)
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
    if data.event and data.event.message:
        msg = data.event.message
        preview = strip_mentions(parse_text_content(msg.content or ""))[:80]
        logger.info(
            "Lark tin nhắn — chat=%s type=%s msg=%s thread=%s root=%s parent=%s @=%d text=%r",
            msg.chat_id,
            msg.chat_type,
            msg.message_id,
            msg.thread_id,
            msg.root_id,
            msg.parent_id,
            len(msg.mentions or []),
            preview,
        )
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
    provider = LLM_PROVIDER
    if provider == "deepseek":
        if not DEEPSEEK_API_KEY or any(p in DEEPSEEK_API_KEY for p in placeholders):
            raise ValueError("LLM_PROVIDER=deepseek — cần DEEPSEEK_API_KEY trong .env")
    elif provider == "byteplus":
        from byteplus_client import validate_byteplus_config

        validate_byteplus_config()
    elif not GEMINI_API_KEY or any(p in GEMINI_API_KEY for p in placeholders):
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
        "Thread auto-reply (hỏi tiếp trong topic không cần @): %s",
        "bật" if LARK_THREAD_AUTO_REPLY else "tắt",
    )
    logger.info(
        "⚠️ Lark Console cần quyền im:message.group_msg (hoặc group_msg:readonly) "
        "để bot NHẬN được tin trong topic không @. Chỉ có group_at_msg thì Lark "
        "không gửi event cho tin hỏi tiếp."
    )
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
