"""
Main menu CellphoneS — fetch menu GraphQL + map tên menu → category_id qua url_info.
Tham chiếu cps-nuxt-standard/store/menu.js (menu id=5).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx

from config import (
    CPS_GRAPHQL_DASHBOARD_ENDPOINT,
    CPS_MAIN_MENU_ID,
    MENU_CATEGORY_FETCH_DELAY_SEC,
    MENU_CATEGORY_MAP_PATH,
)
from cps_api import extract_request_path, url_info

logger = logging.getLogger(__name__)

MAIN_MENU_GRAPHQL_QUERY_TEMPLATE = """
query MENU_ID {{
  menu(id: {menu_id}) {{
    id
    name
    menu_items {{
      id
      name
      parent_id
      target
      enabled
      data
      order
      type
      children {{
        id
        name
        parent_id
        target
        enabled
        data
        order
        type
        children {{
          id
          name
          parent_id
          target
          enabled
          data
          order
          type
        }}
      }}
    }}
  }}
}}
"""


def _parse_menu_data(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _cellphones_path(url: str) -> str:
    """Chỉ giữ path CellphoneS — bỏ domain / query."""
    value = (url or "").strip()
    if not value or value.startswith("#"):
        return ""
    if "cellphones.com.vn" in value:
        return extract_request_path(value)
    if value.startswith("/"):
        return extract_request_path(value)
    if value.endswith(".html") and "://" not in value:
        return extract_request_path(value)
    return ""


def _links_from_item(item: dict[str, Any]) -> list[tuple[str, str]]:
    """Trích (tên menu, request_path) từ một menu item."""
    if item.get("enabled") is False:
        return []

    name = (item.get("name") or "").strip()
    data = _parse_menu_data(item.get("data"))
    links: list[tuple[str, str]] = []

    single = _cellphones_path(str(data.get("url") or ""))
    if single and name:
        links.append((name, single))

    multiple_raw = data.get("multiple_link")
    if multiple_raw:
        multiple = _parse_menu_data(multiple_raw)
        for sub_name, sub_url in multiple.items():
            path = _cellphones_path(str(sub_url or ""))
            label = (str(sub_name) or "").strip() or name
            if path and label:
                links.append((label, path))

    target_path = _cellphones_path(str(item.get("target") or ""))
    if target_path and name and not any(p == target_path for _, p in links):
        links.append((name, target_path))

    return links


def collect_menu_links(menu_items: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Duyệt cây menu — trả danh sách (menu_name, request_path) không trùng path."""
    seen_paths: set[str] = set()
    out: list[tuple[str, str]] = []

    def walk(items: list[dict[str, Any]]) -> None:
        for item in items:
            if not isinstance(item, dict):
                continue
            for label, path in _links_from_item(item):
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                out.append((label, path))
            children = item.get("children") or []
            if isinstance(children, list) and children:
                walk(children)

    walk(menu_items)
    return out


async def fetch_main_menu_items(menu_id: int | None = None) -> list[dict[str, Any]]:
    """Lấy menu_items từ GraphQL dashboard (giống getMenuDataGraphql id=5)."""
    mid = menu_id if menu_id is not None else CPS_MAIN_MENU_ID
    query = MAIN_MENU_GRAPHQL_QUERY_TEMPLATE.format(menu_id=mid)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CPS_GRAPHQL_DASHBOARD_ENDPOINT,
            json={"query": query, "variables": {}},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        payload = response.json()

    errors = payload.get("errors") or []
    if errors:
        raise RuntimeError(f"Menu GraphQL errors: {errors[:1]}")

    menu = (payload.get("data") or {}).get("menu") or {}
    items = menu.get("menu_items") or []
    if not isinstance(items, list):
        return []
    return items


def is_category_url_info(info: dict[str, Any] | None) -> bool:
    """True khi url_info là trang danh mục (có category_id, không có product_id)."""
    if not info:
        return False
    category_id = info.get("category_id")
    product_id = info.get("product_id")
    return bool(category_id) and not product_id


async def resolve_category_id_for_path(request_path: str) -> int | None:
    info = await url_info(request_path)
    if not is_category_url_info(info):
        return None
    try:
        return int(info["category_id"])
    except (TypeError, ValueError, KeyError):
        return None


