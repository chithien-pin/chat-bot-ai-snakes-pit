"""
Hybrid query router — rule-first, LLM refine khi mơ hồ.

Chạy trước extract_search_keywords / fetch_product_for_query để chọn:
- category_browse (filter URL)
- budget_browse
- product_search (tên SP cụ thể)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from cps_bot.browse.budget_browse import is_budget_browse_query, parse_budget_constraint
from cps_bot.browse.category_filter_browse import (
    build_category_filter_url,
    is_category_filter_browse_query,
    resolve_category_filter_request,
    resolve_filter_price,
)

logger = logging.getLogger(__name__)

_QUERY_ROUTE_PROMPT = """Bạn là router tra cứu CellphoneS. Phân tích câu hỏi và trả JSON thuần (không markdown).

Các mode:
- category_browse: tìm danh sách SP theo danh mục + lọc giá/hãng (vd: điện thoại dưới 10 triệu, iphone dưới 20 triệu)
- product_search: tìm 1 SP cụ thể theo tên/model (vd: pocket 3, iphone 17 pro max 256gb)
- budget_browse: tìm SP theo ngân sách không rõ danh mục

JSON schema:
{{
  "mode": "category_browse|product_search|budget_browse",
  "search_keywords": "từ khóa ngắn gọn để search hoặc để trống nếu browse",
  "brand": "iphone|samsung|... hoặc null",
  "price_min_million": null hoặc số,
  "price_max_million": null hoặc số
}}

