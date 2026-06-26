"""Đọc sessions.db cho dashboard."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SESSION_DB_PATH


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_session_summary(*, limit: int = 30) -> dict[str, Any]:
    path = Path(SESSION_DB_PATH)
    if not path.is_file():
        return {"total": 0, "sessions": [], "active_topics": 0}

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        total = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        topic_count = 0
        try:
            topic_count = conn.execute("SELECT COUNT(*) FROM active_topics").fetchone()[0]
        except sqlite3.Error:
            topic_count = 0

        rows = conn.execute(
            """
            SELECT session_key, data, updated_at
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        sessions: list[dict[str, Any]] = []
        for row in rows:
            data = _safe_json(row["data"])
            turns = data.get("turns") or []
            last_turn = turns[-1] if turns else {}
            sessions.append(
                {
                    "session_key": row["session_key"],
                    "updated_at": row["updated_at"],
                    "turn_count": len(turns),
                    "last_user": (last_turn.get("user") or "")[:120],
                    "last_keywords": data.get("last_keywords") or "",
                    "last_product": (data.get("last_product") or {}).get("name") or "",
                    "pending_province_for": data.get("pending_province_for") or "",
                }
            )

        return {
            "total": total,
            "active_topics": topic_count,
            "sessions": sessions,
        }
    finally:
        conn.close()
