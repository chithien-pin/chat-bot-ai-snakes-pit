"""Test advanced_search helpers."""
from __future__ import annotations

from scraper import search_results_need_advanced


def test_need_advanced_empty() -> None:
    assert search_results_need_advanced([], "iphone 16")


def test_need_advanced_single() -> None:
    results = [{"name": "iPhone 16 Pro Max 256GB"}]
    assert not search_results_need_advanced(results, "iphone 16 pro max")


def test_need_advanced_noisy() -> None:
    results = [
        {"name": "Tai nghe Bluetooth ABC"},
        {"name": "Sạc nhanh 20W"},
    ]
    assert search_results_need_advanced(results, "iphone 16 pro max 256")


if __name__ == "__main__":
    test_need_advanced_empty()
    test_need_advanced_single()
    test_need_advanced_noisy()
    print("OK — advanced search tests passed")
