"""
Lưu ngữ cảnh hội thoại — RAM + SQLite persistence (session_store.py).
Mỗi session có TTL (mặc định 24h, SESSION_TTL_HOURS).
"""
from __future__ import annotations

import logging
import time
from typing import Any

from .session_store import delete_persisted_session, is_session_stale, persist_session

logger = logging.getLogger(__name__)

MAX_TURNS = 6
MAX_ASSISTANT_CHARS = 400
MAX_HISTORY_NOTES = 10
MAX_HISTORY_NOTES_CHARS = 600

_EMPTY_SESSION: dict[str, Any] = {
    "turns": [],
    "last_product": None,
    "last_keywords": "",
    "history_notes": [],
    "updated_at": 0.0,
}


def _fresh_session() -> dict[str, Any]:
    return {
        "turns": [],
        "last_product": None,
        "last_keywords": "",
        "history_notes": [],
        "updated_at": time.time(),
    }


def _reset_session(session: dict[str, Any]) -> None:
    session.clear()
    session.update(_fresh_session())


def touch_session(session: dict[str, Any]) -> None:
    session["updated_at"] = time.time()


def session_is_expired(session: dict[str, Any]) -> bool:
    """True nếu session quá SESSION_TTL — không còn ngữ cảnh SP."""
    if not session.get("turns") and not has_product_context(session):
        return False
    return is_session_stale(session.get("updated_at"))


def session_scope_key(
    chat_id: int | str,
    user_id: int | str | None,
    *,
    thread_key: str | None = None,
) -> str:
    """Khóa session — ưu tiên topic/thread để giữ ngữ cảnh trong chủ đề Lark."""
    if thread_key:
        return f"{chat_id}:thread:{thread_key}:{user_id or 0}"
    return f"{chat_id}:{user_id or 0}"


def _session_key(
    chat_id: int | str,
    user_id: int | str | None,
    thread_key: str | None = None,
) -> str:
    return session_scope_key(chat_id, user_id, thread_key=thread_key)


def has_product_context(session: dict[str, Any]) -> bool:
    product = session.get("last_product") or {}
    return bool(session.get("last_keywords") or product.get("name"))


def get_any_session_in_topic(
    store: dict[str, Any],
    chat_id: int | str,
    canonical: str,
) -> dict[str, Any]:
    """Session bất kỳ user nào trong cùng topic (bot đã trả lời)."""
    if not canonical:
        return {}
    prefix = f"{chat_id}:thread:topic:{canonical}:"
    best: dict[str, Any] | None = None
    best_turns = -1
    for key, sess in store.items():
        if not key.startswith(prefix):
            continue
        turns = len(sess.get("turns") or [])
        if turns > best_turns:
            best = sess
            best_turns = turns
    return best or {}


def has_thread_conversation(session: dict[str, Any]) -> bool:
    """True nếu bot đã từng trả lời trong thread/topic này."""
    return bool(session.get("turns"))


def resolve_session(
    store: dict[str, Any],
    chat_id: int | str,
    user_id: int | str | None,
    *,
    thread_key: str | None = None,
) -> dict[str, Any]:
    """
    Lấy session có ngữ cảnh SP — thử topic hiện tại, rồi các topic khác cùng user/chat.
    Lark có thể gửi thread_id / root_id không nhất quán giữa các tin.
    """
    primary = get_session(store, chat_id, user_id, thread_key=thread_key)
    if has_product_context(primary) and not session_is_expired(primary):
        return primary

    # Topic Lark mới (key khác) — vẫn lấy mirror chat-level nếu có.
    if not (primary.get("turns") or []):
        if thread_key:
            chat_level = get_session(store, chat_id, user_id, thread_key=None)
            if has_product_context(chat_level) and not session_is_expired(chat_level):
                return chat_level
        return primary

    suffix = f":{user_id or 0}"
    best: dict[str, Any] | None = None
    best_turns = -1
    chat_prefix = f"{chat_id}:"
    for key, sess in store.items():
        if not key.startswith(chat_prefix) or not key.endswith(suffix):
            continue
        if not has_product_context(sess) or session_is_expired(sess):
            continue
        turns = len(sess.get("turns") or [])
        if turns > best_turns:
            best = sess
            best_turns = turns
    if best is not None:
        return best

    if thread_key:
        chat_level = get_session(store, chat_id, user_id, thread_key=None)
        if has_product_context(chat_level) and not session_is_expired(chat_level):
            return chat_level

    return primary


