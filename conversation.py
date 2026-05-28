"""
Lưu ngữ cảnh hội thoại ngắn hạn (trong RAM — mất khi restart bot).
"""
from __future__ import annotations

from typing import Any

MAX_TURNS = 6
MAX_ASSISTANT_CHARS = 400


def _session_key(chat_id: int | str, user_id: int | str | None) -> str:
    return f"{chat_id}:{user_id or 0}"


def get_session(
    store: dict[str, Any], chat_id: int | str, user_id: int | str | None
) -> dict[str, Any]:
    key = _session_key(chat_id, user_id)
    if key not in store:
        store[key] = {"turns": [], "last_product": None, "last_keywords": ""}
    return store[key]


def clear_session(
    store: dict[str, Any], chat_id: int | str, user_id: int | str | None
) -> None:
    store.pop(_session_key(chat_id, user_id), None)


def append_turn(
    session: dict[str, Any],
    *,
    user: str,
    assistant: str = "",
    keywords: str = "",
    product_name: str = "",
    product_url: str = "",
) -> None:
    session["turns"].append(
        {
            "user": user,
            "assistant": assistant[:MAX_ASSISTANT_CHARS],
            "keywords": keywords,
        }
    )
    session["turns"] = session["turns"][-MAX_TURNS:]
    if keywords:
        session["last_keywords"] = keywords
    if product_name:
        session["last_product"] = {
            "name": product_name,
            "url": product_url,
        }


def format_context_block(session: dict[str, Any]) -> str:
    """Chuỗi ngữ cảnh đưa vào prompt Gemini."""
    parts: list[str] = []
    product = session.get("last_product")
    if product and product.get("name"):
        parts.append(f"Sản phẩm đang thảo luận: {product['name']}")
    if session.get("last_keywords"):
        parts.append(f"Từ khóa tìm gần nhất: {session['last_keywords']}")

    for turn in session.get("turns", [])[-4:]:
        parts.append(f"Khách: {turn['user']}")
        if turn.get("assistant"):
            parts.append(f"Bot: {turn['assistant']}")

    if not parts:
        return ""
    return "=== NGỮ CẢNH HỘI THOẠI (gần đây) ===\n" + "\n".join(parts)
