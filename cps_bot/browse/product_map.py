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

from config import (
    PRODUCT_MAP_ENABLED,
    PRODUCT_MAP_MIN_CONFIDENCE,
    PRODUCT_MAP_MIN_SCORE,
    PRODUCT_MAP_PATH,
)

logger = logging.getLogger(__name__)

_LINE_RE = re.compile(r"^\s*(\d+)\s*-\s*(.+?)\s*$")
_STORAGE_RE = re.compile(
    r"\b(64|128|256|512|1024)\s*(?:gb|g)\b|\b(1|2)\s*tb\b",
    re.I,
)
_CHIP_PRO_RE = re.compile(r"\b(?:a\d+|m\d+)\s*pro\b", re.I)
_M_CHIP_RE = re.compile(r"\bm([1-5])\b", re.I)
_GALAXY_S_GEN_RE = re.compile(r"\b(?:samsung\s+)?(?:galaxy\s+)?s(\d{2})\b", re.I)
_GALAXY_S_GEN_IN_NAME_RE = re.compile(r"\bgalaxy\s*s(\d{2})\b", re.I)
_SCREEN_INCHES = frozenset({"13", "14", "15", "16"})
_MACBOOK_ACCESSORY_HINTS = (
    "bo dan", "bộ dán", "dan macbook", "dán macbook", "innostyle", "zeelot",
    "6in1", "6 in 1", "for macbook", "cho macbook", "ốp macbook", "op macbook",
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
_COLOR_TOKENS = frozenset({
    "hong", "den", "trang", "xanh", "titan", "vang", "tim", "cam", "bac",
    "luu", "ly", "mong", "ket", "ultramarine",
})
_MODEL_DISTINCT_TOKENS = frozenset({
    "neo", "air", "ultra", "plus", "mini", "se", "fold", "flip", "fe",
})

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
    confidence: float


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


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


def _brand_families(folded: str) -> set[str]:
    families: set[str] = set()
    if "macbook" in folded:
        families.add("macbook")
    if "mac mini" in folded or re.search(r"\bmacmini\b", folded):
        families.add("mac_mini")
    if "mac studio" in folded:
        families.add("mac_studio")
    if "iphone" in folded:
        families.add("iphone")
    if "ipad" in folded:
        families.add("ipad")
    if "imac" in folded:
        families.add("imac")
    if "galaxy" in folded or ("samsung" in folded and re.search(r"\bs\d", folded)):
        families.add("galaxy")
    if re.search(r"\bs\d{2}\b", folded):
        families.add("galaxy")
    if "redmi" in folded:
        families.add("redmi")
    if "xiaomi" in folded:
        families.add("xiaomi")
    if "oppo" in folded:
        families.add("oppo")
    if "vivo" in folded:
        families.add("vivo")
    if "realme" in folded:
        families.add("realme")
    return families


def _required_model_phrases(folded: str) -> list[str]:
    """Cụm model bắt buộc phải có trong tên SP nếu user nhắc."""
    from cps_bot.browse.product_lines import required_model_phrases

    return required_model_phrases(folded)


def _m_chips(text: str) -> set[str]:
    """Chip Apple Silicon M1–M5 trong câu hỏi/tên SP."""
    folded = _fold(text)
    return {f"m{m.group(1)}" for m in _M_CHIP_RE.finditer(folded)}


def _screen_inches(text: str, tokens: set[str] | None = None) -> set[str]:
    """Kích thước màn hình laptop (inch), không nhầm 16GB RAM."""
    folded = _fold(text)
    tok = tokens if tokens is not None else _tokenize(text)
    sizes: set[str] = set()
    for sz in _SCREEN_INCHES:
        if re.search(rf"\b{sz}\s*(?:inch|\"|in)\b", folded):
            sizes.add(sz)
        elif sz in tok and f"{sz}gb" not in tok:
            sizes.add(sz)
    return sizes


def _macbook_accessory_penalty(folded_name: str, name_lower: str) -> int:
    hints = _ACCESSORY_NAME_HINTS + _MACBOOK_ACCESSORY_HINTS
    if any(h in name_lower or h in folded_name for h in hints):
        return 80
    return 0


def _apple_silicon_score_adjustment(
    query_folded: str,
    query_tokens: set[str],
    folded_name: str,
    entry_tokens: frozenset[str],
) -> int:
    """Khớp/ lệch thế hệ chip M và kích thước màn hình MacBook."""
    if "macbook" not in query_folded:
        return 0

    points = 0
    q_chips = _m_chips(query_folded)
    e_chips = _m_chips(folded_name)
    if q_chips:
        if e_chips:
            if q_chips & e_chips:
                points += 40
            else:
                points -= 90
        elif any(chip in folded_name for chip in ("m1", "m2", "m3", "m4")):
            points -= 90
        elif re.search(r"\b202[12]\b", folded_name):
            points -= 70

    q_sizes = _screen_inches(query_folded, query_tokens)
    e_sizes = _screen_inches(folded_name, set(entry_tokens))
    if q_sizes and e_sizes:
        if q_sizes & e_sizes:
            points += 25
        else:
            points -= 55

    return points


def _is_chip_pro_reference(folded_name: str) -> bool:
    """A18 Pro / M3 Pro trong tên chip — không phải dòng Pro của iPhone."""
    return bool(_CHIP_PRO_RE.search(folded_name))


def _entry_has_tier_pro(folded_name: str) -> bool:
    """Dòng Pro/Pro Max thật (iPhone Pro, MacBook Pro), không tính chip Pro."""
    if "pro max" in folded_name:
        return True
    if not re.search(r"\bpro\b", folded_name):
        return False
    if _is_chip_pro_reference(folded_name):
        return False
    if "macbook pro" in folded_name:
        return True
    if re.search(r"\biphone\b", folded_name):
        return True
    if re.search(r"\bipad\b", folded_name):
        return True
    return False


def compute_map_match_confidence(keywords: str, entry_name: str) -> float:
    """
    Độ khớp 0–1 giữa câu hỏi user và tên SP map.
    Dùng để từ chối map hit yếu và fallback GraphQL search.
    """
    query_folded = _fold(keywords)
    entry_folded = _fold(entry_name)
    query_tokens = _tokenize(keywords)
    if not query_tokens:
        return 0.0

    q_brands = _brand_families(query_folded)
    e_brands = _brand_families(entry_folded)
    if q_brands and e_brands and not (q_brands & e_brands):
        return 0.0

    q_chips = _m_chips(query_folded)
    e_chips = _m_chips(entry_folded)
    if q_chips:
        if e_chips and not (q_chips & e_chips):
            return 0.0
        if not e_chips and (
            any(chip in entry_folded for chip in ("m1", "m2", "m3", "m4"))
            or re.search(r"\b202[12]\b", entry_folded)
        ):
            return 0.0

    q_sizes = _screen_inches(query_folded, query_tokens)
    e_sizes = _screen_inches(entry_folded)
    if q_sizes and e_sizes and not (q_sizes & e_sizes):
        return 0.0

    if "macbook" in query_folded and _macbook_accessory_penalty(entry_folded, entry_folded):
        return 0.0

    for phrase in _required_model_phrases(query_folded):
        if phrase not in entry_folded:
            return 0.0

    galaxy_gen = _GALAXY_S_GEN_RE.search(query_folded)
    if galaxy_gen:
        gen = galaxy_gen.group(1)
        if not re.search(rf"\bgalaxy\s*s{gen}\b", entry_folded):
            return 0.0
        if "apple watch" in entry_folded or re.search(r"\bwatch\s+ultra\b", entry_folded):
            return 0.0

    query_storage = _storage_tokens(keywords)
    weighted_hits = 0.0
    weighted_total = 0.0
    for token in query_tokens:
        if token in query_storage:
            weight = 0.2
        elif token in _COLOR_TOKENS:
            weight = 0.25
        elif token in q_brands or token in _MODEL_DISTINCT_TOKENS:
            weight = 1.0
        else:
            weight = 0.55
        weighted_total += weight
        if token in entry_folded:
            weighted_hits += weight

    if weighted_total <= 0:
        return 0.0

    ratio = weighted_hits / weighted_total

    non_variant = {
        t
        for t in query_tokens
        if t not in query_storage and t not in _COLOR_TOKENS
    }
    variant_only = bool(query_storage or _COLOR_QUERY_RE.search(query_folded))
    if len(non_variant) >= 2:
        matched_core = sum(1 for t in non_variant if t in entry_folded)
        core_ratio = matched_core / len(non_variant)
        if core_ratio < 0.5:
            ratio *= max(0.35, core_ratio)
        elif variant_only and matched_core == len(non_variant):
            ratio = min(1.0, ratio + 0.08)

    return round(min(1.0, max(0.0, ratio)), 3)


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

    q_brands = _brand_families(query_folded)
    e_brands = _brand_families(entry.text_folded)
    if q_brands and e_brands and not (q_brands & e_brands):
        return 0

    overlap = query_tokens & entry.tokens
    if not overlap:
        if len(query_folded) >= 6 and query_folded in entry.text_folded:
            overlap = query_tokens
        else:
            return 0

    points = len(overlap) * 12
    for token in query_tokens:
        if len(token) >= 2 and token in entry.text_folded:
            points += 4

    points -= max(0, len(entry.tokens) - len(query_tokens)) * 2

    name_lower = entry.name.lower()
    folded_name = entry.text_folded
    if not wants_used and any(h in name_lower or h in folded_name for h in _USED_NAME_HINTS):
        points -= 25
    if phone_query and any(h in name_lower for h in _ACCESSORY_NAME_HINTS):
        points -= 50
    if "macbook" in query_folded:
        points -= _macbook_accessory_penalty(folded_name, name_lower)
        points += _apple_silicon_score_adjustment(
            query_folded, query_tokens, folded_name, entry.tokens
        )

    if "macbook" in query_tokens and "neo" in query_tokens:
        if "macbook" in entry.tokens and "neo" in entry.tokens:
            points += 40
        elif "macbook" not in entry.tokens or "neo" not in entry.tokens:
            points -= 50

    non_variant = query_tokens - query_storage - _COLOR_TOKENS
    if query_storage and len(non_variant) >= 2:
        core_overlap = non_variant & entry.tokens
        if query_storage & _storage_tokens(entry.name) and len(core_overlap) < len(non_variant):
            points -= 45

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
        and not _entry_has_tier_pro(folded_name)
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
        if not _entry_has_tier_pro(folded_name):
            points -= 12
        elif "pro max" in folded_name:
            points -= 10
    else:
        if "pro max" in folded_name:
            points -= 22
        elif _entry_has_tier_pro(folded_name):
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
            and not _entry_has_tier_pro(folded_name)
            and gen_match
        ):
            points += 24

    galaxy_gen = _GALAXY_S_GEN_RE.search(query_folded)
    if galaxy_gen:
        gen = galaxy_gen.group(1)
        if re.search(rf"\bgalaxy\s*s{gen}\b", folded_name):
            points += 40
            if "ultra" in query_tokens and "ultra" in folded_name:
                points += 18
            elif "plus" in query_tokens and "plus" in folded_name:
                points += 14
        elif _GALAXY_S_GEN_IN_NAME_RE.search(folded_name):
            entry_gen = _GALAXY_S_GEN_IN_NAME_RE.search(folded_name)
            if entry_gen and entry_gen.group(1) != gen:
                points -= 80
        elif re.search(rf"\bs{gen}\b", query_folded) and not re.search(
            rf"\bs{gen}\b", folded_name
        ):
            points -= 55
        if "apple watch" in folded_name or re.search(
            r"\bwatch\s+ultra\b", folded_name
        ):
            points -= 120
        if "ultra tab" in folded_name or re.search(r"\bultra\s+tab\b", folded_name):
            points -= 80
        if any(h in folded_name for h in ("op lung", "ốp lưng", "bao da")):
            points -= 70

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
    """Chọn 1 entry khi điểm map sát nhau — ưu tiên khớp brand/model phrase."""
    if not ranked:
        return None
    best_score = ranked[0][0]
    candidates = [entry for score, entry in ranked if score >= best_score - 4]
    if len(candidates) == 1:
        return candidates[0]

    q_brands = _brand_families(query_folded)
    required_phrases = _required_model_phrases(query_folded)

    def tie_key(entry: ProductMapEntry) -> tuple[float, int, int, int]:
        folded = entry.text_folded
        conf = compute_map_match_confidence(query_folded, entry.name)
        points = int(conf * 100)
        if q_brands and not (q_brands & _brand_families(folded)):
            points -= 200
        for phrase in required_phrases:
            if phrase not in folded:
                points -= 80
        if "pro max" in folded and "pro max" not in query_folded:
            points -= 35
        elif _entry_has_tier_pro(folded) and "pro" not in query_tokens:
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
        return (points, -len(entry.tokens), -len(entry.name), 0)

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

    winner = best_entry
    if second_score and best_score - second_score < 5:
        picked = _pick_map_ambiguity_winner(ranked[:12], query_folded, query_tokens)
        if not picked:
            return None
        winner = picked

    confidence = compute_map_match_confidence(keywords, winner.name)
    if confidence < PRODUCT_MAP_MIN_CONFIDENCE:
        logger.info(
            "Product map bỏ hit %s (confidence=%.2f < %.2f) cho %r → fallback search",
            winner.product_id,
            confidence,
            PRODUCT_MAP_MIN_CONFIDENCE,
            keywords[:80],
        )
        return None

    return ProductMapHit(
        winner.product_id,
        winner.name,
        best_score,
        confidence,
    )


def clear_product_map_cache() -> None:
    """Xóa cache sau khi cập nhật file map."""
    _load_entries.cache_clear()