Câu hỏi: {query}
"""


@dataclass(frozen=True)
class QueryRoute:
    """Kết quả routing — dùng trong pipeline trước fetch."""

    mode: str = "auto"
    search_keywords: str = ""
    confidence: float = 0.0
    source: str = "rule"
    category_id: str = ""
    page_path: str = ""
    filter_url: str = ""
    price_min: int | None = None
    price_max: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


_PRODUCT_BRAND_RE = re.compile(
    r"\b(?:iphone|ipad|macbook|imac|airpods|apple\s*watch|"
    r"samsung|galaxy|xiaomi|redmi|poco|oppo|reno|vivo|realme|nokia|honor|"
    r"asus|rog|dell|hp|acer|msi|lenovo|thinkpad|gigabyte|lg\s*gram|"
    r"dji|osmo|gopro|insta360|sony|canon|nikon|fujifilm|"
    r"anker|baseus|ugreen|jbl|marshall|sony\s*wh|airpod)\b",
    re.IGNORECASE,
)
# Model dạng chữ+số dính liền (s26u, ip15, m4…) hoặc "<từ> <số>" đặc trưng model
_PRODUCT_MODEL_RE = re.compile(
    r"\b(?:[a-z]{1,6}\d{1,4}[a-z]{0,3}|\d{1,2}\s*pro(?:\s*max)?|watch\s*\d)\b",
    re.IGNORECASE,
)


def _looks_like_specific_product(text: str) -> bool:
    """Câu có vẻ nhắm tới 1 SP cụ thể (hãng/model) chứ không phải tả nhu cầu."""
    value = (text or "").strip()
    if not value:
        return False
    if _PRODUCT_BRAND_RE.search(value):
        return True
    if _PRODUCT_MODEL_RE.search(value):
        return True
    return False


def _rule_route(text: str) -> QueryRoute:
    """Routing deterministic — luôn chạy trước LLM."""
    original = (text or "").strip()
    if not original:
        return QueryRoute()

    constraint = parse_budget_constraint(original)
    filter_price = resolve_filter_price(original)

    if is_category_filter_browse_query(original):
        req = resolve_category_filter_request(original)
        if req:
            url = build_category_filter_url(req, filter_price)
            return QueryRoute(
                mode="category_browse",
                search_keywords=url,
                filter_url=url,
                confidence=0.95,
                source="rule",
                category_id=req.category_id,
                page_path=req.page_path,
                price_min=filter_price[0] if filter_price else None,
                price_max=filter_price[1] if filter_price else None,
                meta={"menu_name": req.menu_name},
            )

    if is_budget_browse_query(original):
        from cps_bot.browse.budget_browse import strip_budget_phrases_for_keywords

        kw = strip_budget_phrases_for_keywords(original)
        return QueryRoute(
            mode="budget_browse",
            search_keywords=kw or original,
            confidence=0.9,
            source="rule",
            price_min=constraint.min_vnd if constraint else None,
            price_max=constraint.max_vnd if constraint else None,
        )

    if re.search(r"\bpocket\s*\d+\b", original, re.I):
        return QueryRoute(
            mode="product_search",
            search_keywords=original,
            confidence=0.88,
            source="rule",
        )

    from cps_bot.browse.product_map import _is_map_query

    # Chỉ chốt product_search khi có tín hiệu TÊN SẢN PHẨM cụ thể (hãng/model),
    # tránh coi câu tả nhu cầu ("designer làm 3D") là tìm 1 SP.
    if _is_map_query(original) and _looks_like_specific_product(original):
        return QueryRoute(
            mode="product_search",
            search_keywords=original,
            confidence=0.85,
            source="rule",
        )

    # Câu mơ hồ → confidence thấp để LLM router (nếu bật) phân loại lại.
    if _is_map_query(original):
        return QueryRoute(
            mode="product_search",
            search_keywords=original,
            confidence=0.4,
            source="rule",
        )

    return QueryRoute(mode="auto", confidence=0.0, source="rule")


def _parse_llm_route_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def _llm_route(text: str) -> QueryRoute | None:
    from config import LLM_QUERY_ROUTER

    if not LLM_QUERY_ROUTER:
        return None

    from cps_bot.llm.gemini_client import _generate_with_fallback

    prompt = _QUERY_ROUTE_PROMPT.format(query=text.strip())
    raw = _generate_with_fallback(prompt)
    data = _parse_llm_route_json(raw or "")
    if not data:
        return None

    mode = str(data.get("mode") or "auto").strip().lower()
    if mode not in ("category_browse", "product_search", "budget_browse", "auto"):
        mode = "auto"

    search_kw = str(data.get("search_keywords") or "").strip()
    price_min = data.get("price_min_million")
    price_max = data.get("price_max_million")
    pmin = int(float(price_min) * 1_000_000) if price_min is not None else None
    pmax = int(float(price_max) * 1_000_000) if price_max is not None else None

    return QueryRoute(
        mode=mode,
        search_keywords=search_kw,
        confidence=0.75,
        source="llm",
        price_min=pmin,
        price_max=pmax,
        meta={"brand": data.get("brand")},
    )


def _merge_routes(rule: QueryRoute, llm: QueryRoute) -> QueryRoute:
    """Rule thắng khi confidence cao; LLM bổ sung khi rule mơ hồ."""
    if rule.confidence >= 0.85:
        return rule

    if llm.mode == "auto":
        return rule if rule.confidence > 0 else llm

    # Rule confidence thấp (<0.85) → tin phân loại của LLM về mode.
    if rule.filter_url:
        merged_mode = rule.mode
        merged_kw = rule.filter_url
    else:
        merged_mode = llm.mode
        merged_kw = llm.search_keywords or rule.search_keywords

    return QueryRoute(
        mode=merged_mode,
        search_keywords=merged_kw,
        filter_url=rule.filter_url,
        confidence=max(rule.confidence, llm.confidence),
        source="hybrid",
        category_id=rule.category_id,
        page_path=rule.page_path,
        price_min=rule.price_min if rule.price_min is not None else llm.price_min,
        price_max=rule.price_max if rule.price_max is not None else llm.price_max,
        meta={**llm.meta, **rule.meta},
    )


def resolve_query_route(
    text: str,
    *,
    conversation_context: str = "",
    use_llm: bool | None = None,
) -> QueryRoute:
    """
    Hybrid router: rule-first → LLM refine nếu rule chưa chắc.
    conversation_context giữ cho tương lai (follow-up routing).
    """
    _ = conversation_context
    original = (text or "").strip()
    rule = _rule_route(original)
    if rule.confidence >= 0.9:
        return rule

    from config import LLM_QUERY_ROUTER

    should_llm = LLM_QUERY_ROUTER if use_llm is None else use_llm
    if not should_llm:
        return rule if rule.confidence > 0 else QueryRoute(mode="auto", source="rule")

    try:
        llm = _llm_route(original)
    except Exception as exc:
        logger.warning("LLM query router lỗi: %s", exc)
        llm = None

    if llm is None:
        return rule if rule.confidence > 0 else QueryRoute(mode="auto", source="rule")

    return _merge_routes(rule, llm)


def apply_route_to_keywords(route: QueryRoute, fallback_keywords: str) -> str:
    """Chọn search_keywords từ route hoặc fallback."""
    if route.search_keywords:
        return route.search_keywords
    if route.filter_url:
        return route.filter_url
    return fallback_keywords
