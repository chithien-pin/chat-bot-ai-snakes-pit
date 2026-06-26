"""
Lưu feedback user + admin accept → few-shot training cho LLM.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import FEEDBACK_TRAINING_ENABLED, FEEDBACK_TRAINING_MAX_EXAMPLES, FEEDBACK_TRAINING_PATH

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"


@dataclass
class FeedbackTrainingEntry:
    id: str
    ts: str
    platform: str
    rating: str
    status: str = STATUS_PENDING
    user_question: str = ""
    bot_answer: str = ""
    search_keywords: str = ""
    product_id: str = ""
    product_name: str = ""
    product_url: str = ""
    user_comment: str = ""
    admin_note: str = ""
    chat_id: str = ""
    user_id: str = ""
    message_id: str = ""
    accepted_at: str = ""
    rejected_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _training_path() -> Path:
    path = Path(FEEDBACK_TRAINING_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_all() -> list[FeedbackTrainingEntry]:
    path = _training_path()
    if not path.is_file():
        return []
    entries: list[FeedbackTrainingEntry] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            entries.append(
                FeedbackTrainingEntry(
                    id=str(raw.get("id") or ""),
                    ts=str(raw.get("ts") or ""),
                    platform=str(raw.get("platform") or ""),
                    rating=str(raw.get("rating") or ""),
                    status=str(raw.get("status") or STATUS_PENDING),
                    user_question=str(raw.get("user_question") or ""),
                    bot_answer=str(raw.get("bot_answer") or ""),
                    search_keywords=str(raw.get("search_keywords") or ""),
                    product_id=str(raw.get("product_id") or ""),
                    product_name=str(raw.get("product_name") or ""),
                    product_url=str(raw.get("product_url") or ""),
                    user_comment=str(raw.get("user_comment") or ""),
                    admin_note=str(raw.get("admin_note") or ""),
                    chat_id=str(raw.get("chat_id") or ""),
                    user_id=str(raw.get("user_id") or ""),
                    message_id=str(raw.get("message_id") or ""),
                    accepted_at=str(raw.get("accepted_at") or ""),
                    rejected_at=str(raw.get("rejected_at") or ""),
                    meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
                )
            )
    return entries


def _write_all(entries: list[FeedbackTrainingEntry]) -> None:
    path = _training_path()
    with path.open("w", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def add_feedback_entry(
    *,
    platform: str,
    rating: str,
    chat_id: str = "",
    user_id: str = "",
    message_id: str = "",
    user_comment: str = "",
    user_question: str = "",
    bot_answer: str = "",
    search_keywords: str = "",
    product_id: str = "",
    product_name: str = "",
    product_url: str = "",
    meta: dict[str, Any] | None = None,
) -> FeedbackTrainingEntry | None:
    if not FEEDBACK_TRAINING_ENABLED:
        return None

    entry = FeedbackTrainingEntry(
        id=uuid.uuid4().hex[:12],
        ts=_utc_now_iso(),
        platform=platform,
        rating=rating,
        status=STATUS_PENDING,
        user_question=(user_question or "")[:2000],
        bot_answer=(bot_answer or "")[:4000],
        search_keywords=(search_keywords or "")[:500],
        product_id=str(product_id or ""),
        product_name=(product_name or "")[:200],
        product_url=(product_url or "")[:300],
        user_comment=(user_comment or "")[:1000],
        chat_id=str(chat_id or ""),
        user_id=str(user_id or ""),
        message_id=str(message_id or ""),
        meta=meta or {},
    )
    path = _training_path()
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
    logger.info("Feedback training queued id=%s rating=%s", entry.id, rating)
    return entry


def list_feedback_entries(
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[FeedbackTrainingEntry]:
    rows = _read_all()
    rows.sort(key=lambda r: r.ts, reverse=True)
    if status:
        rows = [r for r in rows if r.status == status]
    return rows[:limit]


def get_feedback_entry(entry_id: str) -> FeedbackTrainingEntry | None:
    for row in _read_all():
        if row.id == entry_id:
            return row
    return None


def accept_feedback_entry(
    entry_id: str,
    *,
    admin_note: str = "",
) -> FeedbackTrainingEntry | None:
    entries = _read_all()
    updated: FeedbackTrainingEntry | None = None
    for i, row in enumerate(entries):
        if row.id != entry_id:
            continue
        row.status = STATUS_ACCEPTED
        row.admin_note = (admin_note or row.admin_note or "")[:2000]
        row.accepted_at = _utc_now_iso()
        entries[i] = row
        updated = row
        break
    if not updated:
        return None
    _write_all(entries)
    logger.info("Feedback accepted id=%s", entry_id)
    return updated


def reject_feedback_entry(entry_id: str, *, admin_note: str = "") -> FeedbackTrainingEntry | None:
    entries = _read_all()
    updated: FeedbackTrainingEntry | None = None
    for i, row in enumerate(entries):
        if row.id != entry_id:
            continue
        row.status = STATUS_REJECTED
        row.admin_note = (admin_note or row.admin_note or "")[:2000]
        row.rejected_at = _utc_now_iso()
        entries[i] = row
        updated = row
        break
    if not updated:
        return None
    _write_all(entries)
    logger.info("Feedback rejected id=%s", entry_id)
    return updated


def training_stats() -> dict[str, int]:
    rows = _read_all()
    return {
        "total": len(rows),
        "pending": sum(1 for r in rows if r.status == STATUS_PENDING),
        "accepted": sum(1 for r in rows if r.status == STATUS_ACCEPTED),
        "rejected": sum(1 for r in rows if r.status == STATUS_REJECTED),
        "helpful": sum(1 for r in rows if r.rating == "helpful"),
        "not_helpful": sum(1 for r in rows if r.rating == "not_helpful"),
    }


def load_accepted_examples(*, limit: int = 6) -> list[FeedbackTrainingEntry]:
    rows = [r for r in _read_all() if r.status == STATUS_ACCEPTED]
    rows.sort(key=lambda r: r.accepted_at or r.ts, reverse=True)
    return rows[:limit]


def build_training_prompt_addon(*, limit: int | None = None) -> str:
    """Few-shot / correction block gắn vào system prompt LLM."""
    if not FEEDBACK_TRAINING_ENABLED:
        return ""

    max_examples = limit if limit is not None else FEEDBACK_TRAINING_MAX_EXAMPLES
    examples = load_accepted_examples(limit=max_examples)
    if not examples:
        return ""

    lines = [
        "\n=== HƯỚNG DẪN TỪ FEEDBACK ADMIN ĐÃ DUYỆT ===",
        "Ưu tiên phong cách và nội dung các ví dụ dưới đây khi câu hỏi tương tự.",
    ]
    for ex in examples:
        if ex.rating == "helpful" and ex.user_question and ex.bot_answer:
            lines.append(
                f"\n[Ví dụ tốt]\nKhách: {ex.user_question.strip()}\n"
                f"Trả lời mẫu: {ex.bot_answer.strip()[:1200]}"
            )
            if ex.admin_note:
                lines.append(f"Ghi chú admin: {ex.admin_note.strip()}")
        elif ex.rating == "not_helpful" and ex.user_question:
            lines.append(f"\n[Tránh — user đánh giá không hữu ích]")
            lines.append(f"Khách: {ex.user_question.strip()}")
            if ex.bot_answer:
                lines.append(f"Trả lời cần tránh: {ex.bot_answer.strip()[:800]}")
            if ex.admin_note:
                lines.append(f"Nên trả lời theo hướng: {ex.admin_note.strip()}")

    lines.append("\n=== HẾT FEEDBACK ADMIN ===")
    return "\n".join(lines)
