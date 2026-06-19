"""
Gọi BytePlus ModelArk API (OpenAI-compatible chat completions).

Hai chế độ (BYTEPLUS_API_MODE):
- modelark: /api/v3 — model ID (gpt-oss-120b-250805) hoặc Endpoint ID (ep-xxx)
- coding:   /api/coding/v3 — Coding Plan (ark-code-latest, kimi-k2.5, …)

Tài liệu:
- ModelArk: https://docs.byteplus.com/en/docs/ModelArk/1330626
- gpt-oss-120b: https://docs.byteplus.com/en/docs/ModelArk/1924456
- Coding Plan: https://docs.byteplus.com/en/docs/ModelArk/1928261
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config import (
    BYTEPLUS_API_KEY,
    BYTEPLUS_API_MODE,
    BYTEPLUS_BASE_URL,
    BYTEPLUS_ENDPOINT_ID,
    BYTEPLUS_MODEL,
)

logger = logging.getLogger(__name__)

_MODELARK_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
_CODING_BASE = "https://ark.ap-southeast.bytepluses.com/api/coding/v3"

# Alias tên ngắn → Model ID chính thức trên Console
_MODEL_ALIASES: dict[str, str] = {
    "gpt-oss-120b": "gpt-oss-120b-250805",
    "gpt-oss-120b-250805": "gpt-oss-120b-250805",
}

# Model chỉ gọi được qua Coding Plan (/api/coding/v3)
_CODING_ONLY_MODELS = frozenset(
    {
        "ark-code-latest",
        "bytedance-seed-code",
        "glm-4.7",
        "kimi-k2.5",
        "kimi-k2",
        "kimi-k2-thinking",
    }
)


def resolve_byteplus_settings(
    model_override: str | None = None,
) -> tuple[str, str, str]:
    """
    Trả (api_mode, base_url, model_id) đã chuẩn hóa theo model/endpoint.
    Tự chọn /api/v3 vs /api/coding/v3 khi model thuộc Coding Plan.
    """
    endpoint_id = (BYTEPLUS_ENDPOINT_ID or "").strip()
    raw_model = (model_override or BYTEPLUS_MODEL or "").strip()

    if endpoint_id:
        model_id = endpoint_id
        mode = "modelark"
    elif raw_model.lower() in _CODING_ONLY_MODELS:
        model_id = raw_model
        mode = "coding"
    else:
        model_id = _MODEL_ALIASES.get(raw_model, raw_model)
        mode = "modelark" if BYTEPLUS_API_MODE != "coding" else "coding"

    if BYTEPLUS_API_MODE == "coding" and not endpoint_id:
        mode = "coding"

    expected_base = _CODING_BASE if mode == "coding" else _MODELARK_BASE
    configured = (BYTEPLUS_BASE_URL or "").strip().rstrip("/")
    if not configured:
        base_url = expected_base
    elif mode == "coding" and "/coding/" not in configured:
        logger.warning(
            "BYTEPLUS_BASE_URL=%s không khớp coding — dùng %s",
            configured,
            _CODING_BASE,
        )
        base_url = _CODING_BASE
    elif mode == "modelark" and "/coding/" in configured:
        logger.warning(
            "BYTEPLUS_BASE_URL=%s không khớp modelark — dùng %s",
            configured,
            _MODELARK_BASE,
        )
        base_url = _MODELARK_BASE
    else:
        base_url = configured

    return mode, base_url, model_id


def validate_byteplus_config() -> None:
    """Kiểm tra cấu hình tối thiểu khi LLM_PROVIDER=byteplus."""
    placeholders = ("your_", "placeholder", "here")
    if not BYTEPLUS_API_KEY or any(p in BYTEPLUS_API_KEY for p in placeholders):
        raise ValueError("LLM_PROVIDER=byteplus — cần BYTEPLUS_API_KEY trong .env")
    _, _, model_id = resolve_byteplus_settings()
    if not model_id:
        raise ValueError(
            "LLM_PROVIDER=byteplus — cần BYTEPLUS_MODEL (vd: gpt-oss-120b-250805) "
            "hoặc BYTEPLUS_ENDPOINT_ID (ep-xxx) trong .env"
        )
    mode, base_url, _ = resolve_byteplus_settings()
    logger.info(
        "BytePlus: mode=%s model=%s base=%s",
        mode,
        model_id,
        base_url,
    )


def _chat_completions_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _hint_for_http_error(status: int, body: str, *, mode: str) -> str:
    if "ModelNotOpen" in body:
        return (
            " Model chưa kích hoạt — vào BytePlus Console → ModelArk → "
            "Activation Management, bật model tương ứng (vd: gpt-oss-120b-250805). "
            "Hoặc tạo Inference Endpoint (ep-xxx) rồi đặt BYTEPLUS_ENDPOINT_ID."
        )
    if status != 404:
        return ""
    if "InvalidEndpointOrModel" in body:
        if mode == "modelark":
            return (
                " Kiểm tra BYTEPLUS_MODEL (vd: gpt-oss-120b-250805, không phải "
                "gpt-oss-120b) hoặc dùng BYTEPLUS_ENDPOINT_ID=ep-xxx từ Console."
            )
        return " Kiểm tra BYTEPLUS_MODEL Coding Plan (vd: kimi-k2.5, ark-code-latest)."
    if mode == "coding":
        return (
            " Kiểm tra BYTEPLUS_API_MODE=coding, BYTEPLUS_MODEL (vd: kimi-k2.5) "
            "và API key Coding Plan."
        )
    return (
        " Nếu dùng Coding Plan: BYTEPLUS_API_MODE=coding + /api/coding/v3. "
        "ModelArk: kích hoạt model hoặc dùng Endpoint ID (ep-xxx)."
    )


def generate_chat(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
) -> tuple[str | None, dict[str, Any]]:
    """Gửi prompt tới BytePlus ModelArk; trả (text, metadata usage)."""
    if not BYTEPLUS_API_KEY:
        logger.error("BYTEPLUS_API_KEY chưa cấu hình")
        return None, {}

    mode, base_url, model_name = resolve_byteplus_settings(model)
    if not model_name:
        logger.error(
            "BYTEPLUS_MODEL / BYTEPLUS_ENDPOINT_ID chưa cấu hình"
        )
        return None, {}

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = _chat_completions_url(base_url)
    headers = {
        "Authorization": f"Bearer {BYTEPLUS_API_KEY}",
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
            if response.is_error:
                body = (response.text or "")[:800]
                hint = _hint_for_http_error(
                    response.status_code,
                    body,
                    mode=mode,
                )
                logger.warning(
                    "BytePlus %s HTTP %s — %s%s | mode=%s url=%s",
                    model_name,
                    response.status_code,
                    body or response.reason_phrase,
                    hint,
                    mode,
                    url,
                )
                return None, {
                    "model": model_name,
                    "http_status": response.status_code,
                    "byteplus_mode": mode,
                }
            data = response.json()
    except Exception as exc:
        logger.warning(
            "BytePlus %s lỗi: %s | mode=%s url=%s",
            model_name,
            exc,
            mode,
            url,
        )
        return None, {}

    choices = data.get("choices") or []
    if not choices:
        return None, {"model": model_name, "byteplus_mode": mode}

    message = choices[0].get("message") or {}
    text = (message.get("content") or "").strip()
    usage = data.get("usage") or {}
    meta: dict[str, Any] = {
        "model": data.get("model") or model_name,
        "byteplus_mode": mode,
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
    if not text:
        return None, meta
    return text, meta
