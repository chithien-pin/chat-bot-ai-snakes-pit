"""
Gọi DeepSeek API (OpenAI-compatible chat completions).
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


def generate_chat(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Gửi prompt tới DeepSeek; trả (text, metadata usage)."""
    if not DEEPSEEK_API_KEY:
        logger.error("DEEPSEEK_API_KEY chưa cấu hình")
        return None, {}

    model_name = (model or DEEPSEEK_MODEL).strip()
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0.7,
    }

    try:
        with httpx.Client(timeout=120.0) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        logger.warning("DeepSeek %s lỗi: %s", model_name, exc)
        return None, {}

    choices = data.get("choices") or []
    if not choices:
        return None, {"model": model_name}

    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    usage = data.get("usage") or {}
    meta: dict[str, Any] = {
        "model": data.get("model") or model_name,
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    if not text:
        return None, meta
    return text, meta
