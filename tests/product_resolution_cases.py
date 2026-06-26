"""
Ma trận resolve sản phẩm — từ khóa, màu, tier, map/search.
Dùng cho test_product_resolution_matrix.py (local, không LLM).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeywordCase:
    id: str
    query: str
    expected: str
    """Từ khóa sau normalize (extract_search_keywords, use_llm=False)."""


@dataclass(frozen=True)
class ColorHintCase:
    id: str
    text: str
    want: str
    avoid: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchPickCase:
    id: str
    keywords: str
    want_substr: str
    avoid_substr: tuple[str, ...] = ()


@dataclass(frozen=True)
class MapCase:
    id: str
    keywords: str
    product_id: str
    name_contains: str = ""


KEYWORD_CASES: tuple[KeywordCase, ...] = (
    KeywordCase("kw_ip16_color", "ip16 xanh lưu ly giá bao nhiêu?", "iphone 16 xanh lưu ly"),
    KeywordCase("kw_ip15_color", "ip15 hồng giá bao nhiêu?", "iphone 15 hồng"),
    KeywordCase("kw_ip17", "ip17 trắng 256g", "iphone 17 trắng 256gb"),
    KeywordCase("kw_promax", "iphone 16 promax hôm nay bao nhiêu?", "iphone 16 pro max"),
    KeywordCase("kw_ip_space", "ip 16 pro max hôm nay bao nhiêu", "iphone 16 pro max"),
)

COLOR_HINT_CASES: tuple[ColorHintCase, ...] = (
    ColorHintCase("c_luu_ly", "iphone 16 xanh lưu ly", "xanh lưu ly", ("xanh",)),
    ColorHintCase("c_mong_ket", "iphone 16 xanh mỏng két 128g", "xanh mỏng két", ("xanh",)),
    ColorHintCase("c_xanh_duong", "iphone 15 xanh dương", "xanh dương", ("xanh lá", "xanh")),
    ColorHintCase("c_xanh_la", "iphone 15 màu xanh lá", "xanh lá", ("xanh dương",)),
    ColorHintCase("c_titan_sa_mac", "iphone 16 pro max titan sa mạc", "titan sa mạc", ()),
    ColorHintCase("c_cam_vu_tru", "iphone 17 pro max màu cam vũ trụ", "cam vũ trụ", ("cam",)),
    ColorHintCase("c_hong", "iphone 15 hồng 256g", "hồng", ()),
    ColorHintCase("c_generic_xanh", "iphone 15 màu xanh", "xanh", ("xanh dương", "xanh lá")),
)

SEARCH_PICK_CASES: tuple[SearchPickCase, ...] = (
    SearchPickCase(
        "pick_base_over_promax",
        "iphone 16 xanh lưu ly",
        "iPhone 16 128GB",
        ("Pro Max", "Plus"),
    ),
    SearchPickCase(
        "pick_base_over_pro",
        "iPhone 16 256GB Hồng",
        "iPhone 16 256GB",
        ("Pro",),
    ),
    SearchPickCase(
        "pick_base_over_plus",
        "iPhone 16 128GB Xanh Mỏng Két",
        "iPhone 16 128GB",
        ("Plus",),
    ),
    SearchPickCase(
        "pick_promax_when_asked",
        "iphone 16 pro max 256gb",
        "Pro Max",
        (),
    ),
)

# Map thật — skip nếu không có file product_map.txt
REAL_MAP_CASES: tuple[MapCase, ...] = (
    MapCase("map_ip16_base", "iphone 16", "59254", "iPhone 16"),
    MapCase("map_ip16_luu_ly", "iphone 16 xanh lưu ly", "59254", "iPhone 16"),
    MapCase("map_ip16_promax", "iphone 16 pro max", "59258", "Pro Max"),
    MapCase("map_ip16_hong_256", "iphone 16 hồng 256g", "90112", "256"),
    MapCase("map_ip15_hong", "iphone 15 hồng", "43152", "iPhone 15"),
)

# Tích hợp API (chạy khi PRODUCT_RESOLUTION_INTEGRATION=1)
INTEGRATION_CASES: tuple[KeywordCase, ...] = (
    KeywordCase("int_ip16_luu_ly", "ip16 xanh lưu ly giá bao nhiêu?", "90126"),
    KeywordCase("int_ip15_hong", "ip15 hồng giá bao nhiêu?", "68892"),
)
