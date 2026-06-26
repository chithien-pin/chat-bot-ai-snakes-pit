"""Tests for API trace curl builder."""
from __future__ import annotations

from cps_bot.core.api_trace import build_curl_get, build_curl_post, record_api_call, trace_phase


def test_build_curl_post() -> None:
    curl = build_curl_post(
        "https://api.example.com/graphql",
        json_body={"query": "query Q { x }", "variables": {"id": 1}},
    )
    assert "curl -sS -X POST" in curl
    assert "api.example.com/graphql" in curl
    assert "query Q" in curl


def test_build_curl_get() -> None:
    curl = build_curl_get("https://serpapi.com/search.json", params={"q": "iphone", "engine": "google"})
    assert curl.startswith("curl -sS")
    assert "q=iphone" in curl


def test_record_api_call_generates_curl() -> None:
    stats: dict = {"api_calls_detail": []}
    record_api_call(
        stats,
        name="Test",
        operation="getProductDataDetail",
        endpoint="https://api.cellphones.com.vn/v2/graphql/query",
        graphql_query="query getProductDataDetail($id: ID!) { product(id: $id) { general { name } } }",
        variables={"id": "123", "provinceId": 30},
    )
    calls = stats.get("api_calls_detail") or []
    assert len(calls) == 1
    assert calls[0].get("curl")
    assert "getProductDataDetail" in calls[0]["curl"]
    assert calls[0].get("phase") == "fetch"


def test_trace_phase_tag() -> None:
    stats: dict = {"api_calls_detail": []}
    with trace_phase("shop_stock"):
        record_api_call(stats, name="shops", operation="SHOP_STOCK")
    assert stats["api_calls_detail"][0]["phase"] == "shop_stock"


if __name__ == "__main__":
    test_build_curl_post()
    test_build_curl_get()
    test_record_api_call_generates_curl()
    print("OK — api trace tests passed")
