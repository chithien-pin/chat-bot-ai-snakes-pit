"""Test URL sản phẩm trong search_results."""
from __future__ import annotations

from scraper import (
    format_product_links_appendix,
    graphql_product_url,
    normalize_search_result,
    product_url_from_record,
)


def test_url_from_url_key() -> None:
    record = normalize_search_result(
        {
            "name": "iPhone 17 Pro Max",
            "url_key": "dien-thoai-iphone-17-pro-max",
        }
    )
    assert record["url"].endswith("dien-thoai-iphone-17-pro-max.html")


def test_graphql_product_url() -> None:
    url = graphql_product_url(
        {"url_path": "/dien-thoai-iphone-17-pro-max.html"}
    )
    assert "iphone-17-pro-max" in url


def test_links_appendix() -> None:
    block = format_product_links_appendix(
        [
            {
                "name": "SP A",
                "url": "https://cellphones.com.vn/sp-a.html",
            },
            {
                "name": "SP B",
                "url_path": "/sp-b.html",
            },
        ]
    )
    assert "SP A" in block
    assert "sp-a.html" in block
    assert "sp-b.html" in block
    assert product_url_from_record({"url_path": "/x.html"}) != ""


if __name__ == "__main__":
    test_url_from_url_key()
    test_graphql_product_url()
    test_links_appendix()
    print("OK — product link tests passed")
