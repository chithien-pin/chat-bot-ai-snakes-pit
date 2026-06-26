"""
Unit test ma trận kịch bản nghiệp vụ — bắt buộc pass trước mỗi lần deploy/update.

Chạy: ./scripts/run_tests.sh
"""
from __future__ import annotations

import re
import unittest
import unicodedata

from cps_bot.cps.cps_api import classify_question_scenarios
from cps_bot.llm.gemini_client import extract_compare_product_queries, extract_search_keywords
from tests.scenario_matrix import SCENARIO_MATRIX, ScenarioCase


def _fold(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def assert_scenarios(case: ScenarioCase) -> None:
    got = classify_question_scenarios(case.query)
    for key in case.scenarios:
        if not got.get(key):
            active = [k for k, v in got.items() if v]
            raise AssertionError(
                f"[{case.id}] {case.query!r}: thiếu scenario {key!r}. Có: {active}"
            )
    for key in case.scenarios_exclude:
        if got.get(key):
            raise AssertionError(
                f"[{case.id}] {case.query!r}: không mong đợi scenario {key!r}"
            )


def assert_keywords(case: ScenarioCase) -> None:
    if case.compare_parts:
        parts = extract_compare_product_queries(case.query)
        if len(parts) != 2:
            raise AssertionError(
                f"[{case.id}] compare: cần 2 phần, có {parts!r}"
            )
        folded_parts = [_fold(p) for p in parts]
        for expected in case.compare_parts:
            if not any(_fold(expected) in p for p in folded_parts):
                raise AssertionError(
                    f"[{case.id}] compare thiếu {expected!r} trong {parts!r}"
                )
        return

    if not case.keywords_contains and not case.keywords_exact and not case.keywords_is_filter_url:
        return

    kw = extract_search_keywords(case.query, use_llm=False).strip()
    if not kw:
        raise AssertionError(f"[{case.id}] từ khóa rỗng cho {case.query!r}")

    if case.keywords_is_filter_url:
        if ".html" not in kw or "price=" not in kw:
            raise AssertionError(
                f"[{case.id}] mong đợi filter URL, có {kw!r}"
            )
        return

    if case.keywords_exact:
        if _fold(kw) != _fold(case.keywords_exact):
            raise AssertionError(
                f"[{case.id}] kw: {kw!r} != {case.keywords_exact!r}"
            )
        return

    folded = _fold(kw)
    for token in case.keywords_contains:
        if _fold(token) not in folded:
            raise AssertionError(
                f"[{case.id}] kw {kw!r} thiếu {token!r}"
            )

    if re.search(r"bao nhiêu|hôm nay|check giá", folded):
        raise AssertionError(f"[{case.id}] kw còn noise: {kw!r}")
    if ".html?" in kw:
        raise AssertionError(f"[{case.id}] kw là category URL: {kw!r}")


def _make_scenario_test(case: ScenarioCase):
    def test(self) -> None:
        assert_scenarios(case)

    test.__doc__ = f"{case.group}: {case.query[:60]}"
    return test


def _make_keyword_test(case: ScenarioCase):
    def test(self) -> None:
        assert_scenarios(case)
        assert_keywords(case)

    test.__doc__ = f"keywords {case.id}: {case.query[:50]}"
    return test


class TestScenarioClassification(unittest.TestCase):
    pass


class TestKeywordExtraction(unittest.TestCase):
    pass


for _case in SCENARIO_MATRIX:
    setattr(
        TestScenarioClassification,
        f"test_{_case.id}_scenario",
        _make_scenario_test(_case),
    )
    if (
        _case.keywords_contains
        or _case.keywords_exact
        or _case.keywords_is_filter_url
        or _case.compare_parts
    ):
        setattr(
            TestKeywordExtraction,
            f"test_{_case.id}_keywords",
            _make_keyword_test(_case),
        )


if __name__ == "__main__":
    unittest.main()