def mirror_session_to_chat_level(
    store: dict[str, Any],
    chat_id: int | str,
    user_id: int | str | None,
    source: dict[str, Any],
) -> None:
    """Sao chép ngữ cảnh SP sang session chat-level — fallback khi topic key lệch."""
    if not has_product_context(source) or session_is_expired(source):
        return
    chat_sess = get_session(store, chat_id, user_id, thread_key=None)
    chat_sess["last_keywords"] = source.get("last_keywords") or ""
    product = source.get("last_product") or {}
    if product:
        chat_sess["last_product"] = dict(product)
    merged = (chat_sess.get("turns") or []) + (source.get("turns") or [])
    chat_sess["turns"] = merged[-MAX_TURNS:]
    merged_notes = (chat_sess.get("history_notes") or []) + (source.get("history_notes") or [])
    chat_sess["history_notes"] = merged_notes[-MAX_HISTORY_NOTES:]


def get_session(
    store: dict[str, Any],
    chat_id: int | str,
    user_id: int | str | None,
    *,
    thread_key: str | None = None,
) -> dict[str, Any]:
    key = _session_key(chat_id, user_id, thread_key)
    if key not in store:
        store[key] = _fresh_session()
        return store[key]
    session = store[key]
    if session_is_expired(session):
        logger.info("Session hết hạn TTL — reset %s", key)
        _reset_session(session)
        delete_persisted_session(key)
    return session


def clear_session(
    store: dict[str, Any],
    chat_id: int | str,
    user_id: int | str | None,
    *,
    thread_key: str | None = None,
) -> None:
    key = _session_key(chat_id, user_id, thread_key)
    store.pop(key, None)
    delete_persisted_session(key)


def _summarize_turn_for_history(
    turn: dict[str, Any],
    *,
    keywords: str = "",
    product_name: str = "",
) -> str:
    user = (turn.get("user") or "").strip()[:80]
    note = f"Khách từng hỏi: {user}"
    turn_kw = (turn.get("keywords") or keywords or "").strip()
    if turn_kw:
        note += f" (từ khóa: {turn_kw[:60]})"
    elif product_name:
        note += f" (SP: {product_name[:60]})"
    return note


def _append_history_notes(
    session: dict[str, Any],
    dropped_turns: list[dict[str, Any]],
    *,
    keywords: str = "",
    product_name: str = "",
) -> None:
    if not dropped_turns:
        return
    notes: list[str] = list(session.get("history_notes") or [])
    for turn in dropped_turns:
        notes.append(
            _summarize_turn_for_history(
                turn,
                keywords=keywords,
                product_name=product_name,
            )
        )
    notes = notes[-MAX_HISTORY_NOTES:]
    while notes and sum(len(n) for n in notes) > MAX_HISTORY_NOTES_CHARS:
        notes.pop(0)
    session["history_notes"] = notes


def append_turn(
    session: dict[str, Any],
    *,
    user: str,
    assistant: str = "",
    keywords: str = "",
    product_name: str = "",
    product_url: str = "",
    product_id: str | int = "",
    parent_product_id: str | int = "",
    session_key: str = "",
) -> None:
    session["turns"].append(
        {
            "user": user,
            "assistant": assistant[:MAX_ASSISTANT_CHARS],
            "keywords": keywords,
        }
    )
    if len(session["turns"]) > MAX_TURNS:
        dropped = session["turns"][:-MAX_TURNS]
        _append_history_notes(
            session,
            dropped,
            keywords=keywords,
            product_name=product_name,
        )
    session["turns"] = session["turns"][-MAX_TURNS:]
    touch_session(session)
    if keywords:
        session["last_keywords"] = keywords
    if product_name:
        last_product: dict[str, Any] = {
            "name": product_name,
            "url": product_url,
        }
        if product_id:
            last_product["product_id"] = product_id
        if parent_product_id:
            last_product["parent_id"] = parent_product_id
        session["last_product"] = last_product
    if session_key:
        persist_session(session_key, session)


def format_context_block(session: dict[str, Any]) -> str:
    """Chuỗi ngữ cảnh đưa vào prompt Gemini."""
    parts: list[str] = []
    product = session.get("last_product")
    if product and product.get("name"):
        parts.append(f"Sản phẩm đang thảo luận: {product['name']}")
    if session.get("last_keywords"):
        parts.append(f"Từ khóa tìm gần nhất: {session['last_keywords']}")

    history_notes = session.get("history_notes") or []
    if history_notes:
        parts.append("=== LỊCH SỬ TRƯỚC ĐÓ (tóm tắt) ===")
        parts.extend(history_notes)

    for turn in session.get("turns", [])[-4:]:
        parts.append(f"Khách: {turn['user']}")
        if turn.get("assistant"):
            parts.append(f"Bot: {turn['assistant']}")

    if not parts:
        return ""
    return "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n" + "\n".join(parts)
