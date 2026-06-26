"""Test disambiguation helpers."""
from __future__ import annotations

from cps_bot.llm.disambiguation import build_disambiguation_message, resolve_disambiguation_choice


def test_resolve_by_number() -> None:
    results = [
        {"name": "iPhone 16 Pro Max", "price": "30.000.000₫", "url": "https://cellphones.com.vn/a.html"},
        {"name": "iPhone 16 Pro", "price": "25.000.000₫", "url": "https://cellphones.com.vn/b.html"},
    ]
    pick = resolve_disambiguation_choice("2", results)
    assert pick and "Pro" in pick["name"] and "Max" not in pick["name"]


def test_build_message() -> None:
    results = [
        {"name": "A", "url": "https://cellphones.com.vn/a.html"},
        {"name": "B", "url": "https://cellphones.com.vn/b.html"},
    ]
    msg = build_disambiguation_message(results)
    assert "1." in msg and "2." in msg


if __name__ == "__main__":
    test_resolve_by_number()
    test_build_message()
    print("OK — disambiguation tests passed")
