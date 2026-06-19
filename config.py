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
# 1 = trong topic đã @bot, trả lời tin tiếp theo không cần @ lại (cần quyền Lark)
LARK_THREAD_AUTO_REPLY = os.getenv("LARK_THREAD_AUTO_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Tên hiển thị bot khi @ (phân cách bằng dấu phẩy) — vd: Snake Bot,Gemini Bot
LARK_BOT_MENTION_NAMES = os.getenv("LARK_BOT_MENTION_NAMES", "").strip()
# Lark Base — lưu feedback từ nút card
LARK_BITABLE_ENABLED = os.getenv("LARK_BITABLE_ENABLED", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LARK_BITABLE_APP_TOKEN = os.getenv("LARK_BITABLE_APP_TOKEN", "").strip()
LARK_BITABLE_TABLE_ID = os.getenv("LARK_BITABLE_TABLE_ID", "").strip()
# Giá trị single-select — phải khớp option trong Base
LARK_BITABLE_CATEGORY = os.getenv("LARK_BITABLE_CATEGORY", "Bot tư vấn").strip()
LARK_BITABLE_STATUS = os.getenv("LARK_BITABLE_STATUS", "Mới").strip()
LARK_BITABLE_COL_TOPIC_LINK = os.getenv("LARK_BITABLE_COL_TOPIC_LINK", "Link topic").strip()
# text = cột Text (chuỗi URL) | url = cột Hyperlink (object link+text)
LARK_BITABLE_TOPIC_LINK_FORMAT = os.getenv(
    "LARK_BITABLE_TOPIC_LINK_FORMAT", "text"
).strip().lower()
# Group nhận thông báo khi có feedback mới (chat_id dạng oc_...)
LARK_FEEDBACK_NOTIFY_CHAT_ID = os.getenv("LARK_FEEDBACK_NOTIFY_CHAT_ID", "").strip()

# Mã tỉnh/thành cho API tìm kiếm Cellphones (30 = TP.HCM)
CPS_PROVINCE_ID = int(os.getenv("CPS_PROVINCE_ID", "30"))

# Domain web hiển thị link sản phẩm (url_path → URL đầy đủ)
CPS_WEB_BASE_URL = os.getenv(
    "CPS_WEB_BASE_URL",
    "https://cellphones.com.vn",
).strip().rstrip("/")

# GraphQL CPS — resolve URL + chi tiết sản phẩm (production = dữ liệu đầy đủ)
CPS_GRAPHQL_URL_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_URL_ENDPOINT",
    "https://api.cellphones.com.vn/graphql-url/graphql/query",
).strip()
CPS_GRAPHQL_V2_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_V2_ENDPOINT",
    "https://api.cellphones.com.vn/v2/graphql/query",
).strip()
CPS_GRAPHQL_V2_PRODUCTION = "https://api.cellphones.com.vn/v2/graphql/query"
CPS_GRAPHQL_SEARCH_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_SEARCH_ENDPOINT",
    "https://api.cellphones.com.vn/graphql-search/v2/graphql/query",
).strip()
# Tồn theo cửa hàng (shops_stock) — graphql-dashboard
CPS_GRAPHQL_DASHBOARD_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_DASHBOARD_ENDPOINT",
    "https://api.cellphones.com.vn/graphql-dashboard/graphql/query",
).strip()
CPS_GRAPHQL_CUSTOMER_ENDPOINT = os.getenv(
    "CPS_GRAPHQL_CUSTOMER_ENDPOINT",
    "https://api.cellphones.com.vn/graphql-customer/graphql/query",
).strip()

# Main menu → category map (url_info, throttle + sync 0h hàng ngày)
CPS_MAIN_MENU_ID = int(os.getenv("CPS_MAIN_MENU_ID", "5"))
MENU_CATEGORY_FETCH_DELAY_SEC = float(os.getenv("MENU_CATEGORY_FETCH_DELAY_SEC", "3"))
MENU_CATEGORY_MAP_PATH = os.getenv(
    "MENU_CATEGORY_MAP_PATH",
    str(Path(__file__).resolve().parent / "data" / "menu_category_map.json"),
).strip()

# Session persistence (SQLite) — giữ context qua restart
SESSION_PERSISTENCE = os.getenv("SESSION_PERSISTENCE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SESSION_DB_PATH = os.getenv(
    "SESSION_DB_PATH",
    str(Path(__file__).resolve().parent / "sessions.db"),
).strip()

# Cart / Payment / SSO — trả góp (cps-nuxt-standard .prod.env)
CPS_API_BASE_URL = os.getenv(
    "CPS_API_BASE_URL",
    "https://api.cellphones.com.vn",
).strip().rstrip("/")
CPS_PAYMENT_VER = os.getenv("CPS_PAYMENT_VER", "v3").strip()
CPS_SSO_GUEST_TOKEN_URL = os.getenv(
    "CPS_SSO_GUEST_TOKEN_URL",
    "https://api.smember.com.vn/sso/v1/auth/guest-token",
).strip()

# SerpAPI Google search (site:cellphones.com.vn) — mặc định tắt; ưu tiên CPS advanced_search
SERPAPI_ENABLED = os.getenv("SERPAPI_ENABLED", "0").strip() in {"1", "true", "yes", "on"}
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
SERPAPI_ENDPOINT = os.getenv("SERPAPI_ENDPOINT", "https://serpapi.com/search.json").strip()
SERPAPI_FALLBACK_TO_CPS_SEARCH = os.getenv(
    "SERPAPI_FALLBACK_TO_CPS_SEARCH",
    "0",
).strip() in {"1", "true", "yes", "on"}

# LLM: gemini | deepseek | byteplus
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

# Model Gemini — mặc định gemini-3.5-flash (GA, khuyến nghị production 2026-05)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# DeepSeek (OpenAI-compatible) — dùng khi LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL",
    "https://api.deepseek.com/v1",
).strip()

# BytePlus ModelArk (OpenAI-compatible) — dùng khi LLM_PROVIDER=byteplus
# BYTEPLUS_API_MODE: modelark (mặc định) | coding (Coding Plan subscription)
BYTEPLUS_API_MODE = os.getenv("BYTEPLUS_API_MODE", "modelark").strip().lower()
BYTEPLUS_API_KEY = os.getenv("BYTEPLUS_API_KEY", "").strip()


def _byteplus_default_base_url() -> str:
    if BYTEPLUS_API_MODE == "coding":
        return "https://ark.ap-southeast.bytepluses.com/api/coding/v3"
    return "https://ark.ap-southeast.bytepluses.com/api/v3"


def _byteplus_default_model() -> str:
    if BYTEPLUS_API_MODE == "coding":
        return "ark-code-latest"
    return ""


BYTEPLUS_MODEL = os.getenv("BYTEPLUS_MODEL", _byteplus_default_model()).strip()
# Endpoint ID từ Console (ep-xxx) — ưu tiên hơn BYTEPLUS_MODEL khi gọi API
BYTEPLUS_ENDPOINT_ID = os.getenv("BYTEPLUS_ENDPOINT_ID", "").strip()
BYTEPLUS_BASE_URL = os.getenv(
    "BYTEPLUS_BASE_URL",
    _byteplus_default_base_url(),
).strip()
