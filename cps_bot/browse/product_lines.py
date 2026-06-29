"""
Nhận diện dòng / danh mục sản phẩm — tránh pin nhầm ngữ cảnh khi khách đổi SP.

Ví dụ: MacBook Neo → Mac mini, iPhone → Galaxy, iPhone → iPad, iPhone → tai nghe.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Cụm dài / cụ thể trước — mỗi câu có thể khớp nhiều line (vd. galaxy + galaxy_s)
_PRODUCT_LINE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # Apple — Mac
    (re.compile(r"\bmacbook\s+neo\b", re.I), "macbook_neo"),
    (re.compile(r"\bmacbook\s+air\b", re.I), "macbook_air"),
    (re.compile(r"\bmacbook\s+pro\b", re.I), "macbook_pro"),
    (re.compile(r"\bmacbook\b", re.I), "macbook"),
    (re.compile(r"\bmac\s+mini\b", re.I), "mac_mini"),
    (re.compile(r"\bmac\s+studio\b", re.I), "mac_studio"),
    (re.compile(r"\bmac\s+pro\b", re.I), "mac_pro"),
    (re.compile(r"\bimac\b", re.I), "imac"),
    # Apple — mobile / wear / audio
    (re.compile(r"\biphone\s+air\b", re.I), "iphone_air"),
    (re.compile(r"\biphone\s+\d{1,2}e?\b", re.I), "iphone"),
    (re.compile(r"\biphone\b", re.I), "iphone"),
    (re.compile(r"\bipad\s+pro\b", re.I), "ipad_pro"),
    (re.compile(r"\bipad\s+air\b", re.I), "ipad_air"),
    (re.compile(r"\bipad\s+mini\b", re.I), "ipad_mini"),
    (re.compile(r"\bipad\b", re.I), "ipad"),
    (re.compile(r"\bairpods\s+pro\b", re.I), "airpods_pro"),
    (re.compile(r"\bairpods\s+max\b", re.I), "airpods_max"),
    (re.compile(r"\bairpods\b", re.I), "airpods"),
    (re.compile(r"\bapple\s+watch\b", re.I), "apple_watch"),
    # Samsung
    (re.compile(r"\bgalaxy\s+z\s+fold\b|\bz\s+fold\b|\bgalaxy\s+fold\b", re.I), "galaxy_fold"),
    (re.compile(r"\bgalaxy\s+z\s+flip\b|\bz\s+flip\b|\bgalaxy\s+flip\b", re.I), "galaxy_flip"),
    (re.compile(r"\bgalaxy\s+z\b", re.I), "galaxy_z"),
    (re.compile(r"\bgalaxy\s+s\b|\bgalaxy\s+s\d", re.I), "galaxy_s"),
    (re.compile(r"\bgalaxy\s+a\b|\bgalaxy\s+a\d", re.I), "galaxy_a"),
    (re.compile(r"\bgalaxy\s+tab\b", re.I), "galaxy_tab"),
    (re.compile(r"\bgalaxy\s+watch\b", re.I), "galaxy_watch"),
    (re.compile(r"\bgalaxy\s+buds\b", re.I), "galaxy_buds"),
    (re.compile(r"\bgalaxy\b", re.I), "galaxy"),
    (re.compile(r"\bsamsung\b", re.I), "samsung"),
    # Chinese phone brands
    (re.compile(r"\bredmi\s+note\b", re.I), "redmi_note"),
    (re.compile(r"\bredmi\b", re.I), "redmi"),
    (re.compile(r"\bpoco\b", re.I), "poco"),
    (re.compile(r"\bxiaomi\b", re.I), "xiaomi"),
    (re.compile(r"\boppo\b", re.I), "oppo"),
    (re.compile(r"\bvivo\b", re.I), "vivo"),
    (re.compile(r"\brealme\b", re.I), "realme"),
    (re.compile(r"\bnokia\b", re.I), "nokia"),
    (re.compile(r"\bhuawei\b", re.I), "honor_huawei"),
    (re.compile(r"\bhonor\b", re.I), "honor_huawei"),
    (re.compile(r"\btecno\b", re.I), "tecno"),
    (re.compile(r"\binfinix\b", re.I), "infinix"),
    # Laptop / PC brands (dòng chính)
    (re.compile(r"\basus\s+rog\b|\brog\s+(?:ally|phone|flow)\b", re.I), "asus_rog"),
    (re.compile(r"\basus\s+tuf\b|\btuf\s+gaming\b", re.I), "asus_tuf"),
    (re.compile(r"\basus\s+vivobook\b|\bvivobook\b", re.I), "asus_vivobook"),
    (re.compile(r"\basus\s+zenbook\b|\bzenbook\b", re.I), "asus_zenbook"),
    (re.compile(r"\basus\b", re.I), "asus_laptop"),
    (re.compile(r"\bdell\s+xps\b|\bxps\s+\d", re.I), "dell_xps"),
    (re.compile(r"\bdell\s+inspiron\b|\binspiron\b", re.I), "dell_inspiron"),
    (re.compile(r"\bdell\s+latitude\b|\blatitude\b", re.I), "dell_latitude"),
    (re.compile(r"\bdell\b", re.I), "dell_laptop"),
    (re.compile(r"\blenovo\s+thinkpad\b|\bthinkpad\b", re.I), "lenovo_thinkpad"),
    (re.compile(r"\blenovo\s+ideapad\b|\bideapad\b", re.I), "lenovo_ideapad"),
    (re.compile(r"\blenovo\s+legion\b|\blegion\b", re.I), "lenovo_legion"),
    (re.compile(r"\blenovo\b", re.I), "lenovo_laptop"),
    (re.compile(r"\bhp\s+pavilion\b|\bpavilion\b", re.I), "hp_pavilion"),
    (re.compile(r"\bhp\s+elitebook\b|\belitebook\b", re.I), "hp_elitebook"),
    (re.compile(r"\bhp\b|\bhewlett\b", re.I), "hp_laptop"),
    (re.compile(r"\bacer\s+nitro\b|\bnitro\s+\d", re.I), "acer_nitro"),
    (re.compile(r"\bacer\s+aspire\b|\baspire\b", re.I), "acer_aspire"),
    (re.compile(r"\bacer\b", re.I), "acer_laptop"),
    (re.compile(r"\bmsi\b", re.I), "msi_laptop"),
    (re.compile(r"\bsurface\b", re.I), "microsoft_surface"),
    # Console / TV / monitor
    (re.compile(r"\bplaystation\s*5\b|\bps5\b", re.I), "playstation"),
    (re.compile(r"\bplaystation\s*4\b|\bps4\b", re.I), "playstation"),
    (re.compile(r"\bxbox\b", re.I), "xbox"),
    (re.compile(r"\bnintendo\s+switch\b|\bswitch\b", re.I), "nintendo_switch"),
    (re.compile(r"\boled\s+tv\b|\btivi\b|\btv\b", re.I), "tv"),
    (re.compile(r"\bm[aà]n h[iì]nh\b|\bmonitor\b", re.I), "monitor"),
    # Gia dụng / phụ kiện (danh mục riêng)
    (re.compile(r"\bn[ồo]i chi[êe]n\b|\bnckd\b", re.I), "appliance_airfryer"),
    (re.compile(r"\bm[áa]y l[ạa]nh\b", re.I), "appliance_ac"),
    (re.compile(r"\bt[ủu] l[ạa]nh\b", re.I), "appliance_fridge"),
    (re.compile(r"\bm[áa]y gi[ạa]t\b", re.I), "appliance_washer"),
    (re.compile(r"\brobot\s+h[úu]t\b|\bm[áa]y h[úu]t\b", re.I), "appliance_vacuum"),
)

# Nhóm tương thích — cùng nhóm không conflict (iphone + iphone_air vẫn khác line → conflict)
# Dùng để gom conflict: chỉ conflict khi không cùng line VÀ không cùng compatible group... 
# Actually we want iphone vs iphone_air to conflict. Keep strict line conflict.

# Danh mục rộng — chỉ dùng khi câu có vẻ tra cứu SP mới (không phải hỏi kèm/tặng)
_CATEGORY_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bpin dự phòng\b|\bpin du phong\b|\bsac du phong\b|\bpower bank\b", re.I), "cat_powerbank"),
    (re.compile(r"\btai nghe\b|\bearbuds\b|\btws\b|\bheadphone\b", re.I), "cat_headphone"),
    (re.compile(r"\bloa bluetooth\b|\bloa di dong\b|\bloa di động\b", re.I), "cat_speaker"),
    (re.compile(r"\bsmartwatch\b|\bđồng hồ thông minh\b|\bdong ho thong minh\b", re.I), "cat_watch"),
    (re.compile(r"\blaptop\b|\bmay tinh xach tay\b|\bmáy tính xách tay\b", re.I), "cat_laptop"),
    (re.compile(r"\btablet\b|\bmay tinh bang\b|\bmáy tính bảng\b", re.I), "cat_tablet"),
    (re.compile(r"\bdien thoai\b|\bđiện thoại\b|\bsmartphone\b", re.I), "cat_phone"),
    (re.compile(r"\bchuot\b|\bchuột\b|\bban phim\b|\bbàn phím\b", re.I), "cat_peripheral"),
    (re.compile(r"\brouter\b|\bmodem\b|\bwifi\b", re.I), "cat_network"),
    (re.compile(r"\bcamera\b|\bmay anh\b|\bmáy ảnh\b", re.I), "cat_camera"),
)

# Line → danh mục (để bổ sung category khi đã có line cụ thể)
_LINE_TO_CATEGORY: dict[str, str] = {
    "macbook_neo": "cat_laptop_apple",
    "macbook_air": "cat_laptop_apple",
    "macbook_pro": "cat_laptop_apple",
    "macbook": "cat_laptop_apple",
    "mac_mini": "cat_desktop_apple",
    "mac_studio": "cat_desktop_apple",
    "mac_pro": "cat_desktop_apple",
    "imac": "cat_desktop_apple",
    "iphone": "cat_phone",
    "iphone_air": "cat_phone",
    "ipad": "cat_tablet",
    "ipad_pro": "cat_tablet",
    "ipad_air": "cat_tablet",
    "ipad_mini": "cat_tablet",
    "airpods": "cat_headphone",
    "airpods_pro": "cat_headphone",
    "airpods_max": "cat_headphone",
    "apple_watch": "cat_watch",
    "galaxy_s": "cat_phone",
    "galaxy_a": "cat_phone",
    "galaxy_z": "cat_phone",
    "galaxy_fold": "cat_phone",
    "galaxy_flip": "cat_phone",
    "galaxy_tab": "cat_tablet",
    "galaxy_watch": "cat_watch",
    "galaxy_buds": "cat_headphone",
    "galaxy": "cat_phone",
    "samsung": "cat_phone",
    "redmi": "cat_phone",
    "redmi_note": "cat_phone",
    "poco": "cat_phone",
    "xiaomi": "cat_phone",
    "oppo": "cat_phone",
    "vivo": "cat_phone",
    "realme": "cat_phone",
    "nokia": "cat_phone",
    "honor_huawei": "cat_phone",
    "tecno": "cat_phone",
    "infinix": "cat_phone",
    "asus_rog": "cat_laptop",
    "asus_tuf": "cat_laptop",
    "asus_vivobook": "cat_laptop",
    "asus_zenbook": "cat_laptop",
    "asus_laptop": "cat_laptop",
    "dell_xps": "cat_laptop",
    "dell_inspiron": "cat_laptop",
    "dell_latitude": "cat_laptop",
    "dell_laptop": "cat_laptop",
    "lenovo_thinkpad": "cat_laptop",
    "lenovo_ideapad": "cat_laptop",
    "lenovo_legion": "cat_laptop",
    "lenovo_laptop": "cat_laptop",
    "hp_pavilion": "cat_laptop",
    "hp_elitebook": "cat_laptop",
    "hp_laptop": "cat_laptop",
    "acer_nitro": "cat_laptop",
    "acer_aspire": "cat_laptop",
    "acer_laptop": "cat_laptop",
    "msi_laptop": "cat_laptop",
    "microsoft_surface": "cat_laptop",
    "playstation": "cat_console",
    "xbox": "cat_console",
    "nintendo_switch": "cat_console",
    "tv": "cat_tv",
    "monitor": "cat_monitor",
    "appliance_airfryer": "cat_appliance",
    "appliance_ac": "cat_appliance",
    "appliance_fridge": "cat_appliance",
    "appliance_washer": "cat_appliance",
    "appliance_vacuum": "cat_appliance",
}

_INBOX_ACCESSORY_RE = re.compile(
    r"\b(?:"
    r"c[oó]\s*k[eè]m|k[eè]m\s*theo|t[ặa]ng\s*k[eè]m|"
    r"trong\s*h[ộo]p|in\s*box|h[àa]ng\s*t[ặa]ng"
    r")\b",
    re.I,
)

_PRODUCT_LOOKUP_RE = re.compile(
    r"(?:"
    r"^(?:gi[aá]|check|t[iì]m|so\s+s[aá]nh|mua|t[ưu]\s*v[aấ]n)\s+"
    r"|(?:gi[aá]|bao\s+nhi[eê]u)\s*$"
    r"|(?:gi[aá]|check)\s+(?:c[ủu]a\s+)?(?:con|chiếc|sp|sản\s+phẩm)?"
    r")",
    re.I,
)

# Line cha — bỏ khỏi so conflict khi đã có line con cụ thể
_GENERIC_PARENT_LINES: dict[str, frozenset[str]] = {
    "macbook": frozenset({"macbook_neo", "macbook_air", "macbook_pro"}),
    "galaxy": frozenset({"galaxy_s", "galaxy_a", "galaxy_z", "galaxy_fold", "galaxy_flip", "galaxy_tab", "galaxy_watch", "galaxy_buds"}),
    "iphone": frozenset({"iphone_air"}),
    "ipad": frozenset({"ipad_pro", "ipad_air", "ipad_mini"}),
    "airpods": frozenset({"airpods_pro", "airpods_max"}),
    "asus_laptop": frozenset({"asus_rog", "asus_tuf", "asus_vivobook", "asus_zenbook"}),
    "dell_laptop": frozenset({"dell_xps", "dell_inspiron", "dell_latitude"}),
    "lenovo_laptop": frozenset({"lenovo_thinkpad", "lenovo_ideapad", "lenovo_legion"}),
    "hp_laptop": frozenset({"hp_pavilion", "hp_elitebook"}),
    "acer_laptop": frozenset({"acer_nitro", "acer_aspire"}),
    "redmi": frozenset({"redmi_note"}),
    "honor_huawei": frozenset(),
    "samsung": frozenset({"galaxy_s", "galaxy_a", "galaxy_z", "galaxy_fold", "galaxy_flip", "galaxy_tab", "galaxy_watch", "galaxy_buds", "galaxy"}),
}


def _distinct_lines(lines: frozenset[str]) -> frozenset[str]:
    """Bỏ line cha generic khi đã có line con (macbook vs macbook_neo)."""
    if not lines:
        return lines
    result = set(lines)
    for parent, children in _GENERIC_PARENT_LINES.items():
        if parent in result and (result & children):
            result.discard(parent)
    return frozenset(result)


_PRODUCT_LINE_HINTS = frozenset({
    "mac mini", "mac studio", "macbook neo", "macbook air", "macbook pro", "macbook", "imac",
    "iphone", "ipad", "airpods", "apple watch",
    "galaxy", "samsung", "redmi", "poco", "xiaomi", "oppo", "vivo", "realme", "nokia", "honor", "huawei",
    "asus", "dell", "lenovo", "hp", "acer", "msi", "surface", "thinkpad", "vivobook", "zenbook", "rog",
    "playstation", "ps5", "xbox", "nintendo", "switch",
    "pin dự phòng", "pin du phong", "tai nghe", "loa", "smartwatch",
    "laptop", "tablet", "nồi chiên", "noi chien", "máy lạnh", "may lanh",
})


@dataclass(frozen=True)
class ProductSignatures:
    lines: frozenset[str]
    categories: frozenset[str]


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def extract_product_lines(text: str) -> frozenset[str]:
    """Trích dòng SP từ câu."""
    folded = _fold(text)
    if not folded.strip():
        return frozenset()
    lines: set[str] = set()
    for pattern, line_id in _PRODUCT_LINE_RULES:
        if pattern.search(folded):
            lines.add(line_id)
    return frozenset(lines)


def _extract_categories(text: str) -> frozenset[str]:
    folded = _fold(text)
    if not folded.strip():
        return frozenset()
    if _INBOX_ACCESSORY_RE.search(folded):
        return frozenset()
    categories: set[str] = set()
    for pattern, cat_id in _CATEGORY_RULES:
        if pattern.search(folded):
            categories.add(cat_id)
    return frozenset(categories)


def extract_signatures(text: str) -> ProductSignatures:
    lines = extract_product_lines(text)
    categories = set(_extract_categories(text))
    for line_id in lines:
        cat = _LINE_TO_CATEGORY.get(line_id)
        if cat:
            categories.add(cat)
    return ProductSignatures(lines=lines, categories=frozenset(categories))


def _query_introduces_product_subject(text: str) -> bool:
    """Câu mới đang tra cứu SP/dòng khác (không phải hỏi tiếp thuần)."""
    folded = _fold(text)
    if not folded.strip():
        return False
    sig = extract_signatures(text)
    if sig.lines:
        return True
    if sig.categories and (
        _PRODUCT_LOOKUP_RE.search(folded)
        or _PRODUCT_LOOKUP_RE.search(text or "")
    ):
        return True
    if sig.categories and any(h in folded for h in _PRODUCT_LINE_HINTS):
        return True
    return False


def product_context_conflict(text_a: str, text_b: str) -> bool:
    """
    True khi hai câu không cùng SP/dòng/danh mục.
    text_a thường là câu mới; text_b là session/context.
    """
    sig_a = extract_signatures(text_a)
    sig_b = extract_signatures(text_b)

    lines_a = _distinct_lines(sig_a.lines)
    lines_b = _distinct_lines(sig_b.lines)
    if lines_a and lines_b and not (lines_a & lines_b):
        return True

    if (
        sig_a.categories
        and sig_b.categories
        and not (sig_a.categories & sig_b.categories)
        and _query_introduces_product_subject(text_a)
    ):
        return True

    return False


def product_lines_conflict(text_a: str, text_b: str) -> bool:
    """Alias — dùng product_context_conflict (line + category)."""
    return product_context_conflict(text_a, text_b)


def is_inbox_accessory_question(text: str) -> bool:
    """Hỏi phụ kiện/kèm theo trong hộp SP đang thảo luận (không phải chuyển sang mua tai nghe)."""
    folded = _fold(text or "")
    return bool(_INBOX_ACCESSORY_RE.search(folded))


def mentions_product_line(text: str) -> bool:
    """Câu có nhắc tên/dòng/danh mục sản phẩm cụ thể."""
    folded = _fold(text)
    if _INBOX_ACCESSORY_RE.search(folded):
        return False
    sig = extract_signatures(text)
    if sig.lines:
        return True
    return any(hint in folded for hint in _PRODUCT_LINE_HINTS)


def required_model_phrases(text: str) -> list[str]:
    """Cụm model bắt buộc giữ nguyên khi LLM chuẩn hóa từ khóa."""
    folded = _fold(text)
    phrases: list[str] = []
    pairs = (
        ("macbook neo", r"\bmacbook\s+neo\b"),
        ("macbook air", r"\bmacbook\s+air\b"),
        ("macbook pro", r"\bmacbook\s+pro\b"),
        ("mac mini", r"\bmac\s+mini\b"),
        ("mac studio", r"\bmac\s+studio\b"),
        ("imac", r"\bimac\b"),
        ("iphone air", r"\biphone\s+air\b"),
        ("ipad pro", r"\bipad\s+pro\b"),
        ("ipad air", r"\bipad\s+air\b"),
        ("galaxy z fold", r"\bgalaxy\s+z\s+fold\b|\bz\s+fold\b"),
        ("galaxy z flip", r"\bgalaxy\s+z\s+flip\b|\bz\s+flip\b"),
        ("redmi note", r"\bredmi\s+note\b"),
        ("pin dự phòng", r"\bpin dự phòng\b|\bpin du phong\b|\bpower bank\b"),
    )
    for phrase, pattern in pairs:
        if re.search(pattern, folded, re.I):
            phrases.append(phrase)

    iphone_gen = re.search(r"\biphone\s+(\d{1,2}e?)\b", folded)
    if iphone_gen:
        phrases.append(f"iphone {iphone_gen.group(1)}")

    galaxy_gen = re.search(r"\bgalaxy\s+s?(\d{1,2})\b", folded)
    if galaxy_gen:
        phrases.append(f"galaxy s{galaxy_gen.group(1)}")

    s24 = re.search(r"\bs24\b|\bgalaxy\s+s24\b", folded)
    if s24 and "galaxy s24" not in phrases:
        phrases.append("galaxy s24")

    return phrases


def context_product_text(conversation_context: str) -> str:
    """Gộp tên SP + từ khóa từ block ngữ cảnh hội thoại."""
    keywords = ""
    product_name = ""
    for line in (conversation_context or "").splitlines():
        if line.startswith("Từ khóa tìm gần nhất:"):
            keywords = line.split(":", 1)[1].strip()
        elif line.startswith("Sản phẩm đang thảo luận:"):
            product_name = line.split(":", 1)[1].strip()
    return f"{keywords} {product_name}".strip()
