"""Test template browse list — link inline trong Gợi ý."""
from __future__ import annotations

from cps_bot.browse.fast_reply import build_browse_list_reply


def test_browse_list_reply_inline_product_links() -> None:
    detail = {
        "category_filter_list_mode": True,
        "category_filter_name": "Điện thoại",
        "product_count": 12,
        "category_filter_url": "https://cellphones.com.vn/mobile.html?price=5000000-7000000",
    }
    search_results = [
        {
            "name": "Samsung Galaxy A17 5G 8GB 128GB",
            "price": "5.890.000₫",
            "stock_status": "Còn hàng (947)",
            "url": "https://cellphones.com.vn/dien-thoai-samsung-galaxy-a17-5g.html",
        },
        {
            "name": "Nubia Neo 5 5G 8GB 128GB",
            "price": "6.990.000₫",
            "stock_status": "Còn hàng (54)",
            "url_path": "/dien-thoai-nubia-neo-5-5g.html",
        },
    ]
    reply = build_browse_list_reply(
        "Điện thoại cho phụ huynh tầm giá 5 - 7 triệu",
        detail,
        search_results,
    )

    assert "Gợi ý" in reply
    assert "Samsung Galaxy A17 5G" in reply
    assert "dien-thoai-samsung-galaxy-a17-5g.html" in reply
    assert "dien-thoai-nubia-neo-5-5g.html" in reply
    assert "🔗 Xem đầy đủ:" in reply
    assert "mobile.html?price=5000000-7000000" in reply
    assert "🔗 Link sản phẩm" not in reply

    # Link ngay sau dòng gợi ý tương ứng
    lines = reply.splitlines()
    idx_a17 = next(i for i, line in enumerate(lines) if "Samsung Galaxy A17" in line)
    assert "dien-thoai-samsung-galaxy-a17-5g.html" in lines[idx_a17 + 1]
