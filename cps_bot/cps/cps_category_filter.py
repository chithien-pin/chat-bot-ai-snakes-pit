"""
Category filter — sync attributes theo category_id + build GraphQL dynamic filter.
Tham chiếu cps-nuxt-standard/store/product.js getFilterByCateId + FilterModule.vue.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from config import (
    CATEGORY_ATTRIBUTES_FETCH_DELAY_SEC,
    CATEGORY_ATTRIBUTES_MAP_PATH,
    CPS_GRAPHQL_V2_ENDPOINT,
    CPS_PROVINCE_ID,
    MENU_CATEGORY_MAP_PATH,
)
from cps_bot.cps.cps_menu import load_menu_category_map

logger = logging.getLogger(__name__)

CATEGORY_BY_ID_QUERY_TEMPLATE = """
query {{
  category(id: {category_id}) {{
    id
    name
    parent_id
    path
    uri
    attributes
    categories
    max_price
    min_price
  }}
}}
"""

_FILTER_STOP_WORDS = frozenset({
    "gb", "tb", "mb", "inch", "core", "chip", "cpu", "ram", "ssd", "hdd",
    "laptop", "dien", "thoai", "dùng", "dung", "cho", "mua", "tim", "tìm",
    "có", "co", "không", "khong", "và", "va", "the", "loại", "loai",
})


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _norm_text(text: str) -> str:
    value = _strip_accents((text or "").lower())
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokenize(text: str) -> set[str]:
    return {
        t
        for t in _norm_text(text).split()
        if len(t) >= 2 and t not in _FILTER_STOP_WORDS
    }


def _parse_json_field(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def normalize_category_attributes(raw_attributes: Any) -> list[dict[str, Any]]:
    """Chuẩn hóa attributes từ GraphQL category."""
    attrs = _parse_json_field(raw_attributes)
    if not isinstance(attrs, list):
        return []

    out: list[dict[str, Any]] = []
    for item in attrs:
        if not isinstance(item, dict):
            continue
        if not item.get("active", True):
            continue
        key = str(item.get("key") or "").strip()
        label = str(item.get("label") or "").strip()
        if not key or not label:
            continue

        options: list[dict[str, Any]] = []
        for opt in item.get("data") or []:
            if not isinstance(opt, dict):
                continue
            if not opt.get("active", True):
                continue
            opt_label = str(opt.get("label") or "").strip()
            nice_uri = str(opt.get("nice_uri") or opt.get("value") or "").strip()
            if not opt_label or not nice_uri:
                continue
            options.append(
                {
                    "label": opt_label,
                    "nice_uri": nice_uri,
                    "label_norm": _norm_text(opt_label),
                    "tokens": sorted(_tokenize(f"{opt_label} {nice_uri.replace('-', ' ')}")),
                }
            )

        if len(options) < 2:
            continue

        out.append(
            {
                "key": key,
                "label": label,
                "label_norm": _norm_text(label),
                "options": options,
            }
        )
    return out


async def fetch_category_attributes(category_id: str | int) -> dict[str, Any] | None:
    """Lấy metadata + attributes của category (giống getFilterByCateId)."""
    cid = str(category_id).strip()
    if not cid.isdigit():
        return None

    query = CATEGORY_BY_ID_QUERY_TEMPLATE.format(category_id=cid)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CPS_GRAPHQL_V2_ENDPOINT,
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
        raise RuntimeError(f"Category GraphQL errors: {errors[:1]}")

    category = (payload.get("data") or {}).get("category") or {}
    if not category:
        return None

    attributes = normalize_category_attributes(category.get("attributes"))
    return {
        "id": str(category.get("id") or cid),
        "name": str(category.get("name") or ""),
        "parent_id": str(category.get("parent_id") or ""),
        "uri": str(category.get("uri") or ""),
        "path": str(category.get("path") or ""),
        "max_price": category.get("max_price"),
        "min_price": category.get("min_price"),
        "attribute_count": len(attributes),
        "attributes": attributes,
    }


def _write_attributes_map(out_path: Path, payload: dict[str, Any]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_attributes_sync_state(out_path: Path) -> dict[str, Any]:
    if not out_path.is_file():
        return {"categories": {}, "processed_ids": set()}
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"categories": {}, "processed_ids": set()}

    categories = data.get("categories") or {}
    processed = set(data.get("processed_ids") or [])
    if not processed and isinstance(categories, dict):
        processed = set(categories.keys())
    return {
        "categories": categories if isinstance(categories, dict) else {},
        "processed_ids": processed,
        "menu_names": data.get("menu_names") or {},
    }


def _menu_names_by_category(menu_map: dict[str, str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for name, cid in menu_map.items():
        grouped.setdefault(str(cid), []).append(name)
    for cid in grouped:
        grouped[cid].sort(key=len, reverse=True)
    return grouped


def load_unique_category_ids(menu_map_path: Path | str | None = None) -> list[str]:
    menu_map = load_menu_category_map(menu_map_path)
    return sorted({str(v) for v in menu_map.values() if str(v).strip()})


async def build_category_attributes_map(
    *,
    menu_map_path: Path | str | None = None,
    output_path: Path | str | None = None,
    delay_sec: float | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    """Fetch attributes cho từng category_id trong menu map (throttle)."""
    import asyncio

    out_path = Path(output_path or CATEGORY_ATTRIBUTES_MAP_PATH)
    pause = delay_sec if delay_sec is not None else CATEGORY_ATTRIBUTES_FETCH_DELAY_SEC
    menu_map = load_menu_category_map(menu_map_path)
    menu_names = _menu_names_by_category(menu_map)
    category_ids = load_unique_category_ids(menu_map_path)

    state = _load_attributes_sync_state(out_path) if resume else {
        "categories": {},
        "processed_ids": set(),
    }
    categories: dict[str, Any] = dict(state["categories"])
    processed: set[str] = set(state["processed_ids"])
    errors: list[dict[str, str]] = []

    logger.info("Category attributes: %d id cần sync", len(category_ids))

    for idx, cid in enumerate(category_ids, start=1):
        if cid in processed and cid in categories:
            continue

        logger.info("[%d/%d] category attributes id=%s", idx, len(category_ids), cid)
        try:
            row = await fetch_category_attributes(cid)
        except Exception as exc:
            logger.warning("Category %s lỗi: %s", cid, exc)
            errors.append({"category_id": cid, "error": str(exc)[:200]})
            row = None

        processed.add(cid)
        if row:
            row["menu_names"] = menu_names.get(cid, [])
            categories[cid] = row

        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "category_count": len(categories),
            "processed_ids": sorted(processed),
            "menu_names_index": menu_names,
            "categories": categories,
            "errors": errors,
        }
        _write_attributes_map(out_path, payload)

        if idx < len(category_ids) and pause > 0:
            await asyncio.sleep(pause)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "category_count": len(categories),
        "processed_ids": sorted(processed),
        "menu_names_index": menu_names,
        "categories": categories,
        "errors": errors,
    }
    _write_attributes_map(out_path, payload)
    logger.info("Đã lưu %d category attributes → %s", len(categories), out_path)
    return payload


def load_category_attributes_map(
    path: Path | str | None = None,
) -> dict[str, Any]:
    return _load_category_attributes_map_cached(str(path or CATEGORY_ATTRIBUTES_MAP_PATH))


@lru_cache(maxsize=2)
def _load_category_attributes_map_cached(file_path: str) -> dict[str, Any]:
    path = Path(file_path)
    if not path.is_file():
        return {"categories": {}, "menu_names_index": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"categories": {}, "menu_names_index": {}}
    if not isinstance(data, dict):
        return {"categories": {}, "menu_names_index": {}}
    return data


def get_category_data(category_id: str | int) -> dict[str, Any] | None:
    by_id = load_category_attributes_map().get("categories") or {}
    row = by_id.get(str(category_id))
    return row if isinstance(row, dict) else None


def build_dynamic_filter_clause(filters: list[tuple[str, list[str]]]) -> str:
    """
    Build dynamic filter giống FilterModule.createMultiQueryFilter.
    Ví dụ: laptop_cpu: {in: ["intel-core-i5"]} use_nice_uri: true
    """
    parts: list[str] = []
    for key, values in filters:
        uniq = list(dict.fromkeys(v for v in values if v))
        if not uniq:
            continue
        parts.append(f'{key}: {{in: {json.dumps(uniq, ensure_ascii=False)}}}')
    if not parts:
        return ""
    parts.append("use_nice_uri: true")
    return "\n".join(parts)


def build_products_by_category_filter_query(
    category_id: str | int,
    dynamic_filter: str,
    *,
    province_id: int | None = None,
    size: int = 12,
    page: int = 1,
    filter_price: tuple[int, int] | None = None,
) -> str:
    """GraphQL inline query — products theo category + dynamic filter."""
    cid = str(category_id).strip()
    pid = province_id if province_id is not None else CPS_PROVINCE_ID
    price_clause = ""
    if filter_price:
        price_clause = f"filter_price: {{from: {filter_price[0]} to: {filter_price[1]}}},"

    dynamic_block = dynamic_filter.strip()
    if dynamic_block and not dynamic_block.endswith(","):
        dynamic_block = f"{dynamic_block}\n"

    filter_parts = [
        f"""static: {{
        categories: ["{cid}"],
        province_id: {pid},
        stock: {{ from: 0 }},
        company_stock_id: [46, 56, 152, 4920],
        {price_clause}
      }}"""
    ]
    if dynamic_block:
        filter_parts.append(f"dynamic: {{\n        {dynamic_block}      }}")
    filter_body = ",\n      ".join(filter_parts)

    return f"""
query GetProductsByCategoryFilter {{
  products(
    filter: {{
      {filter_body}
    }},
    page: {page},
    size: {size},
    sort: [{{view: desc}}]
  ) {{
    general {{
      product_id
      name
      sku
      manufacturer
      url_key
      url_path
    }}
    filterable {{
      price
      prices
      special_price
      thumbnail
      stock_available_id
      stock
      promotion_information
    }}
  }}
}}
"""

async def get_products_by_category_filter(
    category_id: str | int,
    dynamic_filter: str,
    *,
    province_id: int | None = None,
    size: int = 12,
    page: int = 1,
    filter_price: tuple[int, int] | None = None,
) -> list[dict[str, Any]]:
    if not dynamic_filter.strip() and not filter_price:
        return []

    query = build_products_by_category_filter_query(
        category_id,
        dynamic_filter,
        province_id=province_id,
        size=size,
        page=page,
        filter_price=filter_price,
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            CPS_GRAPHQL_V2_ENDPOINT,
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
        logger.warning("Category filter GraphQL errors: %s", errors[:1])
        return []

    products = (payload.get("data") or {}).get("products") or []
    return [p for p in products if isinstance(p, dict) and p.get("general")]
