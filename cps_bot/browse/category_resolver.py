"""
Resolve user text → category_id + canonical menu name.

Ưu tiên:
1. Đồng nghĩa dài / cụ thể hơn (dán màn hình trước màn hình)
2. Đồng nghĩa (máy tính bảng → Tablet / category 4)
3. Category level cao (path ngắn) — chỉ khi không bị synonym ngắn hơn lấn át
4. Bỏ hàng cũ trừ khi user hỏi rõ "cũ"
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from cps_bot.cps.cps_category_filter import load_category_attributes_map
from cps_bot.cps.cps_menu import load_menu_category_map, load_menu_entry_paths

try:
    from cps_bot.browse.budget_browse import strip_budget_phrases_for_keywords
except ImportError:
    def strip_budget_phrases_for_keywords(text: str) -> str:
        return text or ""

# Đồng nghĩa cố định → menu name chuẩn trên CPS
_CANONICAL_MENU_ALIASES: dict[str, tuple[str, ...]] = {
    "Tablet": ("tablet", "máy tính bảng", "may tinh bang", "mtb", "máy tính bảng mới"),
    "Điện thoại": (
        "điện thoại",
        "dien thoai",
        "smartphone",
        "smart phone",
        "dt",
        "mobile",
    ),
    "Laptop": ("laptop", "máy tính xách tay", "may tinh xach tay", "notebook", "lap top"),
    "Laptop Gaming": (
        "laptop gaming",
        "gaming laptop",
        "laptop choi game",
        "laptop chơi game",
        "lap top gaming",
    ),
    "Laptop Văn phòng": (
        "laptop van phong",
        "laptop văn phòng",
        "laptop lam viec van phong",
    ),
    "MacBook": ("macbook", "mac book", "máy mac", "may mac"),
    "iPad": ("ipad",),
    "Tivi": ("tivi", "tv", "television"),
    "Màn hình": ("màn hình", "man hinh", "monitor"),
    "Dán màn hình": (
        "dán màn hình",
        "dan man hinh",
        "miếng dán màn hình",
        "mieng dan man hinh",
        "dan kinh",
        "dán kính",
    ),
    "Âm thanh": ("âm thanh", "am thanh", "loa", "tai nghe", "headphone"),
    "Máy ảnh": ("máy ảnh", "may anh", "camera"),
    "Máy hút bụi cầm tay": (
        "máy hút bụi cầm tay",
        "may hut bui cam tay",
        "máy hút bụi",
        "may hut bui",
        "hút bụi cầm tay",
        "hut bui cam tay",
    ),
    "Robot hút bụi": (
        "robot hút bụi",
        "robot hut bui",
        "robot vacuum",
    ),
    "Đồng hồ": ("đồng hồ", "dong ho", "smartwatch", "smart watch"),
    "Pin dự phòng": (
        "pin",
        "pin du phong",
        "pin dự phòng",
        "pin sac du phong",
        "pin sạc dự phòng",
        "sac du phong",
        "sạc dự phòng",
        "power bank",
    ),
}

_POWER_BANK_PIN_RE = re.compile(r"\bpin\b", re.IGNORECASE)
_MAH_CAPACITY_RE = re.compile(r"\b\d{4,5}\s*mah\b", re.IGNORECASE)
_POWER_BANK_PHRASE_RE = re.compile(
    r"\b(?:pin\s+(?:du\s+)?phong|sac\s+du\s+phong|sạc\s+dự\s+phòng)\b",
    re.IGNORECASE,
)

_PRICE_MENU_NAME_RE = re.compile(
    r"(?:"
    r"^(?:dưới|duoi|từ|tu|trên|tren|tầm|tam)\s+\d|"
    r"\d+\s*(?:-\s*\d+\s*)?(?:triệu|trieu|tr\b)"
    r")",
    re.IGNORECASE,
)

_USED_PRODUCT_TEXT_RE = re.compile(
    r"\b("
    r"cũ|cu(?!\s*van)|hàng cũ|hang cu|"
    r"second\s*hand|refurb|like\s*new|"
    r"máy cũ|may cu"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CategoryMatch:
    category_id: str
    menu_name: str
    category_name: str
    page_path: str
    score: int
    match_reason: str


def _strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _norm(text: str) -> str:
    value = _strip_accents((text or "").lower())
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def user_wants_used_products(text: str) -> bool:
    return bool(_USED_PRODUCT_TEXT_RE.search(text or ""))


def is_price_filter_menu_name(menu_name: str) -> bool:
    return bool(_PRICE_MENU_NAME_RE.search((menu_name or "").strip()))


def is_used_product_menu_name(menu_name: str) -> bool:
    name = (menu_name or "").strip().lower()
    if not name:
        return False
    if name.endswith(" cũ") or name.endswith(" cu"):
        return True
    if " hàng cũ" in name or " hang cu" in name:
        return True
    return name in ("hàng cũ", "hang cu")


def _path_depth(path: str) -> int:
    parts = [p for p in (path or "").split("/") if p]
    return len(parts)


def _synonym_matches_text(syn_n: str, text_norm: str) -> bool:
    """Khớp synonym theo từ — tránh 'o to' trong 'cho toi'."""
    if len(syn_n) < 2:
        return False
    if syn_n == text_norm:
        return True
    pattern = r"(?:^|\s)" + re.escape(syn_n) + r"(?:\s|$)"
    return bool(re.search(pattern, text_norm))


def is_power_bank_query(text: str) -> bool:
    """Câu hỏi về pin/sạc dự phòng (không phải category Anker tai nghe)."""
    norm = _norm(text or "")
    norm = re.sub(r"(\d{4,5})mah\b", r"\1 mah", norm)
    if _POWER_BANK_PHRASE_RE.search(norm):
        return True
    if _POWER_BANK_PIN_RE.search(norm) and _MAH_CAPACITY_RE.search(norm):
        return True
    if _POWER_BANK_PIN_RE.search(norm) and re.search(
        r"\b(?:anker|baseus|ugreen|innostyle|energizer|aukey|mazer)\b",
        norm,
    ):
        return True
    return False


def _is_hang_cu_category(category: dict[str, Any]) -> bool:
    path = f"/{(category.get('path') or '').strip('/')}/"
    if "/29/" in path or path.endswith("/29/"):
        return True
    name = _norm(str(category.get("name") or ""))
    return name.endswith(" cu") or "hang cu" in name


def _pick_canonical_menu_name(
    category_id: str,
    menu_map: dict[str, str],
    entry_paths: dict[str, str],
    index_names: list[str],
) -> str:
    """Menu name chuẩn — ưu tiên trang gốc (tablet.html) và tên ngắn."""
    candidates: list[str] = []
    seen: set[str] = set()

    for name in index_names:
        if (
            menu_map.get(name) == category_id
            and not is_price_filter_menu_name(name)
            and not is_used_product_menu_name(name)
        ):
            candidates.append(name)
            seen.add(name)

    for name, cid in menu_map.items():
        if str(cid) != str(category_id) or name in seen:
            continue
        if is_price_filter_menu_name(name) or is_used_product_menu_name(name):
            continue
        candidates.append(name)
        seen.add(name)

    if not candidates:
        return index_names[0] if index_names else ""

    def rank(name: str) -> tuple[int, int, int]:
        path = entry_paths.get(name, "")
        top_level = 1 if path.endswith(".html") and "/" not in path.rsplit(".html", 1)[0] else 0
        alias_boost = 1 if name in _CANONICAL_MENU_ALIASES else 0
        return (top_level, alias_boost, -len(name))

    return max(candidates, key=rank)


def _synonyms_for_category(
    category_id: str,
    category: dict[str, Any],
    menu_names: list[str],
) -> set[str]:
    syns: set[str] = set()
    for raw in (
        category.get("name"),
        category.get("uri"),
        *menu_names,
    ):
        n = _norm(str(raw or ""))
        if len(n) >= 2:
            syns.add(n)
        if raw:
            syns.add(str(raw).lower().strip())
            syns.add(str(raw).strip())

    uri = str(category.get("uri") or "")
    if uri:
        syns.add(_norm(uri.replace("-", " ")))

    for menu_name, aliases in _CANONICAL_MENU_ALIASES.items():
        if menu_name in menu_names:
            syns.update(_norm(a) for a in aliases)
            syns.update(a.lower() for a in aliases)

    return {s for s in syns if len(s) >= 2}


@lru_cache(maxsize=1)
def _category_match_index() -> list[dict[str, Any]]:
    """Index category + synonym — build 1 lần từ category_attributes_map."""
    attr_map = load_category_attributes_map()
    categories = attr_map.get("categories") or {}
    menu_index = attr_map.get("menu_names") or attr_map.get("menu_names_index") or {}
    menu_map = load_menu_category_map()
    entry_paths = load_menu_entry_paths()

    rows: list[dict[str, Any]] = []
    for category_id, category in categories.items():
        if not isinstance(category, dict):
            continue
        index_names = menu_index.get(str(category_id)) or menu_index.get(category_id) or []
        if not isinstance(index_names, list):
            index_names = [str(index_names)]

        canonical_menu = _pick_canonical_menu_name(
            str(category_id),
            menu_map,
            entry_paths,
            [str(n) for n in index_names],
        )
        menu_names = [canonical_menu] if canonical_menu else []
        for n in index_names:
            ns = str(n)
            if ns and ns not in menu_names and not is_price_filter_menu_name(ns):
                menu_names.append(ns)

        for name, cid in menu_map.items():
            if str(cid) != str(category_id) or name in menu_names:
                continue
            if is_price_filter_menu_name(name) or is_used_product_menu_name(name):
                continue
            menu_names.append(name)

        page_path = ""
        if canonical_menu and canonical_menu in entry_paths:
            page_path = entry_paths[canonical_menu]
        elif not page_path:
            uri = str(category.get("uri") or "").strip()
            if uri:
                page_path = uri if uri.endswith(".html") else f"{uri}.html"

        rows.append(
            {
                "category_id": str(category_id),
                "category_name": str(category.get("name") or canonical_menu or ""),
                "menu_name": canonical_menu,
                "page_path": page_path,
                "path_depth": _path_depth(str(category.get("path") or "")),
                "is_hang_cu": _is_hang_cu_category(category),
                "synonyms": _synonyms_for_category(str(category_id), category, menu_names),
            }
        )
    return rows


def _score_category_row(
    text_norm: str, row: dict[str, Any], *, wants_used: bool
) -> tuple[int, str, str] | None:
    is_used = bool(row["is_hang_cu"])
    if wants_used and not is_used:
        return None
    if not wants_used and is_used:
        return None

    best_syn = ""
    best_syn_score = 0
    for syn in row["synonyms"]:
        syn_n = _norm(syn)
        if len(syn_n) < 2:
            continue
        if _synonym_matches_text(syn_n, text_norm) or (
            len(syn_n) >= 6 and syn_n in text_norm
        ):
            score = 2000 + len(syn_n) * 20
            if syn_n == text_norm:
                score += 500
            if score > best_syn_score:
                best_syn_score = score
                best_syn = syn_n

    if best_syn_score <= 0:
        return None

    score = best_syn_score
    reason = f"synonym:{best_syn}"

    # Level category — path 1/2/X (depth=3) là danh mục gốc bán mới
    depth = int(row["path_depth"])
    score += max(0, 400 - depth * 80)
    if depth <= 3:
        reason += ",level:root"

    menu_name = str(row["menu_name"] or "")
    if menu_name in _CANONICAL_MENU_ALIASES:
        score += 150
        reason += f",canonical:{menu_name}"

    page_path = str(row["page_path"] or "")
    if page_path.endswith(".html") and "/" not in page_path.replace(".html", ""):
        score += 100
        reason += ",page:top"

    if is_used:
        reason += ",hang_cu"

    return score, reason, best_syn


def _is_word_aligned_subphrase(short: str, long_phrase: str) -> bool:
    if not short or short == long_phrase or short not in long_phrase:
        return False
    pattern = r"(?:^|\s)" + re.escape(short) + r"(?:\s|$)"
    return bool(re.search(pattern, long_phrase))


def _synonym_is_dominated(syn: str, text_norm: str, all_matching_syns: list[str]) -> bool:
    """
    Synonym ngắn bị lấn khi câu user chứa cụm dài hơn có cùng nghĩa
    (vd. "màn hình" trong "dán màn hình", không áp dụng khi cụm dài chỉ nằm trong tên category).
    """
    if not syn:
        return True
    for other in all_matching_syns:
        if other == syn or len(other) <= len(syn):
            continue
        if other not in text_norm:
            continue
        if _is_word_aligned_subphrase(syn, other):
            return True
    return False


def _menu_query_overlap(text_norm: str, menu_name: str) -> int:
    tokens = [t for t in _norm(menu_name).split() if len(t) >= 2]
    if not tokens:
        return 0
    query_parts = text_norm.split()
    count = 0
    for token in tokens:
        if token in query_parts:
            count += 1
            continue
        # Tránh substring ảo: "pho" trong "iphone", "man" trong "samsung"...
        if len(token) <= 4:
            if re.search(r"(?:^|\s)" + re.escape(token) + r"(?:\s|$)", text_norm):
                count += 1
        elif token in text_norm:
            count += 1
    return count


def _page_path_depth(page_path: str) -> int:
    path = (page_path or "").strip()
    if not path:
        return 0
    return path.count("/") + 1


def _child_extra_menu_tokens_in_query(
    text_norm: str, parent_menu: str, child_menu: str
) -> bool:
    parent_tokens = set(_norm(parent_menu).split())
    child_tokens = set(_norm(child_menu).split())
    extra = [t for t in child_tokens - parent_tokens if len(t) >= 2]
    if not extra:
        return False
    return all(t in text_norm for t in extra)


_BRAND_CHILD_MENUS = frozenset({
    "iPhone", "Samsung", "Xiaomi", "OPPO", "vivo", "realme", "HONOR", "Nokia",
    "Masstel", "Itel", "TECNO", "Nubia", "MacBook", "iPad",
})

_LAPTOP_QUERY_RE = re.compile(
    r"\b(?:laptop|lap top|notebook|may tinh xach tay|máy tính xách tay)\b",
    re.IGNORECASE,
)
# Menu tên chung — khi user nói laptop thì không refine sang nhánh màn hình.
_MONITOR_AMBIGUOUS_MENUS = frozenset({"Gaming", "Văn phòng", "Đồ họa"})


def refine_to_deepest_category_match(text: str, hit: CategoryMatch) -> CategoryMatch:
    """
    Trong cùng nhánh danh mục, chọn level sâu nhất mà câu user vẫn khớp
    (vd. Dán màn hình → Dán màn hình iPhone 17).
    """
    parent_path = (hit.page_path or "").strip()
    if not parent_path:
        return hit

    parent_prefix = parent_path.replace(".html", "")
    original = (text or "").strip()
    text_norm = _norm(strip_budget_phrases_for_keywords(original) or original)
    wants_used = user_wants_used_products(original)

    from cps_bot.cps.cps_menu import load_menu_category_map, load_menu_entry_paths

    menu_map = load_menu_category_map()
    entry_paths = load_menu_entry_paths()
    index_by_id = {row["category_id"]: row for row in _category_match_index()}

    def rank(menu_name: str, page_path: str, base_score: int) -> tuple[int, int, int]:
        return (
            _menu_query_overlap(text_norm, menu_name),
            _page_path_depth(page_path),
            base_score,
        )

    best_menu = hit.menu_name
    best_cid = hit.category_id
    best_path = hit.page_path
    best_name = hit.category_name
    best_reason = hit.match_reason
    parent_overlap = _menu_query_overlap(text_norm, hit.menu_name)
    best_rank = rank(hit.menu_name, hit.page_path, hit.score)

    candidates: list[tuple[str, str, str, str, int, str]] = [
        (hit.menu_name, hit.category_id, hit.page_path, hit.category_name, hit.score, hit.match_reason)
    ]

    for menu_name, cid in menu_map.items():
        if is_price_filter_menu_name(menu_name) or is_used_product_menu_name(menu_name):
            continue
        path = entry_paths.get(menu_name, "")
        if not path:
            continue
        if not (path == parent_path or path.startswith(parent_prefix + "/")):
            continue
        row = index_by_id.get(str(cid))
        if not row:
            continue
        scored = _score_category_row(text_norm, row, wants_used=wants_used)
        base_score = scored[0] if scored else 0
        reason = scored[1] if scored else f"menu:{menu_name}"
        candidates.append(
            (menu_name, str(cid), path, row["category_name"], base_score, reason)
        )

    laptop_query = bool(_LAPTOP_QUERY_RE.search(original))

    for menu_name, cid, path, cat_name, base_score, reason in candidates:
        if cid == hit.category_id:
            continue
        if laptop_query and (path or "").startswith("man-hinh/"):
            if menu_name in _MONITOR_AMBIGUOUS_MENUS:
                continue
            if hit.category_id == "380" or (hit.page_path or "").startswith("laptop"):
                continue
        if "tram-sac-du-phong" in (path or "") and not re.search(
            r"\b(?:trạm|tram)\b", original, re.I
        ):
            continue
        overlap = _menu_query_overlap(text_norm, menu_name)
        child_brand = menu_name in _BRAND_CHILD_MENUS and _child_extra_menu_tokens_in_query(
            text_norm, hit.menu_name, menu_name
        )
        if child_brand:
            overlap = max(overlap, parent_overlap + 1)
        if overlap < 2 and not _child_extra_menu_tokens_in_query(
            text_norm, hit.menu_name, menu_name
        ):
            continue
        if overlap <= parent_overlap and not _child_extra_menu_tokens_in_query(
            text_norm, hit.menu_name, menu_name
        ):
            continue
        depth = _page_path_depth(path)
        candidate_rank = (overlap, depth, base_score)
        if candidate_rank > best_rank:
            best_rank = candidate_rank
            best_menu = menu_name
            best_cid = cid
            best_path = path
            best_name = cat_name
            best_reason = reason + ",deepest"

    if best_cid == hit.category_id:
        return hit

    return CategoryMatch(
        category_id=best_cid,
        menu_name=best_menu,
        category_name=best_name,
        page_path=best_path,
        score=best_rank[2],
        match_reason=best_reason,
    )


def resolve_category_match(text: str) -> CategoryMatch | None:
    """
    Tìm category phù hợp nhất từ câu user.
    Trả CategoryMatch hoặc None.
    """
    original = (text or "").strip()
    if not original:
        return None

    scrubbed = strip_budget_phrases_for_keywords(original)
    text_norm = _norm(scrubbed or original)
    wants_used = user_wants_used_products(original)
    candidates: list[tuple[int, str, str, dict[str, Any]]] = []

    for row in _category_match_index():
        scored = _score_category_row(text_norm, row, wants_used=wants_used)
        if not scored:
            continue
        score, reason, best_syn = scored
        candidates.append((score, reason, best_syn, row))

    if not candidates:
        return None

    matching_syns = [best_syn for _, _, best_syn, _ in candidates]
    viable = [
        (score, reason, row)
        for score, reason, best_syn, row in candidates
        if not _synonym_is_dominated(best_syn, text_norm, matching_syns)
    ]
    if not viable:
        viable = [(score, reason, row) for score, reason, _, row in candidates]

    if is_power_bank_query(original):
        adjusted: list[tuple[int, str, dict[str, Any]]] = []
        for score, reason, row in viable:
            page_path = str(row.get("page_path") or "")
            if row["category_id"] == "122" or "pin-du-phong" in page_path:
                adjusted.append((score + 900, reason + ",power_bank_boost", row))
            elif row["category_id"] == "276" and "pin-du-phong" not in page_path:
                adjusted.append((score - 600, reason + ",power_bank_demote", row))
            else:
                adjusted.append((score, reason, row))
        viable = adjusted

    score, reason, row = max(viable, key=lambda item: item[0])
    return CategoryMatch(
        category_id=row["category_id"],
        menu_name=row["menu_name"] or row["category_name"],
        category_name=row["category_name"],
        page_path=row["page_path"],
        score=score,
        match_reason=reason,
    )


def match_category_from_text(text: str) -> tuple[str, str] | None:
    """API tương thích — (category_id, menu_name)."""
    hit = resolve_category_match(text)
    if not hit:
        return None
    return hit.category_id, hit.menu_name
