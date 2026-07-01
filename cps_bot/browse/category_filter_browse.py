"""
Browse sản phẩm theo category + attribute filter (thay search khi khớp bộ lọc).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from cps_bot.browse.budget_browse import parse_budget_constraint, strip_budget_phrases_for_keywords
from cps_bot.browse.category_resolver import (
    is_price_filter_menu_name,
    is_used_product_menu_name,
    match_category_from_text,
    refine_to_deepest_category_match,
    resolve_category_match,
)
from cps_bot.cps.cps_category_filter import (
    build_dynamic_filter_clause,
    get_category_data,
    load_category_attributes_map,
)
from cps_bot.cps.cps_menu import load_menu_entry_paths

_FILTER_HINT_RE = re.compile(
    r"\b("
    r"chip|cpu|ram|ssd|hdd|ổ cứng|o cung|"
    r"intel|amd|ryzen|core i\d|"
    r"android|ios|iphone|"
    r"inch|gb|tb|mah|pa|pascal|"
    r"lực hút|luc hut|sức hút|suc hut|"
    r"học tập|hoc tap|gaming|đồ họa|do hoa|"
    r"mỏng nhẹ|mong nhe|"
    r"hãng|hang|thương hiệu|thuong hieu|"
    r"dùng|dung cho|anker|baseus|ugreen"
    r")\b",
    re.IGNORECASE,
)
_POLICY_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"chính sách|chinh sach|đổi trả|doi tra|hoàn tiền|hoan tien|"
    r"bảo hành|bao hanh|gửi hãng|gui hang|không thích|khong thich|"
    r"lỗi|loi|sọc màn|soc man"
    r")\b",
    re.IGNORECASE,
)
_SPECIFIC_PRODUCT_QUERY_RE = re.compile(
    r"\b(?:"
    r"iphone\s*\d{1,2}|ip\s*\d{1,2}|"
    r"\d{1,2}\s*prm|\d{1,2}\s*pm\b|"
    r"galaxy\s*s\d{2}|s\d{2}\s*ultra|"
    r"macbook\s*air|mac\s*air|"
    r"ipad\s*(?:air|pro)?|"
    r"oppo\s*reno|find\s*x|"
    r"xiaomi\s*\d+|redmi\s*note|nubia\s*neo|"
    r"wh-\d+|ezviz|asus\s*rog|flip\s*\d|"
    r"tủ lạnh|tu lanh|tivi|"
    r"máy iPhone|may iphone"
    r")\b",
    re.IGNORECASE,
)
_CATEGORY_BROWSE_INTENT_RE = re.compile(
    r"\b(?:"
    r"danh sách|danh sach|ds\s|list\s|"
    r"tầm giá|tam gia|dưới\s+\d+|trên\s+\d+|"
    r"các mẫu|cac mau|"
    r"điện thoại android|dien thoai android|"
    r"máy tính bảng|may tinh bang|"
    r"laptop gaming|pin trâu|man hinh to"
    r")\b",
    re.IGNORECASE,
)
_ACCESSORY_BROWSE_RE = re.compile(
    r"\b(?:"
    r"miếng dán|mieng dan|ốp lưng|op lung|"
    r"dán màn hình|dan man hinh|"
    r"kinh cường lực|kinh cuong luc|"
    r"tai nghe|chuột|chuot|bàn phím|ban phim|"
    r"pin du phong|pin dự phòng|pin sac|pin sạc|sac du phong|sạc dự phòng|"
    r"\bpin\b.*\b(?:mah|anker|baseus|ugreen)\b|"
    r"balo|túi chống sốc|tui chong soc|cáp |cap "
    r")\b",
    re.IGNORECASE,
)
_FEATURE_PHRASE_HINTS: tuple[tuple[str, ...], ...] = (
    ("chong nhin trom", "chống nhìn trộm", "chong nhin trom", "anti spy", "privacy"),
    ("chong soc va dap", "chống sốc", "chong soc", "va đập", "va dap"),
    ("chong tray xuoc", "chống trầy", "chong tray", "trầy xước"),
    ("sieu mong", "siêu mỏng", "sieu mong"),
    ("bao ve mat", "bảo vệ mắt", "bao ve mat"),
)
_VARIANT_EXCLUDE_RE = re.compile(
    r"\b(pro\s*max|promax|pro\b|plus|mini|air|ultra|e\b)\b",
    re.IGNORECASE,
)
_FAMILY_PRIMARY_ATTRS: dict[str, tuple[str, ...]] = {
    "intel": ("laptop_cpu",),
    "amd": ("laptop_cpu",),
    "ryzen": ("laptop_cpu",),
    "android": ("mobile_os_filter",),
    "apple": ("laptop_cpu", "mobile_os_filter"),
}
_ATTR_MATCH_NOISE_RE = re.compile(
    r"\b(?:"
    r"cho toi|cho tôi|cho minh|cho mình|giup minh|giúp mình|"
    r"tu van|tư vấn|mot so|một số|cac mau|các mẫu|"
    r"danh sach|danh sách|tư vấn|tu van"
    r")\b",
    re.IGNORECASE,
)
# Attribute cho phép chọn nhiều giá trị cùng lúc (URL: key=val1,val2,val3)
_MULTI_SELECT_ATTR_KEYS = frozenset({"mobile_nhu_cau_sd"})
_USAGE_URI_PHRASES: tuple[tuple[str, str], ...] = (
    ("choi-game", "choi game"),
    ("choi-game", "game muot"),
    ("choi-game", "game mượt"),
    ("choi-game", "gaming"),
    ("pin-trau", "pin trau"),
    ("pin-trau", "pin khoe"),
    ("chup-anh-dep", "chup anh dep"),
    ("chup-anh-dep", "chup anh"),
    ("chup-anh-dep", "camera dep"),
    ("lam-viec-hoc-tap", "hoc online"),
    ("lam-viec-hoc-tap", "hoc tap"),
    ("lam-viec-hoc-tap", "lam viec hoc tap"),
    ("mong-nhe", "mong nhe"),
    ("mong-nhe", "nhe"),
    ("livestream", "livestream"),
    ("livestream", "stream"),
    ("dung-luong-lon", "dung luong lon"),
    ("cau-hinh-cao", "cau hinh cao"),
)

# Brand subcategory browse — iphone + budget → mobile/apple.html?price=...
_MOBILE_BRAND_BROWSE: tuple[tuple[re.Pattern[str], str, str, str, str], ...] = (
    (re.compile(r"\biphone\b", re.I), "132", "iPhone", "mobile/apple.html", "Apple"),
)

# Nhu cầu sử dụng laptop (category 380) → nhu_cau_su_dung nice_uri
# Câu tự nhiên kiểu "designer làm 3D", "laptop dựng phim" → browse laptop theo nhu cầu.
_LAPTOP_USECASE_BROWSE: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"\b3d\b|render|dựng phim|dung phim|dựng video|dung video|"
            r"đồ họa|do hoa|kỹ xảo|ky xao|"
            r"designer|thiết kế đồ họa|thiet ke do hoa|"
            r"chỉnh sửa video|chinh sua video|edit video|dựng hình|dung hinh",
            re.IGNORECASE,
        ),
        "do-hoa-ky-thuat",
        "Đồ họa - Kỹ thuật",
    ),
    (
        re.compile(r"sáng tạo nội dung|sang tao noi dung|content creator", re.IGNORECASE),
        "laptop-sang-tao-noi-dung",
        "Laptop sáng tạo nội dung",
    ),
    (
        re.compile(r"\bgaming\b|chơi game|choi game|game nặng|game nang", re.IGNORECASE),
        "gaming",
        "Gaming",
    ),
)
# Dấu hiệu câu đang nói về laptop/PC (tránh nhầm điện thoại/máy ảnh/màn hình)
_LAPTOP_DEVICE_HINT_RE = re.compile(
    r"\b(?:laptop|lap top|máy tính|may tinh|máy trạm|may tram|"
    r"workstation|pc|máy để bàn|may de ban|notebook|"
    r"máy làm|may lam|máy chạy|may chay|designer|render)\b",
    re.IGNORECASE,
)
# Danh mục khác đã rõ → không ép về laptop
_NON_LAPTOP_DEVICE_RE = re.compile(
    r"\b(?:điện thoại|dien thoai|smartphone|máy ảnh|may anh|camera|"
    r"màn hình|man hinh|monitor|tivi|tv|đồng hồ|dong ho|tablet|"
    r"máy tính bảng|may tinh bang|tai nghe|loa\b|máy giặt|may giat|"
    r"máy lạnh|may lanh|tủ lạnh|tu lanh)\b",
    re.IGNORECASE,
)

_SCREEN_SIZE_ATTR_KEY = "screen_size"


@dataclass
class CategoryFilterRequest:
    category_id: str
    menu_name: str
    category_name: str
    dynamic_filter: str
    matched_filters: list[dict[str, Any]] = field(default_factory=list)
    is_subcategory_menu: bool = False
    page_path: str = ""
    match_reason: str = ""


def resolve_category_page_path(category_id: str, menu_name: str) -> str:
    """Trang category CPS — vd. mobile.html."""
    entry_paths = load_menu_entry_paths()
    if menu_name in entry_paths:
        return entry_paths[menu_name]

    cat = get_category_data(category_id)
    uri = str((cat or {}).get("uri") or "").strip()
    if uri:
        return uri if uri.endswith(".html") else f"{uri}.html"

    from cps_bot.cps.cps_menu import load_menu_category_map

    menu_map = load_menu_category_map()
    for name, cid in menu_map.items():
        if str(cid) == str(category_id) and name in entry_paths:
            return entry_paths[name]
    return ""


def build_category_filter_url(
    req: CategoryFilterRequest,
    filter_price: tuple[int, int] | None = None,
) -> str:
    """
    URL filter kiểu trang CPS — vd.
    mobile.html?mobile_os_filter=android&price=0-10000000
    """
    base = req.page_path or resolve_category_page_path(req.category_id, req.menu_name)
    if not base:
        base = "mobile.html"

    brand_subpath = ""
    other_params: list[str] = []
    for item in req.matched_filters:
        key = str(item.get("key") or "")
        uris = item.get("nice_uris") or []
        if key == "phone_accessory_brands" and uris and "pin-du-phong" in base:
            brand_subpath = uris[0]
            continue
        if key and uris:
            other_params.append(f"{key}={','.join(uris)}")
    if brand_subpath and base.endswith("pin-du-phong.html"):
        base = base.replace(".html", f"/{brand_subpath}.html")

    params: list[str] = list(other_params)
    if filter_price:
        params.append(f"price={filter_price[0]}-{filter_price[1]}")
    if not params:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{'&'.join(params)}"


def _fold_vn(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def _norm_filter_text(text: str) -> str:
    value = _fold_vn(text)
    value = re.sub(r"(\d{4,5})mah\b", r"\1 mah", value, flags=re.IGNORECASE)
    # 10.000 pa / 10000Pa → 10000 pa
    value = re.sub(
        r"(\d{1,2})\.(\d{3})\s*pa\b",
        lambda m: f"{m.group(1)}{m.group(2)} pa",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(\d+)\s*pa\b", r"\1 pa", value, flags=re.IGNORECASE)
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _usage_uris_from_text(text_norm: str) -> set[str]:
    folded = _fold_vn(text_norm)
    uris: set[str] = set()
    for uri, phrase in _USAGE_URI_PHRASES:
        if phrase in folded:
            uris.add(uri)
    return uris


def _extract_feature_phrases(text: str) -> list[str]:
    phrases: list[str] = []
    norm = _norm_filter_text(text)
    for group in _FEATURE_PHRASE_HINTS:
        for alias in group:
            alias_norm = _norm_filter_text(alias)
            if alias_norm and alias_norm in norm:
                phrases.append(group[0])
                break
    return phrases


# Token ngắn nhưng có nghĩa (3d, 4k, 5g…) — không bị loại như stopword
_SHORT_SIGNIFICANT_TOKENS = frozenset({"3d", "2d", "4k", "8k", "5g", "4g", "ai"})


def _meaningful_query_tokens(text_norm: str) -> set[str]:
    stop = {
        "cho", "toi", "mot", "so", "van", "tu", "cac", "mau", "danh", "sach",
        "xin", "giup", "minh", "ban", "em", "anh", "chi", "co", "khong",
    }
    return {
        t
        for t in text_norm.split()
        if (len(t) >= 3 or t in _SHORT_SIGNIFICANT_TOKENS) and t not in stop
    }


def _score_attribute_option(text_norm: str, option: dict[str, Any], *, feature_phrases: list[str]) -> int:
    label_norm = str(option.get("label_norm") or _norm_filter_text(option.get("label") or ""))
    nice_uri = str(option.get("nice_uri") or "")
    uri_norm = nice_uri.replace("-", " ")

    score = 0
    has_evidence = False
    if label_norm and label_norm in text_norm:
        score += 220 + len(label_norm) * 4
        has_evidence = True
    if uri_norm and uri_norm in text_norm:
        score += 180
        has_evidence = True

    for phrase in feature_phrases:
        if phrase in label_norm or phrase in uri_norm.replace("-", " "):
            score += 200
            has_evidence = True

    opt_tokens = set(option.get("tokens") or [])
    query_tokens = _meaningful_query_tokens(text_norm)
    overlap = opt_tokens & query_tokens
    if overlap:
        score += len(overlap) * 12
        has_evidence = True

    for token in query_tokens:
        if len(token) < 4 and token not in ("anker", "mah") and token not in _SHORT_SIGNIFICANT_TOKENS:
            continue
        if token in uri_norm or token in label_norm:
            score += 70
            has_evidence = True

    # Tránh khớp Pro/Max/Plus khi user không nhắc biến thể
    if not _VARIANT_EXCLUDE_RE.search(text_norm):
        for variant in ("pro", "max", "plus", "mini", "air", "ultra"):
            if variant in label_norm.split() or variant in uri_norm.split("-"):
                score -= 55

    # Không có bằng chứng thật (chỉ trùng độ dài) → không chọn filter
    if not has_evidence:
        return 0

    # Độ dài label chỉ dùng làm tiebreak giữa các option ĐÃ match thật
    if label_norm:
        score += len(label_norm)

    return score


def _option_matches_tokens(option: dict[str, Any], text_tokens: set[str]) -> bool:
    opt_tokens = set(option.get("tokens") or [])
    overlap = text_tokens & opt_tokens
    if not overlap:
        return False
    return any(len(t) >= 3 or re.fullmatch(r"i\d+", t) for t in overlap)


def match_attribute_filters(
    text: str,
    category_data: dict[str, Any],
    *,
    strip_menu_name: str = "",
    skip_screen_size: bool = False,
) -> list[tuple[str, list[str], list[str]]]:
    """
    Trích attribute filter từ câu hỏi — chọn option khớp nhất (hoặc cả nhóm nếu chỉ nêu hãng/chip).
    """
    scrubbed = text
    if strip_menu_name:
        scrubbed = re.sub(re.escape(strip_menu_name), " ", scrubbed, flags=re.I)
    scrubbed = _ATTR_MATCH_NOISE_RE.sub(" ", scrubbed)
    text_norm = _norm_filter_text(scrubbed)
    feature_phrases = _extract_feature_phrases(scrubbed)
    family_tokens = [t for t in ("intel", "amd", "ryzen", "android", "apple") if t in text_norm]

    matched: list[tuple[str, list[str], list[str]]] = []
    for attr in category_data.get("attributes") or []:
        key = str(attr.get("key") or "")
        if not key:
            continue
        if skip_screen_size and key == _SCREEN_SIZE_ATTR_KEY:
            continue

        scored: list[tuple[int, dict[str, Any]]] = []
        for opt in attr.get("options") or []:
            score = _score_attribute_option(
                text_norm,
                opt,
                feature_phrases=feature_phrases,
            )
            if score > 0:
                scored.append((score, opt))

        if not scored:
            continue

        best_score = max(s for s, _ in scored)
        if family_tokens:
            primary_keys = _FAMILY_PRIMARY_ATTRS.get(family_tokens[0], ())
            if primary_keys and key not in primary_keys and best_score < 120:
                continue

        if best_score < 35:
            continue

        if key in _MULTI_SELECT_ATTR_KEYS:
            usage_hits = _usage_uris_from_text(text_norm)
            option_by_uri = {
                str(o.get("nice_uri") or ""): o for _, o in scored
            }
            selected = [
                option_by_uri[uri]
                for uri in usage_hits
                if uri in option_by_uri
            ]
            if not selected:
                selected = [
                    opt for score, opt in scored if score >= 80
                ]
            if not selected:
                selected = [
                    opt for score, opt in scored if score >= best_score - 5
                ]
        elif family_tokens:
            family = family_tokens[0]
            family_opts = [
                opt
                for score, opt in scored
                if score >= 35 and family in str(opt.get("nice_uri") or "")
            ]
            if len(family_opts) >= 2:
                selected = family_opts
            else:
                selected = [
                    opt for score, opt in scored if score >= best_score - 5
                ]
        else:
            selected = [opt for score, opt in scored if score >= best_score - 5]

        nice_uris = list(dict.fromkeys(str(o["nice_uri"]) for o in selected))
        labels = [str(o["label"]) for o in selected]
        matched.append((key, nice_uris, labels))

    return matched


def _prune_redundant_attribute_matches(
    page_path: str,
    matches: list[tuple[str, list[str], list[str]]],
) -> list[tuple[str, list[str], list[str]]]:
    """Bỏ filter trùng với category page đã chỉ định model/loại."""
    path_folded = (page_path or "").lower().replace("-", "").replace("/", "")
    pruned: list[tuple[str, list[str], list[str]]] = []

    for key, uris, labels in matches:
        if key in ("op_dan_dong_iphone", "for_product", "op_dan_dong_samsung"):
            uri = (uris[0] if uris else "").replace("-", "")
            if uri and uri in path_folded:
                continue
        pruned.append((key, uris, labels))

    keys = {item[0] for item in pruned}
    if "tinh_nang_dac_biet" in keys:
        pruned = [item for item in pruned if item[0] != "dan_man_hinh_loai"]
    if "mobile_nhu_cau_sd" in keys:
        usage_uris = set()
        for key, uris, _labels in pruned:
            if key == "mobile_nhu_cau_sd":
                usage_uris.update(uris)
        if "chup-anh-dep" in usage_uris:
            pruned = [
                item for item in pruned if item[0] != "mobile_camera_feature"
            ]

    # Lực hút (Pa) rõ ràng → bỏ tính năng chỉ khớp nhầm qua "sức hút"
    if "robot_luc_hut_filter" in keys:
        pruned = [
            item for item in pruned if item[0] != "robot_hut_bui_tinh_nang"
        ]
        # Category đã là máy hút bụi → không cần thêm filter chức năng "hút bụi"
        pruned = [
            item
            for item in pruned
            if not (item[0] == "robot_chuc_nang" and item[1] == ["hut-bui"])
        ]

    return pruned


def _extract_suction_power_filter(text: str) -> tuple[str, list[str], list[str]] | None:
    """
    Lực hút Pa → robot_luc_hut_filter nice_uri.
    Vd: "lực hút trên 10000 pa" → tren-10000pa
    """
    norm = _norm_filter_text(text)
    if not re.search(r"\bpa\b", norm):
        return None

    def _pick_uri(pa: int, *, over: bool, under: bool) -> tuple[str, str] | None:
        if over or (not under and pa >= 10000):
            if pa >= 10000:
                return "tren-10000pa", "Trên 10000pa"
        if under:
            if pa <= 2000:
                return "tu-2001-5000pa", "Từ 2001 - 5000pa"
            if pa <= 5000:
                return "tu-2001-5000pa", "Từ 2001 - 5000pa"
            if pa <= 10000:
                return "tu-5001-10000pa", "Từ 5001 - 10000pa"
        if over:
            if pa >= 5001:
                return "tu-5001-10000pa", "Từ 5001 - 10000pa"
            if pa >= 2001:
                return "tu-2001-5000pa", "Từ 2001 - 5000pa"
        return None

    over_m = re.search(r"(?:tren|>|>=)\s*(\d+)\s*pa\b", norm)
    if over_m:
        hit = _pick_uri(int(over_m.group(1)), over=True, under=False)
        if hit:
            uri, label = hit
            return ("robot_luc_hut_filter", [uri], [label])

    under_m = re.search(r"(?:duoi|<|<=)\s*(\d+)\s*pa\b", norm)
    if under_m:
        hit = _pick_uri(int(under_m.group(1)), over=False, under=True)
        if hit:
            uri, label = hit
            return ("robot_luc_hut_filter", [uri], [label])

    return None


def _resolve_brand_subcategory_browse(text: str) -> CategoryFilterRequest | None:
    """
    Browse theo hãng + ngân sách — vd. điện thoại iphone dưới 20 triệu
    → mobile/apple.html?price=0-20000000
    """
    original = (text or "").strip()
    if not original:
        return None
    if not parse_budget_constraint(original):
        return None
    if (
        _SPECIFIC_PRODUCT_QUERY_RE.search(original)
        and not _CATEGORY_BROWSE_INTENT_RE.search(original)
    ):
        return None

    for pattern, category_id, menu_name, page_path, category_name in _MOBILE_BRAND_BROWSE:
        if not pattern.search(original):
            continue
        return CategoryFilterRequest(
            category_id=category_id,
            menu_name=menu_name,
            category_name=category_name,
            dynamic_filter="",
            matched_filters=[],
            is_subcategory_menu=True,
            page_path=page_path,
            match_reason=f"brand_subcategory:{menu_name}",
        )
    return None


def _laptop_usecase_matches(text: str) -> list[tuple[str, list[str], list[str]]]:
    """Trích nhu_cau_su_dung từ câu (designer/3D/gaming…) — [] nếu không có."""
    original = (text or "").strip()
    matched: list[tuple[str, list[str], list[str]]] = []
    seen_uris: set[str] = set()
    for pattern, nice_uri, label in _LAPTOP_USECASE_BROWSE:
        if pattern.search(original) and nice_uri not in seen_uris:
            matched.append(("nhu_cau_su_dung", [nice_uri], [label]))
            seen_uris.add(nice_uri)
    return matched


def _resolve_laptop_usecase_browse(text: str) -> CategoryFilterRequest | None:
    """
    Câu tả nhu cầu (designer/3D/dựng phim…) → browse laptop theo nhu_cau_su_dung.
    Chỉ kích hoạt khi có ngữ cảnh laptop/PC và không nói rõ thiết bị khác.
    """
    original = (text or "").strip()
    if not original:
        return None
    if _NON_LAPTOP_DEVICE_RE.search(original):
        return None
    if not _LAPTOP_DEVICE_HINT_RE.search(original):
        return None

    matched = _laptop_usecase_matches(original)
    if not matched:
        return None

    category_data = get_category_data("380")
    if not category_data:
        return None

    filter_pairs = [(key, uris) for key, uris, _labels in matched]
    dynamic_filter = build_dynamic_filter_clause(filter_pairs)
    matched_meta = [
        {"key": key, "nice_uris": uris, "labels": labels}
        for key, uris, labels in matched
    ]
    return CategoryFilterRequest(
        category_id="380",
        menu_name="Laptop",
        category_name=str(category_data.get("name") or "Laptop"),
        dynamic_filter=dynamic_filter,
        matched_filters=matched_meta,
        is_subcategory_menu=False,
        page_path="laptop.html",
        match_reason="laptop_usecase",
    )


def resolve_category_filter_request(text: str) -> CategoryFilterRequest | None:
    """
    Phân tích câu hỏi → category + dynamic filter nếu có thể browse qua GraphQL filter.
    """
    original = (text or "").strip()
    if not original:
        return None

    brand_hit = _resolve_brand_subcategory_browse(original)
    if brand_hit:
        return brand_hit

    cat_hit = resolve_category_match(original)
    if not cat_hit:
        return _resolve_laptop_usecase_browse(original)

    cat_hit = refine_to_deepest_category_match(original, cat_hit)

    category_id = cat_hit.category_id
    menu_name = cat_hit.menu_name
    category_data = get_category_data(category_id)
    if not category_data:
        attr_map = load_category_attributes_map()
        category_data = (attr_map.get("categories") or {}).get(category_id)
    if not category_data:
        return None

    page_path = cat_hit.page_path or resolve_category_page_path(category_id, menu_name)
    filter_price = resolve_filter_price(original)
    attr_scrubbed = strip_budget_phrases_for_keywords(original)
    has_budget = parse_budget_constraint(original) is not None
    attr_matches = match_attribute_filters(
        attr_scrubbed,
        category_data,
        strip_menu_name=menu_name,
        skip_screen_size=has_budget,
    )
    suction_hit = _extract_suction_power_filter(original)
    if suction_hit:
        key, uris, labels = suction_hit
        attr_matches = [
            (key, uris, labels),
            *[
                m for m in attr_matches
                if m[0] not in (key, "robot_hut_bui_tinh_nang")
            ],
        ]
    attr_matches = _prune_redundant_attribute_matches(page_path, attr_matches)

    # Laptop: câu tả nhu cầu (designer/3D…) khớp nhu_cau_su_dung dù token không trùng label
    if category_id == "380" and not any(k == "nhu_cau_su_dung" for k, _, _ in attr_matches):
        usecase = _laptop_usecase_matches(original)
        if usecase:
            attr_matches = usecase + attr_matches
    is_subcategory = (
        len(menu_name.split()) >= 2
        and not is_price_filter_menu_name(menu_name)
        and not is_used_product_menu_name(menu_name)
    )

    if not attr_matches and not is_subcategory and not filter_price:
        return None

    if not attr_matches and is_subcategory:
        return CategoryFilterRequest(
            category_id=category_id,
            menu_name=menu_name,
            category_name=str(category_data.get("name") or menu_name),
            dynamic_filter="",
            matched_filters=[],
            is_subcategory_menu=True,
            page_path=page_path,
            match_reason=cat_hit.match_reason,
        )

    if not attr_matches and filter_price:
        return CategoryFilterRequest(
            category_id=category_id,
            menu_name=menu_name,
            category_name=str(category_data.get("name") or menu_name),
            dynamic_filter="",
            matched_filters=[],
            is_subcategory_menu=False,
            page_path=page_path,
            match_reason=cat_hit.match_reason,
        )

    filter_pairs = [(key, uris) for key, uris, _labels in attr_matches]
    dynamic_filter = build_dynamic_filter_clause(filter_pairs)
    if not dynamic_filter and not is_subcategory and not filter_price:
        return None

    matched_meta = [
        {
            "key": key,
            "nice_uris": uris,
            "labels": labels,
        }
        for key, uris, labels in attr_matches
    ]

    return CategoryFilterRequest(
        category_id=category_id,
        menu_name=menu_name,
        category_name=str(category_data.get("name") or menu_name),
        dynamic_filter=dynamic_filter,
        matched_filters=matched_meta,
        is_subcategory_menu=is_subcategory and not attr_matches,
        page_path=page_path,
        match_reason=cat_hit.match_reason,
    )


def is_category_filter_browse_query(text: str) -> bool:
    """True khi nên thử browse category + attribute filter thay vì search."""
    value = text or ""
    if _POLICY_CONTEXT_RE.search(value):
        return False
    if (
        _SPECIFIC_PRODUCT_QUERY_RE.search(value)
        and not _CATEGORY_BROWSE_INTENT_RE.search(value)
        and not _ACCESSORY_BROWSE_RE.search(value)
    ):
        return False
    req = resolve_category_filter_request(value)
    if not req:
        return False
    if req.dynamic_filter:
        return True
    if resolve_filter_price(value):
        return True
    if req.is_subcategory_menu:
        # User gọi đúng tên subcategory (vd "đồng hồ thể thao") → hiện danh sách.
        menu_norm = _norm_filter_text(req.menu_name)
        if menu_norm and menu_norm in _norm_filter_text(value):
            return True
        if not _CATEGORY_BROWSE_INTENT_RE.search(value) and not _FILTER_HINT_RE.search(value):
            return False
        return True
    return bool(_FILTER_HINT_RE.search(value))


def describe_category_filter(req: CategoryFilterRequest) -> str:
    parts = [req.menu_name or req.category_name or ""]
    if req.category_name and req.category_name.lower() != (req.menu_name or "").lower():
        parts.append(req.category_name)
    for item in req.matched_filters:
        labels = item.get("labels") or []
        if labels:
            parts.append(", ".join(labels[:3]))
    return " — ".join(p for p in parts if p)


def resolve_filter_price(text: str) -> tuple[int, int] | None:
    """Gắn filter_price static nếu câu có ngân sách."""
    constraint = parse_budget_constraint(text)
    if not constraint:
        return None
    if constraint.min_vnd is not None and constraint.max_vnd is not None:
        return int(constraint.min_vnd), int(constraint.max_vnd)
    if constraint.max_vnd is not None:
        return 0, int(constraint.max_vnd)
    if constraint.min_vnd is not None:
        return int(constraint.min_vnd), 999_999_999
    return None
