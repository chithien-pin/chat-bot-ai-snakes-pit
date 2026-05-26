"""
Module giao tiếp với Google Gemini API.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import google.generativeai as genai

from config import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Bạn là trợ lý tư vấn sản phẩm công nghệ. Dựa trên dữ liệu sản phẩm dưới đây "
    "từ cellphones.com.vn, hãy trả lời câu hỏi của khách hàng một cách rõ ràng, "
    "ngắn gọn, đúng trọng tâm bằng tiếng Việt. "
    "Chỉ dùng thông tin có trong dữ liệu; nếu thiếu thì nói rõ là không có trong dữ liệu. "
    "Có thể dùng emoji phù hợp. Tránh markdown phức tạp (không dùng bảng)."
)

# Cấu hình SDK một lần khi import
genai.configure(api_key=GEMINI_API_KEY)

# Thứ tự thử model (ưu tiên cấu hình, sau đó các bản flash miễn phí)
MODEL_FALLBACKS = (
    GEMINI_MODEL,
    "gemini-1.5-flash",
    "gemini-2.0-flash",
    "gemini-flash-latest",
)


def _serialize_product_data(product_data: dict[str, Any]) -> str:
    """Chuyển dict sản phẩm sang JSON dễ đọc cho model."""
    return json.dumps(product_data, ensure_ascii=False, indent=2)


def analyze_product(user_question: str, product_data: dict[str, Any]) -> str:
    """
    Gọi Gemini với system prompt + dữ liệu sản phẩm + câu hỏi người dùng.
    """
    user_question = user_question.strip()
    data_text = _serialize_product_data(product_data)

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"=== DỮ LIỆU SẢN PHẨM ===\n{data_text}\n\n"
        f"=== CÂU HỎI KHÁCH HÀNG ===\n{user_question}\n\n"
        "Hãy trả lời:"
    )

    last_error: Exception | None = None
    tried: list[str] = []

    for model_name in MODEL_FALLBACKS:
        if not model_name or model_name in tried:
            continue
        tried.append(model_name)
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            text = (response.text or "").strip()
            if text:
                if model_name != GEMINI_MODEL:
                    logger.info(
                        "Dùng model dự phòng: %s (cấu hình: %s)",
                        model_name,
                        GEMINI_MODEL,
                    )
                return text
            last_error = ValueError("Phản hồi rỗng từ Gemini")
        except Exception as exc:
            last_error = exc
            logger.warning("Model %s lỗi: %s", model_name, exc)
            continue

    logger.exception("Lỗi gọi Gemini sau khi thử %s", tried)
    detail = str(last_error) if last_error else "không rõ"
    return (
        "⚠️ Không thể kết nối Gemini lúc này. "
        f"Chi tiết kỹ thuật: {detail}"
    )
