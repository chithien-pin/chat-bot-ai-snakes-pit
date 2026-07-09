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
    DeleteMessageRequest,
    PatchMessageRequest,
    PatchMessageRequestBody,
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
from cps_bot.core.chat_help import chat_help_plain
from cps_bot.core.chat_pipeline import process_chat_message
from cps_bot.feedback.feedback import (
    FEEDBACK_HELPFUL,
    build_lark_card_action_response,
    build_lark_feedback_form_card,
    build_lark_feedback_thanks_card,
    build_lark_interactive_card,
    build_lark_status_card,
    lark_interactive_content,
    parse_lark_feedback_payload,
    record_message_feedback,
)
from cps_bot.feedback.lark_bitable import bitable_is_configured, save_feedback_to_bitable
from cps_bot.feedback.lark_feedback_notify import build_lark_topic_link, send_feedback_admin_notification
from cps_bot.lark.compare_card import build_lark_compare_card
from cps_bot.browse.compare_reply import build_compare_summary
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from cps_bot.lark.lark_ws_patch import apply_lark_ws_card_patch
from cps_bot.core.conversation import (
    clear_all_sessions_for_chat,
    format_context_block,
    get_any_session_in_topic,
    has_product_context,
    has_thread_conversation,
    resolve_session,
)
from cps_bot.llm.gemini_client import (
    is_affirmative_follow_up,
    is_contextual_follow_up,
    _mentions_new_product,
)
from cps_bot.core.user_display import resolve_lark_user_name
from cps_bot.core.session_store import (
    delete_active_topic,
    delete_active_topics_for_chat,
    delete_persisted_sessions_for_chat,
    delete_topic_aliases_for_chat,
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


def clear_lark_chat_runtime(chat_id: str) -> dict[str, int]:
    """
    Xóa toàn bộ ngữ cảnh Lark cho một chat — RAM (_sessions, topics, aliases) + SQLite.
    """
    cid = (chat_id or "").strip()
    if not cid:
        return {"sessions": 0, "active_topics": 0, "topic_aliases": 0}

    ram_sessions = clear_all_sessions_for_chat(_sessions, cid)

    topic_scopes = [s for s in list(_active_topics) if s.startswith(f"{cid}:")]
    for scope in topic_scopes:
        _active_topics.discard(scope)
        delete_active_topic(scope)

    alias_keys = [k for k in list(_topic_alias_map.keys()) if k.startswith(f"{cid}:")]
    for key in alias_keys:
        _topic_alias_map.pop(key, None)

    db_topics = delete_active_topics_for_chat(cid)
    db_aliases = delete_topic_aliases_for_chat(cid)
    db_sessions = delete_persisted_sessions_for_chat(cid)

    counts = {
        "sessions": max(ram_sessions, db_sessions),
        "active_topics": max(len(topic_scopes), db_topics),
        "topic_aliases": max(len(alias_keys), db_aliases),
    }
    logger.info("Đã xóa Lark runtime chat %s: %s", cid, counts)
    return counts


def reset_lark_memory(*, reload_from_db: bool = False) -> dict[str, int]:
    """
    Reset toàn bộ state RAM Lark — dùng khi cần xóa hết context in-memory.
    Mặc định không reload từ SQLite (RAM trống cho tới khi restart hoặc hỏi mới).
    """
    global _sessions, _active_topics, _topic_alias_map

    counts = {
        "sessions": len(_sessions),
        "active_topics": len(_active_topics),
        "topic_aliases": len(_topic_alias_map),
    }
    _sessions.clear()
    _active_topics.clear()
    _topic_alias_map.clear()

    if reload_from_db:
        _sessions.update(load_session_store())
        _active_topics.update(load_active_topics())
        _active_topics.update(rebuild_active_topics_from_sessions(_sessions))
        _topic_alias_map.update(load_topic_aliases())

    logger.info("Reset Lark memory (reload=%s): cleared %s", reload_from_db, counts)
    return counts


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
        if ctx and (
            is_contextual_follow_up(user_text, ctx)
            or is_affirmative_follow_up(user_text)
        ):
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
        card = build_lark_status_card(text)
        payload = lark_interactive_content(card)
        if not self.status_message_id:
            self.status_message_id = self.reply_interactive(card)
            return
        if not self._update(self.status_message_id, payload, msg_type="interactive"):
            logger.warning("Không cập nhật được trạng thái — giữ tin cũ")

    def send_final(self, text: str) -> str:
        if self.status_message_id:
            payload = lark_interactive_content(build_lark_status_card(text))
            if self._patch_interactive(self.status_message_id, payload):
                return self.status_message_id
            logger.warning(
                "Lark PATCH text card thất bại — gửi reply mới (giữ tin trạng thái)"
            )
            self.status_message_id = None
        return self.reply(text)

    def send_final_interactive(self, card: dict[str, Any]) -> str:
        payload = lark_interactive_content(card)
        if self.status_message_id:
            if self._patch_interactive(self.status_message_id, payload):
                return self.status_message_id
            logger.warning(
                "Lark PATCH card thất bại — gửi reply mới (giữ tin trạng thái)"
            )
            self.status_message_id = None
        return self.reply_interactive(card)

    def _patch_interactive(self, message_id: str, content: str) -> bool:
        """PATCH interactive card — PUT (message.update) không hỗ trợ card."""
        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                PatchMessageRequestBody.builder()
                .content(content)
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.patch(request)
        if not response.success():
            logger.warning(
                "Lark PATCH lỗi: code=%s msg=%s message_id=%s",
                response.code,
                response.msg,
                message_id,
            )
            return False
        return True

    def _update(
        self,
        message_id: str,
        content: str,
        *,
        msg_type: str = "text",
    ) -> bool:
        if msg_type == "interactive":
            return self._patch_interactive(message_id, content)
        body_content = text_content(content)
        request = (
            UpdateMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                UpdateMessageRequestBody.builder()
                .msg_type("text")
                .content(body_content)
                .build()
            )
            .build()
        )
        response = self.client.im.v1.message.update(request)
        if not response.success():
            logger.warning(
                "Lark update lỗi: code=%s msg=%s message_id=%s",
                response.code,
                response.msg,
                message_id,
            )
            return False
        return True

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

    def _delete(self, message_id: str) -> bool:
        request = (
            DeleteMessageRequest.builder()
            .message_id(message_id)
            .build()
        )
        response = self.client.im.v1.message.delete(request)
        if not response.success():
            logger.warning(
                "Lark delete lỗi: code=%s msg=%s message_id=%s",
                response.code,
                response.msg,
                message_id,
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
    messenger.reply(chat_help_plain(lark=True))


async def _cmd_clear(
    messenger: LarkMessenger,
    chat_id: str,
    user_id: str | None,
    *,
    thread_key: str | None = None,
) -> None:
    if not is_allowed_chat(chat_id):
        return
    _ = thread_key
    counts = clear_lark_chat_runtime(chat_id)
    messenger.reply(
        "🧹 Đã xóa ngữ cảnh hội thoại (RAM + lưu trữ).\n"
        f"• Session: {counts['sessions']}\n"
        f"• Topic active: {counts['active_topics']}\n"
        f"• Topic alias: {counts['topic_aliases']}\n"
        "Bạn có thể hỏi sản phẩm mới từ đầu."
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

    user_name = ""
    if user_id and _lark_client is not None:
        user_name = resolve_lark_user_name(_lark_client, str(user_id))

    async def on_status(text: str) -> None:
        messenger.update_status(text)

    result = await process_chat_message(
        user_question,
        platform="lark",
        chat_id=chat_id,
        user_id=str(user_id or "0"),
        user_name=user_name,
        thread_key=thread_key or None,
        session_store=_sessions,
        message_id=message_id or None,
        max_reply_length=MAX_MESSAGE_LENGTH,
        mirror_to_chat_level=True,
        cache_feedback=False,
        on_status=on_status,
        error_detail_in_reply=True,
        extra_metrics={
            "thread_key": thread_key,
            "process_reason": process_reason,
        },
    )

    if result.status == "success":
        thread_id_for_link = (msg.thread_id or msg.root_id or "").strip()
        if result.use_compare_column_layout and len(result.compare_products) >= 2:
            summary = result.reply
            if result.metrics.get("fast_compare_reply"):
                summary = build_compare_summary(
                    result.compare_products[:2],
                    fast=True,
                )
            card = build_lark_compare_card(
                result.compare_products[:2],
                summary=summary,
                question=user_question,
                product_name=result.product_name,
                product_url=result.response_link_url,
                thread_id=thread_id_for_link,
                source_chat_id=chat_id,
            )
        else:
            card = build_lark_interactive_card(
                result.reply,
                product_url=result.response_link_url,
                question=user_question,
                product_name=result.product_name,
                thread_id=thread_id_for_link,
                source_chat_id=chat_id,
            )
        bot_mid = messenger.send_final_interactive(card)
        if not bot_mid and result.use_compare_column_layout:
            logger.warning(
                "Compare column card gửi thất bại — fallback card 1 cột"
            )
            fallback_card = build_lark_interactive_card(
                result.reply,
                product_url=result.response_link_url,
                question=user_question,
                product_name=result.product_name,
                thread_id=thread_id_for_link,
                source_chat_id=chat_id,
            )
            bot_mid = messenger.send_final_interactive(fallback_card)
        if not bot_mid:
            logger.warning("Interactive card gửi thất bại — fallback text")
            bot_mid = messenger.send_final(result.reply)
    else:
        bot_mid = messenger.send_final(result.reply)
    _after_bot_reply(msg, bot_mid, chat_id=chat_id)


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
    answer_body: str = "",
) -> None:
    """Ghi metrics + training queue + Lark Base + noti admin — không chặn card.action.trigger."""
    record_message_feedback(
        platform="lark",
        rating=rating,
        chat_id=chat_id,
        user_id=reviewer_open_id,
        message_id=message_id,
        user_comment=user_comment,
        user_question=question,
        bot_answer=answer_body,
        product_name=product_name,
        product_url=product_url,
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
            "answer_body": payload.get("answer_body", ""),
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
        from cps_bot.llm.byteplus_client import validate_byteplus_config

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
