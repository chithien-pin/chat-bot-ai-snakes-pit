"""
Cấu hình bot — đọc từ biến môi trường (.env) hoặc giá trị mặc định.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Tải file .env cùng thư mục dự án
load_dotenv(Path(__file__).resolve().parent / ".env")

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "your_telegram_bot_token_here",
)
GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "your_gemini_api_key_here",
)
# Để trống hoặc không set nếu muốn bot phản hồi mọi chat
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID", "").strip()

# Mã tỉnh/thành cho API tìm kiếm Cellphones (30 = TP.HCM)
CPS_PROVINCE_ID = int(os.getenv("CPS_PROVINCE_ID", "30"))

# Model Gemini
# Mặc định gemini-2.0-flash (miễn phí). Có thể đặt gemini-1.5-flash nếu API hỗ trợ.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
