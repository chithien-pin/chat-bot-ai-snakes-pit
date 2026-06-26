"""Trạng thái file dữ liệu sync (menu map, category attributes)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import CATEGORY_ATTRIBUTES_MAP_PATH, MENU_CATEGORY_MAP_PATH


def _file_meta(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"exists": False, "path": str(path)}

    stat = path.stat()
    meta: dict[str, Any] = {
        "exists": True,
        "path": str(path),
        "size_bytes": stat.st_size,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
        "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            meta["updated_at"] = data.get("updated_at")
            meta["category_count"] = data.get("category_count")
            meta["link_count"] = data.get("link_count")
            meta["progress_index"] = data.get("progress_index")
            meta["processed_ids"] = len(data.get("processed_ids") or [])
            if "entries" in data:
                meta["menu_entries"] = len(data.get("entries") or {})
    except (json.JSONDecodeError, OSError):
        meta["parse_error"] = True

    return meta


def build_data_health() -> dict[str, Any]:
    return {
        "menu_category_map": _file_meta(Path(MENU_CATEGORY_MAP_PATH)),
        "category_attributes_map": _file_meta(Path(CATEGORY_ATTRIBUTES_MAP_PATH)),
    }
