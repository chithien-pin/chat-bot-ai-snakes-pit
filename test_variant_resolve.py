"""Test variant hint extraction."""
from __future__ import annotations

from cps_api import _extract_variant_hints, _variant_hint_score


def test_storage_hint() -> None:
    hints = _extract_variant_hints("iPhone 16 Pro Max 256GB Titan")
    assert "256gb" in hints


def test_color_hint() -> None:
    hints = _extract_variant_hints("iPhone 16 Plus 256 màu hồng")
    assert "hồng" in hints


def test_variant_score() -> None:
    score = _variant_hint_score("iPhone 16 Pro Max 256GB Titan Tự Nhiên", ["256gb", "titan"])
    assert score >= 20


if __name__ == "__main__":
    test_storage_hint()
    test_color_hint()
    test_variant_score()
    print("OK — variant resolve tests passed")
