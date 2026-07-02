"""Test hậu kiểm số liệu câu trả lời."""
from __future__ import annotations

from cps_bot.llm.answer_guard import (
    check_answer_numbers,
    collect_known_numbers,
    extract_currency_numbers,
    parse_price_to_vnd,
)


def test_parse_price_formats() -> None:
    assert parse_price_to_vnd("22.990.000đ") == 22990000
    assert parse_price_to_vnd("990k") == 990000
    assert parse_price_to_vnd("12.5 triệu") == 12500000


def test_extract_currency_numbers() -> None:
    nums = extract_currency_numbers("Giá 22.990.000đ, trả trước 990k")
    assert 22990000 in nums
    assert 990000 in nums


def test_check_answer_numbers_match() -> None:
    payload = {
        "primary_product": {
            "price": "22.990.000đ",
            "old_price": "24.990.000đ",
        }
    }
    answer = "Giá hiện tại 22.990.000đ, giá gốc 24.990.000đ."
    assert check_answer_numbers(answer, payload) == []


def test_check_answer_numbers_mismatch() -> None:
    payload = {
        "primary_product": {"price": "22.990.000đ"},
    }
    answer = "Giá chỉ còn 19.990.000đ thôi nhé!"
    mismatches = check_answer_numbers(answer, payload)
    assert 19990000 in mismatches


def test_check_answer_no_numbers() -> None:
    payload = {"primary_product": {"price": "22.990.000đ"}}
    assert check_answer_numbers("Máy còn hàng, bạn ghé shop nhé!", payload) == []


def test_collect_known_from_search_results() -> None:
    payload = {
        "search_results": [
            {"name": "A", "price": "10.990.000đ"},
            {"name": "B", "price": "12.990.000đ"},
        ]
    }
    known = collect_known_numbers(payload)
    assert 10990000 in known
    assert 12990000 in known


if __name__ == "__main__":
    test_parse_price_formats()
    test_extract_currency_numbers()
    test_check_answer_numbers_match()
    test_check_answer_numbers_mismatch()
    test_check_answer_no_numbers()
    test_collect_known_from_search_results()
    print("OK — answer guard tests passed")
