"""
Nội dung hướng dẫn chat — dùng chung web /help modal, Telegram /help, Lark /help.
"""
from __future__ import annotations

CHAT_HELP_BODY = """Cách đặt câu hỏi để bot tìm đúng sản phẩm và trả lời chính xác nhất:

1️⃣ Ghi rõ sản phẩm
• Nêu hãng + model + dung lượng + màu (nếu có).
• Nên: Giá iPhone 17 Pro Max 256GB hôm nay?
• Tránh: "điện thoại nào ngon" (trừ khi bạn muốn gợi ý theo ngân sách).

2️⃣ Hỏi tiếp trong cùng hội thoại
• Sau câu đầu, hỏi ngắn — bot nhớ sản phẩm đang thảo luận.
• Ví dụ: Còn hàng shop không? · Giá Smember bao nhiêu? · Trả góp được không? · Còn màu nào khác?

3️⃣ Tồn cửa hàng
• Ghi rõ sản phẩm + quận/tỉnh hoặc địa chỉ gần bạn.
• Ví dụ: Shop quận 1 còn iPhone 16 Pro 256GB màu Titan không?
• Bot có thể hỏi lại tỉnh/thành — trả lời để tra tồn chính xác hơn.

4️⃣ Trả góp & thanh toán
• Nêu sản phẩm + hình thức: CTTC (Home Credit, MCredit…), thẻ tín dụng, Kredivo/Fundiin.
• Với thẻ: thêm ngân hàng + kỳ hạn + loại thẻ (Visa/Master/JCB).
• Ví dụ: Trả góp Techcombank iPhone 17 256GB 6 tháng thẻ Visa.

5️⃣ So sánh & tư vấn chọn mua
• So sánh: So sánh iPhone 17 Pro Max và Galaxy S26 Ultra.
• Theo ngân sách: Laptop gaming dưới 20 triệu · Điện thoại tầm 10 triệu.
• Theo danh mục + giá: iPhone dưới 20 triệu.

6️⃣ Nên tránh
• Câu ngoài phạm vi CellphoneS (thời tiết, viết code, tin tức chung…).
• Đổi sang sản phẩm khác giữa chừng mà không nêu tên mới.
• Chỉ gõ "giá sao" khi chưa hỏi sản phẩm nào trong phiên chat.

Bot hỗ trợ: giá & KM (Smember/HSSV), tồn cửa hàng, thu cũ đổi mới, trả góp, bảo hành, so sánh 2 SP, thông số & tư vấn chọn mua.

⚠️ Giá, khuyến mãi và tồn kho lấy từ dữ liệu CellphoneS tại thời điểm tra cứu — vui lòng xác nhận lại trên cellphones.com.vn trước khi quyết định mua."""

CHAT_HELP_SHORT = (
    "📖 Mình hỗ trợ tra cứu sản phẩm trên cellphones.com.vn.\n\n"
    "💡 Ghi rõ hãng + model + dung lượng/màu; hỏi tiếp ngắn trong cùng hội thoại "
    "(còn hàng, giá Smember, trả góp…).\n\n"
    "Gõ /help để xem hướng dẫn chi tiết cách chat hiệu quả."
)

TELEGRAM_HELP_COMMANDS = "*Lệnh:* /start · /help · /clear · /chatid"

LARK_HELP_COMMANDS = "Lệnh: /start · /help · /clear · /chatid"

LARK_TOPIC_NOTE = (
    "\n\nTrong topic Lark: @bot một lần, các câu tiếp theo không cần @ lại."
)


def chat_help_plain(*, lark: bool = False) -> str:
    """Hướng dẫn đầy đủ — Lark (plain text)."""
    parts = [
        "📖 Hướng dẫn chat với CellphoneS AI\n\n",
        CHAT_HELP_BODY,
        "\n\n",
        LARK_HELP_COMMANDS if lark else "Lệnh: /start · /help · /clear",
    ]
    if lark:
        parts.append(LARK_TOPIC_NOTE)
    return "".join(parts)


def chat_help_telegram() -> str:
    """Hướng dẫn đầy đủ — Telegram Markdown (legacy)."""
    return (
        "📖 *Hướng dẫn chat với CellphoneS AI*\n\n"
        "Cách đặt câu hỏi để bot tìm đúng sản phẩm và trả lời chính xác nhất:\n\n"
        "1️⃣ *Ghi rõ sản phẩm*\n"
        "• Nêu hãng \\+ model \\+ dung lượng \\+ màu \\(nếu có\\)\\.\n"
        "• _Nên:_ Giá iPhone 17 Pro Max 256GB hôm nay?\n"
        "• _Tránh:_ điện thoại nào ngon \\(trừ khi hỏi theo ngân sách\\)\\.\n\n"
        "2️⃣ *Hỏi tiếp trong cùng hội thoại*\n"
        "• Bot nhớ sản phẩm đang thảo luận\\.\n"
        "• _Còn hàng shop không?_ · _Giá Smember?_ · _Trả góp được không?_ · _Còn màu nào khác?_\n\n"
        "3️⃣ *Tồn cửa hàng*\n"
        "• Ghi SP \\+ quận/tỉnh hoặc địa chỉ gần bạn\\.\n"
        "• _Shop quận 1 còn iPhone 16 Pro 256GB màu Titan không?_\n\n"
        "4️⃣ *Trả góp & thanh toán*\n"
        "• CTTC \\(Home Credit, MCredit…\\), thẻ tín dụng, Kredivo/Fundiin\\.\n"
        "• Thẻ: thêm ngân hàng \\+ kỳ hạn \\+ Visa/Master/JCB\\.\n"
        "• _Trả góp Techcombank iPhone 17 256GB 6 tháng thẻ Visa_\n\n"
        "5️⃣ *So sánh & tư vấn*\n"
        "• _So sánh iPhone 17 Pro Max và Galaxy S26 Ultra_\n"
        "• _Laptop gaming dưới 20 triệu_ · _iPhone dưới 20 triệu_\n\n"
        "6️⃣ *Nên tránh*\n"
        "• Câu ngoài CellphoneS \\(thời tiết, code, tin tức…\\)\n"
        "• Đổi SP khác giữa chừng mà không nêu tên mới\n"
        "• Chỉ _giá sao_ khi chưa hỏi SP nào\n\n"
        f"{TELEGRAM_HELP_COMMANDS}\n\n"
        "⚠️ Giá và tồn kho có thể thay đổi — xem thêm trên website\\."
    )
