"""Test danh sách tỉnh CellphoneS."""
from __future__ import annotations

from cps_bot.cps.cps_provinces import (
    CPS_PROVINCES,
    PROVINCE_COMPANY_ID,
    PROVINCE_ID_TO_NAME,
    company_id_for_province,
    resolve_province_from_text,
)


def test_all_provinces_loaded() -> None:
    assert len(CPS_PROVINCES) == 48
    assert PROVINCE_ID_TO_NAME[30] == "Hồ Chí Minh"
    assert PROVINCE_ID_TO_NAME[24] == "Hà Nội"
    assert PROVINCE_ID_TO_NAME[15] == "Đà Nẵng"
    assert PROVINCE_ID_TO_NAME[27] == "Hải Phòng"


def test_company_id_regions() -> None:
    assert PROVINCE_COMPANY_ID[30] == 12869
    assert PROVINCE_COMPANY_ID[24] == 3759
    assert PROVINCE_COMPANY_ID[15] == 3759
    assert company_id_for_province(8) == 12869
    assert company_id_for_province(5) == 3759


def test_resolve_major_cities() -> None:
    assert resolve_province_from_text("shop HCM còn hàng không") == 30
    assert resolve_province_from_text("Hà Nội có không") == 24
    assert resolve_province_from_text("ở Đà Nẵng còn không") == 15
    assert resolve_province_from_text("Hải Phòng có shop không") == 27


def test_resolve_other_provinces() -> None:
    assert resolve_province_from_text("Bình Dương còn hàng") == 8
    assert resolve_province_from_text("Cần Thơ có shop không") == 14
    assert resolve_province_from_text("Vũng Tàu còn không") == 2
    assert resolve_province_from_text("Huế có hàng không") == 57


if __name__ == "__main__":
    test_all_provinces_loaded()
    test_company_id_regions()
    test_resolve_major_cities()
    test_resolve_other_provinces()
    print("OK — province tests passed")
