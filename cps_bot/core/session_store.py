"""
Session persistence — SQLite backup cho conversation store (RAM).
TTL mặc định 24h/session (SESSION_TTL_HOURS).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

from config import SESSION_DB_PATH, SESSION_PERSISTENCE, SESSION_TTL_SECONDS

logger = logging.getLogger(__name__)


def session_expiry_cutoff(now: float | None = None) -> float:
    """Unix timestamp — session cũ hơn mốc này được coi là hết hạn."""
    return (now if now is not None else time.time()) - SESSION_TTL_SECONDS


def is_session_stale(updated_at: float | None, *, now: float | None = None) -> bool:
    if updated_at is None:
        return False
    try:
        return float(updated_at) < session_expiry_cutoff(now)
    except (TypeError, ValueError):
        return False


def _connect() -> sqlite3.Connection:
    path = Path(SESSION_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_key TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def purge_expired_persisted_state(*, now: float | None = None) -> dict[str, int]:
    """Xóa session/topic/alias quá SESSION_TTL — gọi khi load hoặc định kỳ."""
    if not SESSION_PERSISTENCE:
        return {"sessions": 0, "active_topics": 0, "topic_aliases": 0}
    cutoff = session_expiry_cutoff(now)
    counts = {"sessions": 0, "active_topics": 0, "topic_aliases": 0}
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        _ensure_topic_aliases_table(conn)
        for table in counts:
            row = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE updated_at < ?",
                (cutoff,),
            ).fetchone()
            counts[table] = int(row[0]) if row else 0
            conn.execute(f"DELETE FROM {table} WHERE updated_at < ?", (cutoff,))
        conn.commit()
        conn.close()
        if any(counts.values()):
            logger.info(
                "Đã purge session hết hạn (TTL=%ss): %s",
                SESSION_TTL_SECONDS,
                counts,
            )
    except Exception as exc:
        logger.warning("Không purge session hết hạn: %s", exc)
    return counts


def load_session_store() -> dict[str, Any]:
    if not SESSION_PERSISTENCE:
        return {}
    purge_expired_persisted_state()
    store: dict[str, Any] = {}
    cutoff = session_expiry_cutoff()
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT session_key, data, updated_at FROM sessions WHERE updated_at >= ?",
            (cutoff,),
        ).fetchall()
        conn.close()
        for key, raw, updated_at in rows:
            try:
                sess = json.loads(raw)
                if isinstance(sess, dict):
                    sess["updated_at"] = float(updated_at)
                store[key] = sess
            except json.JSONDecodeError:
                continue
        logger.info("Loaded %d sessions from SQLite (TTL=%ss)", len(store), SESSION_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Không load được sessions.db: %s", exc)
    return store


def persist_session(session_key: str, session: dict[str, Any]) -> None:
    if not SESSION_PERSISTENCE:
        return
    try:
        now = time.time()
        payload = dict(session)
        payload["updated_at"] = now
        conn = _connect()
        conn.execute(
            """
            INSERT INTO sessions (session_key, data, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (session_key, json.dumps(payload, ensure_ascii=False), now),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Không persist session %s: %s", session_key, exc)


def delete_persisted_session(session_key: str) -> None:
    if not SESSION_PERSISTENCE:
        return
    try:
        conn = _connect()
        conn.execute("DELETE FROM sessions WHERE session_key = ?", (session_key,))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Không xóa session %s: %s", session_key, exc)


def delete_persisted_sessions_for_chat(chat_id: str) -> int:
    """Xóa mọi session SQLite thuộc một Lark chat_id."""
    if not SESSION_PERSISTENCE or not chat_id:
        return 0
    prefix = f"{chat_id}:"
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE session_key LIKE ?",
            (f"{prefix}%",),
        ).fetchone()
        count = int(row[0]) if row else 0
        conn.execute(
            "DELETE FROM sessions WHERE session_key LIKE ?",
            (f"{prefix}%",),
        )
        conn.commit()
        conn.close()
        return count
    except Exception as exc:
        logger.warning("Không xóa sessions chat %s: %s", chat_id, exc)
        return 0


def delete_active_topics_for_chat(chat_id: str) -> int:
    if not SESSION_PERSISTENCE or not chat_id:
        return 0
    prefix = f"{chat_id}:"
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        row = conn.execute(
            "SELECT COUNT(*) FROM active_topics WHERE scope_key LIKE ?",
            (f"{prefix}%",),
        ).fetchone()
        count = int(row[0]) if row else 0
        conn.execute(
            "DELETE FROM active_topics WHERE scope_key LIKE ?",
            (f"{prefix}%",),
        )
        conn.commit()
        conn.close()
        return count
    except Exception as exc:
        logger.warning("Không xóa active topics chat %s: %s", chat_id, exc)
        return 0


