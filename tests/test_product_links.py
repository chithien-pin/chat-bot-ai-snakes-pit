"""Test URL sản phẩm trong search_results."""
from __future__ import annotations

from cps_bot.cps.scraper import (
    format_product_links_appendix,
    graphql_product_url,
    normalize_search_result,
    product_url_from_record,
    should_attach_product_links_appendix,
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


def test_appendix_not_for_single_product_search_noise() -> None:
    detail = {"name": "iPhone 15 128GB Xanh dương", "product_id": "123"}
    assert not should_attach_product_links_appendix(
        detail,
        ambiguous_search=False,
    )


def test_appendix_for_browse_list() -> None:
    detail = {"stock_browse_list_mode": True}
    assert should_attach_product_links_appendix(detail)


def test_appendix_skipped_when_ambiguous() -> None:
    detail = {"name": "iPhone 15"}
    assert not should_attach_product_links_appendix(
        detail,
        ambiguous_search=True,
    )


def test_appendix_for_compare_mode() -> None:
    assert should_attach_product_links_appendix(None, compare_mode=True)


def test_appendix_skipped_when_browse_fetch_failed() -> None:
    """Scenario budget_browse nhưng fetch thất bại → không gắn link SP lạ."""
    detail = {"name": "Máy ảnh Canon EOS R50"}
    assert not should_attach_product_links_appendix(
        detail,
        scenarios={"budget_browse": True},
    )


if __name__ == "__main__":
    test_url_from_url_key()
    test_graphql_product_url()
    test_links_appendix()
    test_appendix_skipped_when_browse_fetch_failed()
    print("OK — product link tests passed")
