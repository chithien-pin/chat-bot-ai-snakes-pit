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
CATEGORY_ATTRIBUTES_MAP_PATH = os.getenv(
    "CATEGORY_ATTRIBUTES_MAP_PATH",
    str(Path(__file__).resolve().parent / "data" / "category_attributes_map.json"),
).strip()
CATEGORY_ATTRIBUTES_FETCH_DELAY_SEC = float(
    os.getenv("CATEGORY_ATTRIBUTES_FETCH_DELAY_SEC", "3")
)

# Metrics + dashboard
METRICS_LOG_PATH = os.getenv(
    "METRICS_LOG_PATH",
    str(Path(__file__).resolve().parent / "metrics.log"),
).strip()
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0").strip()
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "").strip()
DASHBOARD_AUTH_SALT = os.getenv("DASHBOARD_AUTH_SALT", "cps-bot-dashboard").strip()

# Product map — tra product_id trước GraphQL search
PRODUCT_MAP_PATH = os.getenv(
    "PRODUCT_MAP_PATH",
    str(Path(__file__).resolve().parent / "data" / "product_map.map"),
).strip()
PRODUCT_MAP_ENABLED = os.getenv("PRODUCT_MAP_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
PRODUCT_MAP_MIN_SCORE = int(os.getenv("PRODUCT_MAP_MIN_SCORE", "25"))
# Độ khớp tối thiểu (0–1) giữa câu hỏi và tên SP map — dưới ngưỡng → fallback search API
PRODUCT_MAP_MIN_CONFIDENCE = float(os.getenv("PRODUCT_MAP_MIN_CONFIDENCE", "0.6"))

# Latency — browse list trả template (không LLM); payload LLM gọn hơn
FAST_BROWSE_REPLY = os.getenv("FAST_BROWSE_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Câu hỏi giá/KM 1 SP cụ thể — template từ payload, không gọi LLM phân tích
FAST_PRICE_REPLY = os.getenv("FAST_PRICE_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Câu hỏi tồn cửa hàng thuần — template từ shops_stock, không LLM
FAST_SHOP_STOCK_REPLY = os.getenv("FAST_SHOP_STOCK_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# So sánh 2 SP — template 2 cột, không LLM
FAST_COMPARE_REPLY = os.getenv("FAST_COMPARE_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Trả góp 1 SP — template từ payload installment, không LLM phân tích
FAST_INSTALLMENT_REPLY = os.getenv("FAST_INSTALLMENT_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Phụ kiện/combo mua kèm 1 SP — template, không LLM phân tích
FAST_COMBO_REPLY = os.getenv("FAST_COMBO_REPLY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SLIM_LLM_PAYLOAD = os.getenv("SLIM_LLM_PAYLOAD", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_MAX_SEARCH_RESULTS = int(os.getenv("LLM_MAX_SEARCH_RESULTS", "5"))

# LLM phân loại intent (chặn câu ngoài CellphoneS) + chuẩn hóa từ khóa/đồng nghĩa
LLM_INTENT_CLASSIFY = os.getenv("LLM_INTENT_CLASSIFY", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_KEYWORD_NORMALIZE = os.getenv("LLM_KEYWORD_NORMALIZE", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
LLM_QUERY_ROUTER = os.getenv("LLM_QUERY_ROUTER", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Feedback training — admin duyệt feedback → few-shot LLM
FEEDBACK_TRAINING_PATH = os.getenv(
    "FEEDBACK_TRAINING_PATH",
    str(Path(__file__).resolve().parent / "data" / "feedback_training.jsonl"),
).strip()
FEEDBACK_TRAINING_ENABLED = os.getenv("FEEDBACK_TRAINING_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FEEDBACK_TRAINING_MAX_EXAMPLES = int(os.getenv("FEEDBACK_TRAINING_MAX_EXAMPLES", "6"))

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
# Thời gian giữ ngữ cảnh hội thoại (giờ) — mặc định 24h/session
SESSION_TTL_HOURS = float(os.getenv("SESSION_TTL_HOURS", "24"))
SESSION_TTL_SECONDS = max(int(SESSION_TTL_HOURS * 3600), 60)
USER_NAMES_CACHE_PATH = os.getenv(
    "USER_NAMES_CACHE_PATH",
    str(Path(__file__).resolve().parent / "var" / "user_names.json"),
).strip()

# Cart / Payment / SSO — trả góp (cps-nuxt-standard .prod.env)
CPS_API_BASE_URL = os.getenv(
    "CPS_API_BASE_URL",
    "https://api.cellphones.com.vn",
).strip().rstrip("/")
# Gợi ý phụ kiện / sản phẩm mua cùng (recommendation API)
CPS_RECOMMENDATION_ENABLED = os.getenv("CPS_RECOMMENDATION_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
CPS_RECOMMENDATION_MAX_PRODUCTS = int(os.getenv("CPS_RECOMMENDATION_MAX_PRODUCTS", "5"))
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


def active_llm_model() -> str:
    """Model/endpoint đang cấu hình cho LLM_PROVIDER."""
    if LLM_PROVIDER == "deepseek":
        return DEEPSEEK_MODEL
    if LLM_PROVIDER == "byteplus":
        return BYTEPLUS_ENDPOINT_ID or BYTEPLUS_MODEL or "byteplus"
    return GEMINI_MODEL
