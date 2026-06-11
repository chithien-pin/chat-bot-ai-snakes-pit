"""
Utilities ghi metrics dạng JSON lines.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_metrics_logger = logging.getLogger("bot_metrics")
if not _metrics_logger.handlers:
    _metrics_logger.setLevel(logging.INFO)
    _metrics_logger.propagate = False
    log_path = Path(__file__).resolve().parent / "metrics.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _metrics_logger.addHandler(handler)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_metric(event: str, **fields: Any) -> None:
    """
    Ghi 1 dòng JSON metrics vào metrics.log.
    """
    payload = {
        "ts": _utc_now_iso(),
        "event": event,
        **fields,
    }
    _metrics_logger.info(json.dumps(payload, ensure_ascii=False))
