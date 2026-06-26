"""Test trích địa điểm & khớp quận (quận 9 vs Q.9)."""
from __future__ import annotations

from cps_bot.cps.cps_api import (
    _flatten_shops,
    _shop_matches_location,
    extract_location_hint,
)


def _shop(address: str, district_name: str = "") -> dict:
    return {
        "address": address,
        "near": "",
        "district_name": district_name,
        "external_id": 999,
    }


def _districts(*shops: dict) -> list[dict]:
    return [{"district_name": "Quận 9", "shops": list(shops)}]


Q9_SHOPS = _districts(
    _shop("241-243 Đỗ Xuân Hợp, P. Phước Long B, Q.9"),
    _shop("241 Lê Văn Việt, P. Hiệp Phú, Q.9"),
)

Q10_SHOP = _districts(
    _shop("347 Nguyễn Tri Phương, Phường 5, Quận 10"),
)


def test_extract_quan_9() -> None:
    hint = extract_location_hint("Có chỗ nào gần quận 9 không?")
    assert hint == "quận 9", hint


def test_extract_q_abbrev() -> None:
    assert extract_location_hint("Q.9 có hàng không?") == "quận 9"
    assert extract_location_hint("q9 còn không") == "quận 9"


def test_match_quan_9_addresses() -> None:
    hint = extract_location_hint("Có chỗ nào gần quận 9 không?")
    matched = _flatten_shops(Q9_SHOPS, location_hint=hint)
    assert len(matched) == 2, f"expected 2 Q9 shops, got {len(matched)}"


def test_match_q_abbrev_same_as_quan() -> None:
    h1 = extract_location_hint("gần quận 9 không?")
    h2 = extract_location_hint("Q.9 có hàng không?")
    m1 = _flatten_shops(Q9_SHOPS, location_hint=h1)
    m2 = _flatten_shops(Q9_SHOPS, location_hint=h2)
    assert len(m1) == len(m2) == 2


def test_quan_9_excludes_quan_10() -> None:
    all_d = Q9_SHOPS + Q10_SHOP
    hint = extract_location_hint("quận 9 có hàng không")
    matched = _flatten_shops(all_d, location_hint=hint)
    assert len(matched) == 2
    assert all("Q.9" in s["address"] or "q.9" in s["address"].lower() for s in matched)


def test_shop_matches_q9_format() -> None:
    shop = _shop("241 Lê Văn Việt, P. Hiệp Phú, Q.9")
    assert _shop_matches_location(shop, "quận 9")
    assert _shop_matches_location(shop, "Q.9")
    assert not _shop_matches_location(shop, "quận 10")


if __name__ == "__main__":
    test_extract_quan_9()
    test_extract_q_abbrev()
    test_match_quan_9_addresses()
    test_match_q_abbrev_same_as_quan()
    test_quan_9_excludes_quan_10()
    test_shop_matches_q9_format()
    print("OK — location hint tests passed")
