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

# Lark Bot (lark_bot.py)
LARK_APP_ID = os.getenv("LARK_APP_ID", "").strip()
LARK_APP_SECRET = os.getenv("LARK_APP_SECRET", "").strip()
LARK_CHAT_ID = os.getenv("LARK_CHAT_ID", "").strip()
# lark = Lark quốc tế, feishu = Feishu Trung Quốc
LARK_API_DOMAIN = os.getenv("LARK_API_DOMAIN", "lark").strip().lower()

# Mã tỉnh/thành cho API tìm kiếm Cellphones (30 = TP.HCM)
CPS_PROVINCE_ID = int(os.getenv("CPS_PROVINCE_ID", "30"))

# GraphQL CPS — resolve URL + chi tiết sản phẩm
CPS_GRAPHQL_URL_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_URL_ENDPOINT",
    "https://api-stag.cps.onl/graphql-url/graphql/query",
).strip()
CPS_GRAPHQL_V2_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_V2_ENDPOINT",
    "https://api-stag.cps.onl/v2/graphql/query",
).strip()

# Model Gemini
# Mặc định gemini-2.5-flash (free tier ổn). 1.5 đã ngừng; 3.5 hay bị 429.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
