"""
Session persistence — SQLite backup cho conversation store (RAM).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from config import SESSION_DB_PATH, SESSION_PERSISTENCE

logger = logging.getLogger(__name__)


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


def load_session_store() -> dict[str, Any]:
    if not SESSION_PERSISTENCE:
        return {}
    store: dict[str, Any] = {}
    try:
        conn = _connect()
        rows = conn.execute("SELECT session_key, data FROM sessions").fetchall()
        conn.close()
        for key, raw in rows:
            try:
                store[key] = json.loads(raw)
            except json.JSONDecodeError:
                continue
        logger.info("Loaded %d sessions from SQLite", len(store))
    except Exception as exc:
        logger.warning("Không load được sessions.db: %s", exc)
    return store


def persist_session(session_key: str, session: dict[str, Any]) -> None:
    if not SESSION_PERSISTENCE:
        return
    try:
        import time

        conn = _connect()
        conn.execute(
            """
            INSERT INTO sessions (session_key, data, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (session_key, json.dumps(session, ensure_ascii=False), time.time()),
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
        import time

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
    """Load persisted active topics (scope_key = chat_id:canonical)."""
    if not SESSION_PERSISTENCE:
        return set()
    try:
        conn = _connect()
        _ensure_active_topics_table(conn)
        rows = conn.execute("SELECT scope_key FROM active_topics").fetchall()
        conn.close()
        return {row[0] for row in rows if row[0]}
    except Exception as exc:
        logger.warning("Không load active topics: %s", exc)
        return set()


def rebuild_active_topics_from_sessions(store: dict[str, Any]) -> set[str]:
    """Khôi phục topic active từ session có lịch sử hội thoại."""
    active: set[str] = set()
    marker = ":thread:topic:"
    for key, sess in store.items():
        if marker not in key or not (sess.get("turns")):
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
        import time

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
    """Load alias map — key = chat_id:alias, value = canonical."""
    if not SESSION_PERSISTENCE:
        return {}
    try:
        conn = _connect()
        _ensure_topic_aliases_table(conn)
        rows = conn.execute(
            "SELECT chat_id, alias, canonical FROM topic_aliases"
        ).fetchall()
        conn.close()
        return {f"{cid}:{alias}": canonical for cid, alias, canonical in rows if cid and alias}
    except Exception as exc:
        logger.warning("Không load topic aliases: %s", exc)
        return {}
