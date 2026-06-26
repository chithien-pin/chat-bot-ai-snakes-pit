"""
Tra cứu product_id từ file map {{productId}}-{{productName}}.
Dùng trước GraphQL search để resolve nhanh và chính xác hơn.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config import PRODUCT_MAP_ENABLED, PRODUCT_MAP_MIN_SCORE, PRODUCT_MAP_PATH

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")
_STORAGE_RE = re.compile(
    r"\b(64|128|256|512|1024)\s*(?:gb|g)\b|\b(1|2)\s*tb\b",
    re.I,
)
_USED_NAME_HINTS = (
    "cũ", "cu ", " cu", "đã kích hoạt", "da kich hoat",
    "đổi bảo hành", "doi bao hanh", "đổi bh", "hàng trưng bày",
)
_ACCESSORY_NAME_HINTS = (
    "ốp lưng", "op lung", "tai nghe", "chuột", "chuot", "bàn phím",
    "ban phim", "cáp ", "cap ", "củ sạc", "cu sac", "pin sạc",
    "kinh cường lực", "miếng dán",
)
_PHONE_QUERY_HINTS = (
    "iphone", "ipad", "samsung", "galaxy", "xiaomi", "oppo", "vivo",
    "điện thoại", "dien thoai", "macbook", "laptop",
)
_COLOR_QUERY_RE = re.compile(
    r"\b("
    r"hồng|hong|đen|den|trắng|trang|xanh|titan|vàng|vang|tím|tim|"
    r"cam|bạc|bac|lưu ly|luu ly|mỏng két|mong ket|ultramarine"
    r")\b",
    re.IGNORECASE,
)

_STOP_TOKENS = frozenset({
    "mã", "ma", "giá", "gia", "cho", "mình", "minh", "còn", "co",
    "có", "không", "khong", "bao", "nhiêu", "nhieu", "hôm", "nay",
    "check", "mua", "tháng", "thang", "này", "nay",
})


@dataclass(frozen=True)
class ProductMapEntry:
    product_id: str
    name: str
    tokens: frozenset[str]
    text_folded: str


@dataclass(frozen=True)
class ProductMapHit:
    product_id: str
    name: str
    score: int


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _tokenize(text: str) -> set[str]:
    folded = _fold(text.replace("-", " "))
    tokens = {
        t
        for t in re.findall(r"[a-z0-9]+", folded)
        if len(t) >= 2 and t not in _STOP_TOKENS
    }
    for m in _STORAGE_RE.finditer(text or ""):
        if m.group(2):
            tokens.add(f"{m.group(2)}tb")
        else:
            tokens.add(f"{m.group(1)}gb")
    return tokens


def _is_map_query(keywords: str) -> bool:
    kw = (keywords or "").strip().lower()
    if len(kw) < 3:
        return False
    if kw.startswith("http") or ".html" in kw:
        return False
    return True


@lru_cache(maxsize=1)
def _load_entries(path: str) -> tuple[ProductMapEntry, ...]:
    file_path = Path(path)
    if not file_path.is_file():
        logger.warning("Product map không tồn tại: %s", file_path)
        return ()

    entries: list[ProductMapEntry] = []
    with file_path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = _LINE_RE.match(line.strip())
            if not match:
                continue
            product_id = match.group(1).strip()
            name = match.group(2).strip()
            if not product_id or not name:
                continue
            entries.append(
                ProductMapEntry(
                    product_id=product_id,
                    name=name,
                    tokens=frozenset(_tokenize(name)),
                    text_folded=_fold(name),
                )
            )
    logger.info("Đã load product map: %d SP từ %s", len(entries), file_path)
    return tuple(entries)


def _storage_tokens(text: str) -> set[str]:
    folded = _fold(text or "")
    tokens: set[str] = set()
    for m in _STORAGE_RE.finditer(folded):
        if m.group(2):
            tokens.add(f"{m.group(2)}tb")
        else:
            tokens.add(f"{m.group(1)}gb")
    return tokens


def _score_entry(
    entry: ProductMapEntry,
    query_tokens: set[str],
    query_folded: str,
    *,
    query_storage: set[str],
    wants_used: bool,
    phone_query: bool,
) -> int:
    if not query_tokens:
        return 0

    overlap = query_tokens & entry.tokens
    if not overlap:
        # Cho phép khớp chuỗi con dài (vd: wh-1000xm5)
        if len(query_folded) >= 6 and query_folded in entry.text_folded:
            overlap = query_tokens
        else:
            return 0

    points = len(overlap) * 12
    for token in query_tokens:
        if len(token) >= 2 and token in entry.text_folded:
            points += 4

    # Ưu tiên tên ngắn gọn khi overlap tương đương
    points -= max(0, len(entry.tokens) - len(query_tokens)) * 2

    name_lower = entry.name.lower()
    folded_name = entry.text_folded
    if not wants_used and any(h in name_lower or h in folded_name for h in _USED_NAME_HINTS):
        points -= 25
    if phone_query and any(h in name_lower for h in _ACCESSORY_NAME_HINTS):
        points -= 50

    if "pro max" in query_folded and "pro max" in folded_name:
        points += 20
    elif "pro" in query_tokens and "pro" in folded_name and "max" not in query_tokens:
        if "pro max" in folded_name:
            points -= 10
        else:
            points += 10

    entry_storage = _storage_tokens(entry.name)
    gen_match = re.search(r"\biphone\s*(\d{1,2})\b", query_folded)
    if query_storage:
        if entry_storage & query_storage:
            points += 18
        elif entry_storage:
            points -= 35
    elif entry_storage:
        if not _COLOR_QUERY_RE.search(query_folded):
            points -= 12
        elif not query_storage:
            if "128gb" in entry_storage:
                points += 14
            else:
                points -= 10
    elif (
        _COLOR_QUERY_RE.search(query_folded)
        and not query_storage
        and phone_query
        and gen_match
        and "plus" not in folded_name
        and not re.search(r"\bpro\b", folded_name)
        and re.fullmatch(r"iphone \d{1,2}", folded_name)
    ):
        points += 16

    if gen_match:
        gen = gen_match.group(1)
        if re.search(rf"\biphone\s*{gen}\b", folded_name):
            points += 28
        elif re.search(r"\biphone\s*(\d{1,2})\b", folded_name):
            entry_gen = re.search(r"\biphone\s*(\d{1,2})\b", folded_name)
            if entry_gen and entry_gen.group(1) != gen:
                points -= 70

    if "pro max" in query_folded:
        if "pro max" not in folded_name:
            points -= 18
    elif "pro" in query_tokens:
        if "pro" not in folded_name:
            points -= 12
        elif "pro max" in folded_name:
            points -= 10
    else:
        if "pro max" in folded_name:
            points -= 22
        elif re.search(r"\bpro\b", folded_name):
            points -= 16
        if "plus" in folded_name and "plus" not in query_tokens:
            points -= 50
        if "ultra" in folded_name and "ultra" not in query_tokens:
            points -= 40
        if (
            re.search(r"\bmax\b", folded_name)
            and "pro max" not in folded_name
            and "max" not in query_folded
            and "pro max" not in query_folded
        ):
            points -= 50
        if re.search(r"\bmini\b", folded_name) and "mini" not in query_folded:
            points -= 45
        if re.search(r"\b16e\b", folded_name) and "16e" not in query_folded.replace(" ", ""):
            points -= 40
        if (
            query_storage
            and not entry_storage
            and "plus" not in folded_name
            and not re.search(r"\bpro\b", folded_name)
            and gen_match
        ):
            points += 24

    return points


def _quality_bonus(entry: ProductMapEntry, *, wants_used: bool) -> int:
    name_lower = entry.name.lower()
    folded = entry.text_folded
    bonus = 0
    if not wants_used:
        if any(h in name_lower or h in folded for h in _USED_NAME_HINTS):
            bonus -= 60
        else:
            bonus += 25
        if "chính hãng" in name_lower or "chinh hang" in folded:
            bonus += 12
    if any(h in name_lower for h in _ACCESSORY_NAME_HINTS):
        bonus -= 40
    return bonus


def _pick_map_ambiguity_winner(
    ranked: list[tuple[int, ProductMapEntry]],
    query_folded: str,
    query_tokens: set[str],
) -> ProductMapEntry | None:
    """Chọn 1 entry khi điểm map sát nhau — ưu tiên bản base, tên ngắn."""
    if not ranked:
        return None
    best_score = ranked[0][0]
    candidates = [entry for score, entry in ranked if score >= best_score - 4]
    if len(candidates) == 1:
        return candidates[0]

    def tie_key(entry: ProductMapEntry) -> tuple[int, int, int]:
        folded = entry.text_folded
        points = 0
        if "pro max" in folded and "pro max" not in query_folded:
            points -= 35
        elif re.search(r"\bpro\b", folded) and "pro" not in query_tokens:
            points -= 25
        if "plus" in folded and "plus" not in query_tokens:
            points -= 35
        if "ultra" in folded and "ultra" not in query_tokens:
            points -= 30
        if (
            re.search(r"\bmax\b", folded)
            and "pro max" not in folded
            and "max" not in query_folded
        ):
            points -= 40
        if re.search(r"\bmini\b", folded) and "mini" not in query_folded:
            points -= 35
        if re.fullmatch(r"iphone \d{1,2}", folded):
            points += 20
        return (points, -len(entry.tokens), -len(entry.name))

    return max(candidates, key=tie_key)


def resolve_product_from_map(keywords: str) -> ProductMapHit | None:
    """Tìm product_id khớp nhất từ map — None nếu không đủ tin cậy."""
    from cps_bot.browse.product_term_synonyms import normalize_product_terms

    keywords = normalize_product_terms(keywords)
    if not PRODUCT_MAP_ENABLED or not _is_map_query(keywords):
        return None

    entries = _load_entries(PRODUCT_MAP_PATH)
    if not entries:
        return None

    query_tokens = _tokenize(keywords)
    query_folded = _fold(keywords)
    if not query_tokens and len(query_folded) < 4:
        return None

    query_storage = _storage_tokens(keywords)
    wants_used = bool(re.search(r"\b(?:cũ|cu|hàng cũ|hang cu)\b", keywords, re.I))
    phone_query = any(h in query_folded for h in _PHONE_QUERY_HINTS)

    ranked: list[tuple[int, ProductMapEntry]] = []
    for entry in entries:
        score = _score_entry(
            entry,
            query_tokens,
            query_folded,
            query_storage=query_storage,
            wants_used=wants_used,
            phone_query=phone_query,
        )
        total = score + _quality_bonus(entry, wants_used=wants_used)
        if total >= PRODUCT_MAP_MIN_SCORE:
            ranked.append((total, entry))

    if not ranked:
        return None

    ranked.sort(key=lambda row: (row[0], -len(row[1].tokens)), reverse=True)
    best_score, best_entry = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0

    if second_score and best_score - second_score < 5:
        winner = _pick_map_ambiguity_winner(ranked[:8], query_folded, query_tokens)
        if winner:
            return ProductMapHit(winner.product_id, winner.name, best_score)
        return None

    return ProductMapHit(best_entry.product_id, best_entry.name, best_score)


def clear_product_map_cache() -> None:
    """Xóa cache sau khi cập nhật file map."""
    _load_entries.cache_clear()