def delete_topic_aliases_for_chat(chat_id: str) -> int:
    if not SESSION_PERSISTENCE or not chat_id:
        return 0
    try:
        conn = _connect()
        _ensure_topic_aliases_table(conn)
        row = conn.execute(
            "SELECT COUNT(*) FROM topic_aliases WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        count = int(row[0]) if row else 0
        conn.execute("DELETE FROM topic_aliases WHERE chat_id = ?", (chat_id,))
        conn.commit()
        conn.close()
        return count
    except Exception as exc:
        logger.warning("Không xóa topic aliases chat %s: %s", chat_id, exc)
        return 0


def _ensure_active_topics_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS active_topics (
            scope_key TEXT PRIMARY KEY,
            updated_at REAL NOT NULL
        )
        """
    )


def persist_active_topic(scope_key: str) -> None:
    """Lưu topic đang active (chat_id:canonical) — survive bot restart."""
    if not SESSION_PERSISTENCE or not scope_key:
        return
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        conn.execute(
            """
            INSERT INTO active_topics (scope_key, updated_at)
            VALUES (?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (scope_key, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Không persist active topic %s: %s", scope_key, exc)


def delete_active_topic(scope_key: str) -> None:
    if not SESSION_PERSISTENCE or not scope_key:
        return
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        conn.execute("DELETE FROM active_topics WHERE scope_key = ?", (scope_key,))
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Không xóa active topic %s: %s", scope_key, exc)


def load_active_topics() -> set[str]:
    """Load persisted active topics (scope_key = chat_id:canonical) trong TTL."""
    if not SESSION_PERSISTENCE:
        return set()
    cutoff = session_expiry_cutoff()
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        rows = conn.execute(
            "SELECT scope_key FROM active_topics WHERE updated_at >= ?",
            (cutoff,),
        ).fetchall()
        conn.close()
        return {row[0] for row in rows if row[0]}
    except Exception as exc:
        logger.warning("Không load active topics: %s", exc)
        return set()


def rebuild_active_topics_from_sessions(store: dict[str, Any]) -> set[str]:
    """Khôi phục topic active từ session có lịch sử hội thoại (chưa hết hạn)."""
    active: set[str] = set()
    marker = ":thread:topic:"
    for key, sess in store.items():
        if marker not in key or not (sess.get("turns")):
            continue
        if is_session_stale(sess.get("updated_at")):
            continue
        chat_id, rest = key.split(marker, 1)
        canonical = rest.rsplit(":", 1)[0]
        if chat_id and canonical:
            active.add(f"{chat_id}:{canonical}")
    return active


def _ensure_topic_aliases_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS topic_aliases (
            chat_id TEXT NOT NULL,
            alias TEXT NOT NULL,
            canonical TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (chat_id, alias)
        )
        """
    )


def persist_topic_alias(chat_id: str, alias: str, canonical: str) -> None:
    """Lưu alias → canonical để follow-up khớp sau restart."""
    if not SESSION_PERSISTENCE or not chat_id or not alias or not canonical:
        return
    try:
        conn = _connect()
        _ensure_topic_aliases_table(conn)
        conn.execute(
            """
            INSERT INTO topic_aliases (chat_id, alias, canonical, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id, alias) DO UPDATE SET
                canonical = excluded.canonical,
                updated_at = excluded.updated_at
            """,
            (chat_id, alias, canonical, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Không persist topic alias %s/%s: %s", chat_id, alias, exc)


def load_topic_aliases() -> dict[str, str]:
    """Load alias map — key = chat_id:alias, value = canonical (trong TTL)."""
    if not SESSION_PERSISTENCE:
        return {}
    cutoff = session_expiry_cutoff()
    try:
        conn = _connect()
        _ensure_topic_aliases_table(conn)
        rows = conn.execute(
            "SELECT chat_id, alias, canonical FROM topic_aliases WHERE updated_at >= ?",
            (cutoff,),
        ).fetchall()
        conn.close()
        return {f"{cid}:{alias}": canonical for cid, alias, canonical in rows if cid and alias}
    except Exception as exc:
        logger.warning("Không load topic aliases: %s", exc)
        return {}


def clear_all_bot_state() -> dict[str, int]:
    """
    Xóa toàn bộ context/lịch sử chat đã persist (sessions, topic active, alias).
    Bot cần restart để xóa RAM (_sessions trong lark/telegram).
    """
    counts: dict[str, int] = {"sessions": 0, "active_topics": 0, "topic_aliases": 0}
    path = Path(SESSION_DB_PATH)
    if not path.is_file():
        logger.info("Không có sessions DB tại %s — bỏ qua", path)
        return counts
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        _ensure_topic_aliases_table(conn)
        for table in counts:
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            counts[table] = int(row[0]) if row else 0
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
        conn.close()
        logger.info("Đã xóa bot state: %s", counts)
    except Exception as exc:
        logger.warning("Không clear bot state: %s", exc)
    return counts
