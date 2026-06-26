"""
Danh sách tỉnh/thành CellphoneS — dùng cho resolve tỉnh, company_id, tồn cửa hàng.
Nguồn: API province CellphoneS.
"""
from __future__ import annotations

import re
import unicodedata

# company_id: 12869 = Miền Nam, 3759 = Miền Bắc
CPS_PROVINCES: list[dict[str, int | str]] = [
    {"id": 1, "name": "An Giang", "company_id": 12869},
    {"id": 2, "name": "Bà Rịa - Vũng Tàu", "company_id": 12869},
    {"id": 3, "name": "Bạc Liêu", "company_id": 12869},
    {"id": 5, "name": "Bắc Giang", "company_id": 3759},
    {"id": 6, "name": "Bắc Ninh", "company_id": 3759},
    {"id": 7, "name": "Bến Tre", "company_id": 12869},
    {"id": 8, "name": "Bình Dương", "company_id": 12869},
    {"id": 9, "name": "Bình Định", "company_id": 12869},
    {"id": 10, "name": "Bình Phước", "company_id": 12869},
    {"id": 11, "name": "Bình Thuận", "company_id": 12869},
    {"id": 12, "name": "Cà Mau", "company_id": 12869},
    {"id": 14, "name": "Cần Thơ", "company_id": 12869},
    {"id": 15, "name": "Đà Nẵng", "company_id": 3759},
    {"id": 16, "name": "Đắk Lắk", "company_id": 12869},
    {"id": 19, "name": "Đồng Nai", "company_id": 12869},
    {"id": 20, "name": "Đồng Tháp", "company_id": 12869},
    {"id": 21, "name": "Gia Lai", "company_id": 12869},
    {"id": 23, "name": "Hà Nam", "company_id": 3759},
    {"id": 24, "name": "Hà Nội", "company_id": 3759},
    {"id": 25, "name": "Hà Tĩnh", "company_id": 3759},
    {"id": 26, "name": "Hải Dương", "company_id": 3759},
    {"id": 27, "name": "Hải Phòng", "company_id": 3759},
    {"id": 29, "name": "Hòa Bình", "company_id": 3759},
    {"id": 30, "name": "Hồ Chí Minh", "company_id": 12869},
    {"id": 31, "name": "Hưng Yên", "company_id": 3759},
    {"id": 32, "name": "Khánh Hòa", "company_id": 12869},
    {"id": 33, "name": "Kiên Giang", "company_id": 12869},
    {"id": 36, "name": "Lạng Sơn", "company_id": 3759},
    {"id": 38, "name": "Lâm Đồng", "company_id": 12869},
    {"id": 39, "name": "Long An", "company_id": 12869},
    {"id": 40, "name": "Nam Định", "company_id": 3759},
    {"id": 41, "name": "Nghệ An", "company_id": 3759},
    {"id": 42, "name": "Ninh Bình", "company_id": 3759},
    {"id": 43, "name": "Ninh Thuận", "company_id": 12869},
    {"id": 44, "name": "Phú Thọ", "company_id": 3759},
    {"id": 46, "name": "Quảng Bình", "company_id": 3759},
    {"id": 48, "name": "Quảng Ngãi", "company_id": 12869},
    {"id": 49, "name": "Quảng Ninh", "company_id": 3759},
    {"id": 51, "name": "Sóc Trăng", "company_id": 12869},
    {"id": 53, "name": "Tây Ninh", "company_id": 12869},
    {"id": 54, "name": "Thái Bình", "company_id": 3759},
    {"id": 55, "name": "Thái Nguyên", "company_id": 3759},
    {"id": 56, "name": "Thanh Hóa", "company_id": 3759},
    {"id": 57, "name": "Thừa Thiên - Huế", "company_id": 3759},
    {"id": 58, "name": "Tiền Giang", "company_id": 12869},
    {"id": 59, "name": "Trà Vinh", "company_id": 12869},
    {"id": 61, "name": "Vĩnh Long", "company_id": 12869},
    {"id": 62, "name": "Vĩnh Phúc", "company_id": 3759},
]

PROVINCE_ID_TO_NAME: dict[int, str] = {
    int(p["id"]): str(p["name"]) for p in CPS_PROVINCES
}

PROVINCE_COMPANY_ID: dict[int, int] = {
    int(p["id"]): int(p["company_id"]) for p in CPS_PROVINCES
}

# Viết tắt / tên gọi phổ biến ngoài tên chính thức
_EXTRA_PROVINCE_ALIASES: dict[str, int] = {
    "hcm": 30,
    "tp hcm": 30,
    "tp.hcm": 30,
    "tphcm": 30,
    "tp ho chi minh": 30,
    "sài gòn": 30,
    "sai gon": 30,
    "sg": 30,
    "hn": 24,
    "ha noi": 24,
    "hà nội": 24,
    "da nang": 15,
    "đà nẵng": 15,
    "dn": 15,
    "hue": 57,
    "huế": 57,
    "thua thien hue": 57,
    "thừa thiên huế": 57,
    "can tho": 14,
    "cần thơ": 14,
    "vung tau": 2,
    "vũng tàu": 2,
    "ba ria": 2,
    "bà rịa": 2,
    "br vt": 2,
    "hai phong": 27,
    "hải phòng": 27,
    "hp": 27,
    "binh duong": 8,
    "bình dương": 8,
    "bd": 8,
    "dong nai": 19,
    "đồng nai": 19,
    "long an": 39,
    "khanh hoa": 32,
    "khánh hòa": 32,
    "nha trang": 32,
    "lam dong": 38,
    "lâm đồng": 38,
    "da lat": 38,
    "đà lạt": 38,
    "quang ninh": 49,
    "quảng ninh": 49,
    "ha long": 49,
    "hạ long": 49,
}


def _strip_accents(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _normalize_alias(text: str) -> str:
    s = (text or "").strip().lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", " ", s)
    return s


def _alias_variants(name: str) -> set[str]:
    variants: set[str] = set()
    base = _normalize_alias(name)
    if not base:
        return variants
    variants.add(base)
    stripped = _normalize_alias(_strip_accents(name))
    if stripped:
        variants.add(stripped)
    for part in re.split(r"\s*-\s*", name):
        part = part.strip()
        if not part:
            continue
        variants.add(_normalize_alias(part))
        variants.add(_normalize_alias(_strip_accents(part)))
    return variants


def _build_province_aliases() -> dict[str, int]:
    aliases: dict[str, int] = {}
    for province in CPS_PROVINCES:
        pid = int(province["id"])
        for variant in _alias_variants(str(province["name"])):
            aliases.setdefault(variant, pid)
    for alias, pid in _EXTRA_PROVINCE_ALIASES.items():
        aliases[_normalize_alias(alias)] = pid
    return aliases


PROVINCE_NAME_ALIASES: dict[str, int] = _build_province_aliases()


def province_name(province_id: int | None) -> str:
    if province_id is None:
        return ""
    return PROVINCE_ID_TO_NAME.get(int(province_id), "")


def company_id_for_province(province_id: int, *, default_province_id: int = 30) -> int:
    if province_id in PROVINCE_COMPANY_ID:
        return PROVINCE_COMPANY_ID[province_id]
    return PROVINCE_COMPANY_ID.get(default_province_id, 12869)


def resolve_province_from_text(text: str) -> int | None:
    """Trích tỉnh/thành từ câu hỏi (vd: Hà Nội, Bình Dương, Cần Thơ)."""
    lower = _normalize_alias(text)
    if not lower:
        return None
    for alias, pid in sorted(
        PROVINCE_NAME_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if alias in lower:
            return pid
    return None
