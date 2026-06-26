"""
Tên hiển thị user (Lark open_id, Telegram id) — cache + lookup API.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def user_names_cache_path() -> Path:
    from config import USER_NAMES_CACHE_PATH

    return Path(USER_NAMES_CACHE_PATH)


def load_user_name_cache() -> dict[str, dict[str, str]]:
    path = user_names_cache_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.warning("Không đọc được user names cache: %s", exc)
        return {}


def save_user_name_cache(cache: dict[str, Any]) -> None:
    path = user_names_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def cache_key(platform: str, user_id: str) -> str:
    return f"{platform}:{user_id}"


def remember_user_name(platform: str, user_id: str, user_name: str) -> None:
    user_name = (user_name or "").strip()
    user_id = (user_id or "").strip()
    if not user_id or not user_name:
        return
    cache = load_user_name_cache()
    cache[cache_key(platform, user_id)] = {
        "user_name": user_name,
        "platform": platform,
        "user_id": user_id,
    }
    save_user_name_cache(cache)


def resolve_lark_user_name(client: Any, open_id: str) -> str:
    """Lấy tên Lark qua Contact API — có cache."""
    open_id = (open_id or "").strip()
    if not open_id:
        return ""

    cached = load_user_name_cache().get(cache_key("lark", open_id), {})
    if cached.get("user_name"):
        return str(cached["user_name"])

    try:
        from lark_oapi.api.contact.v3 import GetUserRequest

        request = (
            GetUserRequest.builder()
            .user_id(open_id)
            .user_id_type("open_id")
            .build()
        )
        response = client.contact.v3.user.get(request)
        if not response.success() or not response.data or not response.data.user:
            logger.debug(
                "Lark user.get thất bại open_id=%s code=%s",
                open_id,
                getattr(response, "code", ""),
            )
            return ""

        user = response.data.user
        name = (user.name or user.nickname or user.en_name or "").strip()
        if name:
            remember_user_name("lark", open_id, name)
        return name
    except Exception as exc:
        logger.debug("Lark user name lookup %s: %s", open_id, exc)
        return ""


def telegram_user_display_name(user: Any) -> str:
    if not user:
        return ""
    parts = [getattr(user, "first_name", None) or "", getattr(user, "last_name", None) or ""]
    name = " ".join(p for p in parts if p).strip()
    username = getattr(user, "username", None) or ""
    if not name and username:
        return f"@{username}"
    if name and username:
        return f"{name} (@{username})"
    return name


def build_user_display_map(
    rows: list[dict[str, Any]],
    *,
    cache: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """user_id → tên hiển thị (cache + metrics mới nhất)."""
    names: dict[str, str] = {}
    cache = cache if cache is not None else load_user_name_cache()
    for entry in cache.values():
        if not isinstance(entry, dict):
            continue
        uid = str(entry.get("user_id") or "").strip()
        uname = str(entry.get("user_name") or "").strip()
        if uid and uname:
            names[uid] = uname

    chat = [r for r in rows if r.get("event") == "chat_message"]
    for row in sorted(chat, key=lambda r: str(r.get("ts") or "")):
        uid = str(row.get("user_id") or "").strip()
        uname = str(row.get("user_name") or "").strip()
        if uid and uname:
            names[uid] = uname
    return names


def attach_user_names(
    payload: dict[str, Any],
    name_map: dict[str, str],
) -> None:
    """Gắn user_name vào messages, groups, filters.users."""
    for msg in payload.get("messages") or []:
        uid = str(msg.get("user_id") or "").strip()
        msg["user_name"] = name_map.get(uid) or msg.get("user_name") or ""

    for group in payload.get("groups") or []:
        uid = str(group.get("user_id") or "").strip()
        group["user_name"] = name_map.get(uid) or group.get("user_name") or ""

    filters = payload.get("filters") or {}
    for user in filters.get("users") or []:
        uid = str(user.get("user_id") or "").strip()
        user["user_name"] = name_map.get(uid) or user.get("user_name") or ""


def ensure_lark_user_names(user_ids: set[str] | list[str], *, limit: int = 15) -> None:
    """Backfill tên Lark cho dashboard — user chưa có trong cache."""
    from config import LARK_API_DOMAIN, LARK_APP_ID, LARK_APP_SECRET

    if not LARK_APP_ID or not LARK_APP_SECRET:
        return

    cache = load_user_name_cache()
    missing: list[str] = []
    for uid in user_ids:
        uid = str(uid or "").strip()
        if not uid.startswith("ou_"):
            continue
        if cache.get(cache_key("lark", uid), {}).get("user_name"):
            continue
        missing.append(uid)
    if not missing:
        return

    try:
        import lark_oapi as lark
        from lark_oapi.core.enum import LogLevel

        domain = (
            lark.FEISHU_DOMAIN
            if LARK_API_DOMAIN == "feishu"
            else lark.LARK_DOMAIN
        )
        client = (
            lark.Client.builder()
            .app_id(LARK_APP_ID)
            .app_secret(LARK_APP_SECRET)
            .domain(domain)
            .log_level(LogLevel.ERROR)
            .build()
        )
        for uid in missing[:limit]:
            resolve_lark_user_name(client, uid)
    except Exception as exc:
        logger.debug("ensure_lark_user_names: %s", exc)