def _write_map_files(out_path: Path, payload: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    map_txt = out_path.with_suffix(".map")
    entries = payload.get("entries") or {}
    lines = [f"{name}:{cid}" for name, cid in sorted(entries.items())]
    map_txt.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _load_sync_state(out_path: Path) -> dict[str, Any]:
    if not out_path.is_file():
        return {
            "entries": {},
            "skipped": [],
            "errors": [],
            "processed_paths": set(),
            "entry_paths": {},
        }
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "entries": {},
            "skipped": [],
            "errors": [],
            "processed_paths": set(),
            "entry_paths": {},
        }

    entries_raw = data.get("entries") or {}
    skipped = data.get("skipped") or []
    errors = data.get("errors") or []
    entry_paths_raw = data.get("entry_paths") or {}
    processed = set(data.get("processed_paths") or [])
    if not processed:
        for row in skipped:
            if isinstance(row, dict) and row.get("path"):
                processed.add(str(row["path"]))
        for row in errors:
            if isinstance(row, dict) and row.get("path"):
                processed.add(str(row["path"]))
        if isinstance(entry_paths_raw, dict):
            for path in entry_paths_raw.values():
                if path:
                    processed.add(str(path))

    return {
        "entries": (
            {str(k): str(v) for k, v in entries_raw.items()}
            if isinstance(entries_raw, dict)
            else {}
        ),
        "skipped": [r for r in skipped if isinstance(r, dict)],
        "errors": [r for r in errors if isinstance(r, dict)],
        "processed_paths": processed,
        "entry_paths": (
            {str(k): str(v) for k, v in entry_paths_raw.items()}
            if isinstance(entry_paths_raw, dict)
            else {}
        ),
    }


async def build_menu_category_map(
    *,
    menu_id: int | None = None,
    delay_sec: float | None = None,
    output_path: Path | str | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Fetch main menu → url_info từng link (throttle) → lưu map menu_name:category_id."""
    import asyncio

    mid = menu_id if menu_id is not None else CPS_MAIN_MENU_ID
    pause = delay_sec if delay_sec is not None else MENU_CATEGORY_FETCH_DELAY_SEC
    out_path = Path(output_path or MENU_CATEGORY_MAP_PATH)

    items = await fetch_main_menu_items(mid)
    links = collect_menu_links(items)
    logger.info("Menu id=%s: %d link cần kiểm tra url_info", mid, len(links))

    state = _load_sync_state(out_path) if resume else {
        "entries": {},
        "skipped": [],
        "errors": [],
        "processed_paths": set(),
        "entry_paths": {},
    }
    entries: dict[str, str] = dict(state["entries"])
    entry_paths: dict[str, str] = dict(state.get("entry_paths") or {})
    skipped: list[dict[str, str]] = list(state["skipped"])
    errors: list[dict[str, str]] = list(state["errors"])
    processed_paths: set[str] = set(state["processed_paths"])

    def persist(progress_idx: int) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "menu_id": mid,
            "link_count": len(links),
            "category_count": len(entries),
            "progress_index": progress_idx,
            "entries": entries,
            "entry_paths": entry_paths,
            "skipped": skipped,
            "errors": errors,
            "processed_paths": sorted(processed_paths),
        }
        _write_map_files(out_path, payload)

    for idx, (menu_name, path) in enumerate(links, start=1):
        if path in processed_paths:
            logger.debug("Bỏ qua đã xử lý [%d/%d] %r (%s)", idx, len(links), menu_name, path)
            continue

        logger.info("[%d/%d] url_info %r (%s)", idx, len(links), menu_name, path)
        try:
            category_id = await resolve_category_id_for_path(path)
        except Exception as exc:
            logger.warning("url_info lỗi %s: %s", path, exc)
            errors.append({"name": menu_name, "path": path, "error": str(exc)[:200]})
            category_id = None

        processed_paths.add(path)
        if category_id is not None:
            entries[menu_name] = str(category_id)
            entry_paths[menu_name] = path
        else:
            skipped.append({"name": menu_name, "path": path, "reason": "not_category"})

        persist(idx)

        if idx < len(links) and pause > 0:
            await asyncio.sleep(pause)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "menu_id": mid,
        "link_count": len(links),
        "category_count": len(entries),
        "progress_index": len(links),
        "entries": entries,
        "entry_paths": entry_paths,
        "skipped": skipped,
        "errors": errors,
        "processed_paths": sorted(processed_paths),
    }
    _write_map_files(out_path, payload)

    logger.info(
        "Đã lưu %d category → %s và %s",
        len(entries),
        out_path,
        out_path.with_suffix(".map"),
    )
    return payload


def load_menu_category_map(
    path: Path | str | None = None,
) -> dict[str, str]:
    """Đọc map menu_name → category_id từ file JSON."""
    file_path = Path(path or MENU_CATEGORY_MAP_PATH)
    if not file_path.is_file():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    entries = data.get("entries") or {}
    if not isinstance(entries, dict):
        return {}
    return {str(k): str(v) for k, v in entries.items()}


def category_id_for_menu_name(name: str, mapping: dict[str, str] | None = None) -> str:
    """Tra category_id theo tên menu (không phân biệt hoa thường)."""
    table = mapping if mapping is not None else load_menu_category_map()
    if not name:
        return ""
    if name in table:
        return table[name]
    lower = name.lower()
    for key, value in table.items():
        if key.lower() == lower:
            return value
    return ""
