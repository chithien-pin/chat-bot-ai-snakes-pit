"""Regression — 3 case routing sai (pocket 3, điện thoại 5 triệu, iphone dưới 20tr)."""
from __future__ import annotations

from cps_bot.browse.budget_browse import is_budget_browse_query, parse_budget_constraint
from cps_bot.browse.category_filter_browse import (
    build_category_filter_url,
    is_category_filter_browse_query,
    resolve_category_filter_request,
    resolve_filter_price,
)
from cps_bot.browse.product_map import clear_product_map_cache, resolve_product_from_map
from cps_bot.cps.cps_api import _pick_best_search_result
from cps_bot.llm.query_router import resolve_query_route


def test_case2_bare_5_trieu_budget_range() -> None:
    text = "Điện thoại 5 triệu"
    c = parse_budget_constraint(text)
    assert c is not None
    assert c.min_vnd == 4_000_000
    assert c.max_vnd == 6_000_000
    assert is_budget_browse_query(text)

    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "3"
    url = build_category_filter_url(req, resolve_filter_price(text))
    assert "price=4000000-6000000" in url
    assert url.startswith("mobile.html")

    route = resolve_query_route(text, use_llm=False)
    assert route.mode == "category_browse"
    assert route.confidence >= 0.85
    assert "price=4000000-6000000" in route.filter_url


def test_case3_iphone_under_20_trieu_apple_filter() -> None:
    text = "Điện thoại iphone dưới 20 triệu"
    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "132"
    assert req.page_path == "mobile/apple.html"
    assert "pho-thong" not in (req.page_path or "")
    assert not any(
        f.get("key") == "screen_size" for f in (req.matched_filters or [])
    )

    url = build_category_filter_url(req, resolve_filter_price(text))
    assert url == "mobile/apple.html?price=0-20000000"

    route = resolve_query_route(text, use_llm=False)
    assert route.mode == "category_browse"
    assert "mobile/apple.html" in route.filter_url
    assert "price=0-20000000" in route.filter_url


def test_case1_pocket_3_product_map() -> None:
    clear_product_map_cache()
    hit = resolve_product_from_map("pocket 3")
    assert hit is not None
    assert hit.product_id == "71385"
    assert "pocket 3" in hit.name.lower() or "osmo pocket 3" in hit.name.lower()
    assert "huawei" not in hit.name.lower()

    route = resolve_query_route("pocket 3", use_llm=False)
    assert route.mode == "product_search"
    assert route.confidence >= 0.85


def test_case1_pocket_3_search_ranking() -> None:
    results = [
        {"name": "Huawei Pocket S", "url_path": "dien-thoai-huawei-pocket-s.html"},
        {"name": "DJI Osmo Pocket 3", "url_path": "camera-dji-osmo-pocket-3.html"},
    ]
    best = _pick_best_search_result(results, "pocket 3")
    assert best is not None
    assert "dji" in (best.get("name") or "").lower()


def test_case4_designer_3d_laptop_usecase() -> None:
    text = "là designer muốn tìm máy làm 3D"
    assert is_category_filter_browse_query(text)
    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "380"
    assert req.page_path == "laptop.html"
    assert any(
        f.get("key") == "nhu_cau_su_dung"
        and "do-hoa-ky-thuat" in (f.get("nice_uris") or [])
        for f in req.matched_filters
    )
    url = build_category_filter_url(req, resolve_filter_price(text))
    assert "laptop.html" in url
    assert "nhu_cau_su_dung=do-hoa-ky-thuat" in url

    route = resolve_query_route(text, use_llm=False)
    assert route.mode == "category_browse"


def test_case4_laptop_lam_3d_short_token() -> None:
    text = "laptop làm 3d"
    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "380"
    assert any(
        "do-hoa-ky-thuat" in (f.get("nice_uris") or [])
        for f in req.matched_filters
    )


def test_case5_sport_watch_no_bogus_filters() -> None:
    text = "đồng hồ thể thao"
    req = resolve_category_filter_request(text)
    assert req is not None
    # Không được tự gắn filter tính năng/sức khỏe khi user không nhắc
    assert not req.matched_filters
    assert not req.dynamic_filter
    assert req.is_subcategory_menu

    # Gọi đúng tên subcategory → browse list
    assert is_category_filter_browse_query(text)
    url = build_category_filter_url(req, resolve_filter_price(text))
    assert url == "do-choi-cong-nghe/dong-ho-the-thao.html"
    assert "smart_watch" not in url

    route = resolve_query_route(text, use_llm=False)
    assert route.mode == "category_browse"


def test_non_laptop_usecase_not_hijacked() -> None:
    # "máy ảnh" không được ép về laptop dù có thể có từ nhu cầu
    from cps_bot.browse.category_filter_browse import _resolve_laptop_usecase_browse

    assert _resolve_laptop_usecase_browse("máy ảnh chụp đồ họa") is None
    # Không có ngữ cảnh laptop/pc → không tự route laptop
    assert _resolve_laptop_usecase_browse("làm 3d") is None


def test_case6_vacuum_suction_over_10000pa() -> None:
    text = "máy hút bụi lực hút trên 10000Pa"
    assert not is_budget_browse_query(text)
    assert parse_budget_constraint(text) is None
    assert is_category_filter_browse_query(text)
    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "824"
    assert req.page_path == "nha-thong-minh/may-hut-bui/may-hut-bui-cam-tay.html"
    assert any(
        f.get("key") == "robot_luc_hut_filter"
        and "tren-10000pa" in (f.get("nice_uris") or [])
        for f in req.matched_filters
    )
    url = build_category_filter_url(req, resolve_filter_price(text))
    assert url == (
        "nha-thong-minh/may-hut-bui/may-hut-bui-cam-tay.html"
        "?robot_luc_hut_filter=tren-10000pa"
    )
    route = resolve_query_route(text, use_llm=False)
    assert route.mode == "category_browse"


def test_case6_vacuum_pa_not_budget() -> None:
    text = "máy hút bụi trên 10.000 Pa"
    assert parse_budget_constraint(text) is None
    assert not is_budget_browse_query(text)


if __name__ == "__main__":
    test_case2_bare_5_trieu_budget_range()
    test_case3_iphone_under_20_trieu_apple_filter()
    test_case1_pocket_3_product_map()
    test_case1_pocket_3_search_ranking()
    test_case4_designer_3d_laptop_usecase()
    test_case4_laptop_lam_3d_short_token()
    test_case5_sport_watch_no_bogus_filters()
    test_non_laptop_usecase_not_hijacked()
    test_case6_vacuum_suction_over_10000pa()
    test_case6_vacuum_pa_not_budget()
    print("OK — query routing case tests passed")
