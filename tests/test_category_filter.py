"""Test category attribute filter browse."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cps_bot.browse.category_filter_browse import (
    match_attribute_filters,
    resolve_category_filter_request,
)
from cps_bot.browse.category_resolver import match_category_from_text
from cps_bot.cps.cps_category_filter import (
    build_dynamic_filter_clause,
    fetch_category_attributes,
    normalize_category_attributes,
)


def test_normalize_attributes_structure():
    sample = [
        {
            "key": "laptop_cpu",
            "label": "CPU",
            "active": True,
            "data": [
                {"label": "Intel Core i5", "nice_uri": "intel-core-i5", "active": True},
                {"label": "AMD Ryzen 5", "nice_uri": "amd-ryzen-5", "active": True},
            ],
        }
    ]
    attrs = normalize_category_attributes(sample)
    assert len(attrs) == 1
    assert attrs[0]["key"] == "laptop_cpu"
    assert attrs[0]["options"][0]["nice_uri"] == "intel-core-i5"


def test_build_dynamic_filter_clause():
    clause = build_dynamic_filter_clause([("laptop_cpu", ["intel-core-i5"])])
    assert "laptop_cpu" in clause
    assert "intel-core-i5" in clause
    assert "use_nice_uri: true" in clause


def test_match_intel_on_laptop_attributes():
    category_data = {
        "attributes": normalize_category_attributes(
            [
                {
                    "key": "laptop_cpu",
                    "label": "CPU",
                    "active": True,
                    "data": [
                        {"label": "Intel Core i5", "nice_uri": "intel-core-i5", "active": True},
                        {"label": "Intel Core i7", "nice_uri": "intel-core-i7", "active": True},
                        {"label": "AMD Ryzen 5", "nice_uri": "amd-ryzen-5", "active": True},
                    ],
                }
            ]
        )
    }
    matches = match_attribute_filters(
        "laptop dùng chip intel",
        category_data,
        strip_menu_name="Laptop",
    )
    assert matches
    key, uris, labels = matches[0]
    assert key == "laptop_cpu"
    assert "intel-core-i5" in uris
    assert any("Intel" in lb for lb in labels)


def test_resolve_laptop_intel_query_with_map(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    attrs_file = tmp_path / "category_attributes_map.json"
    menu_file = tmp_path / "menu_category_map.json"

    menu_file.write_text(
        json.dumps({"entries": {"Laptop": "380"}}),
        encoding="utf-8",
    )

    async def _load():
        cat = await fetch_category_attributes(380)
        assert cat
        attrs_file.write_text(
            json.dumps({"categories": {"380": cat}}),
            encoding="utf-8",
        )
        return cat

    cat = asyncio.run(_load())

    import config
    import cps_bot.cps.cps_category_filter
    import cps_bot.browse.category_filter_browse as cfb

    old_menu = config.MENU_CATEGORY_MAP_PATH
    old_attrs = config.CATEGORY_ATTRIBUTES_MAP_PATH
    try:
        config.MENU_CATEGORY_MAP_PATH = str(menu_file)
        config.CATEGORY_ATTRIBUTES_MAP_PATH = str(attrs_file)
        cps_category_filter.MENU_CATEGORY_MAP_PATH = str(menu_file)
        cps_category_filter.CATEGORY_ATTRIBUTES_MAP_PATH = str(attrs_file)

        req = resolve_category_filter_request("laptop dùng chip intel")
        assert req is not None, "expected category filter request"
        assert req.category_id == "380"
        assert req.dynamic_filter
        assert "laptop_cpu" in req.dynamic_filter or "intel" in req.dynamic_filter
    finally:
        config.MENU_CATEGORY_MAP_PATH = old_menu
        config.CATEGORY_ATTRIBUTES_MAP_PATH = old_attrs


def test_resolve_android_phone_budget_query():
    text = "điện thoại Android dưới 10 triệu"
    req = resolve_category_filter_request(text)
    assert req is not None, "expected category filter request"
    assert req.category_id == "3"
    assert req.dynamic_filter
    assert "mobile_os_filter" in req.dynamic_filter
    assert "android" in req.dynamic_filter

    from cps_bot.browse.category_filter_browse import build_category_filter_url, resolve_filter_price

    url = build_category_filter_url(req, resolve_filter_price(text))
    assert url.startswith("mobile.html?")
    assert "mobile_os_filter=android" in url
    assert "price=0-10000000" in url


def test_skip_price_menu_name_when_matching_category():
    hit = match_category_from_text("điện thoại Android dưới 10 triệu")
    assert hit is not None
    assert hit[0] == "3"
    assert hit[1] == "Điện thoại"


def test_tablet_budget_not_used_category():
    text = "máy tính bảng dưới 27 triệu"
    hit = match_category_from_text(text)
    assert hit is not None
    assert hit[0] == "4", f"expected Tablet (4), got {hit}"
    assert hit[1] == "Tablet"

    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "4"
    assert req.menu_name == "Tablet"
    assert "hang-cu" not in (req.page_path or "")

    from cps_bot.browse.category_filter_browse import build_category_filter_url, resolve_filter_price

    url = build_category_filter_url(req, resolve_filter_price(text))
    assert url.startswith("tablet.html?")
    assert "price=0-27000000" in url


def test_used_tablet_when_user_asks_cu():
    hit = match_category_from_text("máy tính bảng cũ dưới 5 triệu")
    assert hit is not None
    assert hit[0] == "941"


def test_laptop_synonym_resolves_to_main_category():
    hit = match_category_from_text("laptop dưới 20 triệu")
    assert hit == ("380", "Laptop")


def test_phone_vietnamese_synonym():
    from cps_bot.browse.category_resolver import resolve_category_match

    hit = resolve_category_match("điện thoại android dưới 10 triệu")
    assert hit is not None
    assert hit.category_id == "3"
    assert hit.menu_name == "Điện thoại"


def test_screen_protector_deepest_category():
    from cps_bot.browse.category_filter_browse import (
        build_category_filter_url,
        resolve_category_filter_request,
    )

    text = "miếng dán màn hình chống nhìn trộm iphone 17 thường"
    req = resolve_category_filter_request(text)
    assert req is not None, "expected category filter request"
    assert req.category_id == "2668", f"expected Dán màn hình iPhone 17 (2668), got {req}"
    assert req.menu_name == "Dán màn hình iPhone 17"
    assert "iphone-17.html" in (req.page_path or "")

    url = build_category_filter_url(req, None)
    assert "tinh_nang_dac_biet=chong-nhin-trom" in url
    assert "iphone-17-pro" not in url


def test_screen_protector_not_monitor_category():
    from cps_bot.browse.category_resolver import resolve_category_match

    hit = resolve_category_match(
        "miếng dán màn hình chống nhìn trộm iphone 17 thường"
    )
    assert hit is not None, "expected category match"
    assert hit.category_id in ("286", "2668")
    assert hit.menu_name.startswith("Dán màn hình")
    assert hit.page_path != "man-hinh.html"
    assert "dan-man-hinh" in (hit.page_path or "")


def test_monitor_query_still_resolves():
    from cps_bot.browse.category_resolver import resolve_category_match

    hit = resolve_category_match("màn hình gaming 27 inch")
    assert hit is not None
    assert hit.category_id in ("784", "1233")
    assert "man-hinh" in (hit.page_path or "")


def test_specific_iphone_price_skips_category_browse():
    from cps_bot.browse.category_filter_browse import is_category_filter_browse_query

    assert not is_category_filter_browse_query(
        "Giá iphone 17 pro max 512gb bao nhiêu hôm nay"
    )


def test_accessory_with_iphone_still_category_browse():
    from cps_bot.browse.category_filter_browse import is_category_filter_browse_query

    assert is_category_filter_browse_query(
        "miếng dán màn hình chống nhìn trộm iphone 17 thường"
    )


def test_cho_toi_does_not_match_o_to_category():
    from cps_bot.browse.category_resolver import resolve_category_match, _category_match_index

    _category_match_index.cache_clear()
    hit = resolve_category_match("tư vấn cho tôi một số Pin Anker 10000mah")
    assert hit is not None
    assert hit.category_id == "122", f"expected Pin dự phòng, got {hit}"
    assert "o-to" not in (hit.page_path or "")


def test_pin_anker_10000mah_category_filter_url():
    from cps_bot.browse.category_filter_browse import (
        build_category_filter_url,
        is_category_filter_browse_query,
        resolve_category_filter_request,
    )
    from cps_bot.browse.category_resolver import _category_match_index

    _category_match_index.cache_clear()
    text = "Tư vấn một số pin Anker 10000mah"
    assert is_category_filter_browse_query(text)
    req = resolve_category_filter_request(text)
    assert req is not None
    assert req.category_id == "122"
    url = build_category_filter_url(req)
    assert url.startswith("phu-kien/pin-du-phong/anker.html")
    assert "battery_capacity=10000-mah" in url
    assert "o-to" not in url


def test_fresh_topic_does_not_reuse_other_thread_context():
    from cps_bot.core.conversation import get_session, resolve_session

    store: dict = {}
    chat_id = "oc_test"
    user_id = "u1"
    other = get_session(store, chat_id, user_id, thread_key="topic:old")
    other["last_keywords"] = "iphone"
    other["last_product"] = {"name": "iPhone", "url": "https://cellphones.com.vn/iphone.html"}
    other["turns"] = [{"user": "q", "assistant": "a"}]

    fresh = resolve_session(store, chat_id, user_id, thread_key="topic:new")
    assert not fresh.get("last_keywords")
    assert not fresh.get("last_product")


if __name__ == "__main__":
    test_normalize_attributes_structure()
    test_build_dynamic_filter_clause()
    test_match_intel_on_laptop_attributes()
    test_resolve_laptop_intel_query_with_map(Path("data/_cat_filter_test"))
    test_resolve_android_phone_budget_query()
    test_skip_price_menu_name_when_matching_category()
    test_tablet_budget_not_used_category()
    test_used_tablet_when_user_asks_cu()
    test_laptop_synonym_resolves_to_main_category()
    test_phone_vietnamese_synonym()
    test_screen_protector_not_monitor_category()
    test_screen_protector_deepest_category()
    test_monitor_query_still_resolves()
    test_specific_iphone_price_skips_category_browse()
    test_accessory_with_iphone_still_category_browse()
    print("OK")
