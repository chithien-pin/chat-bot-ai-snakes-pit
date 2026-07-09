"""
Xây pipeline trace từng tin nhắn — dùng cho dashboard Pipeline view.
"""
from __future__ import annotations

from typing import Any

from config import LLM_PROVIDER

_RESOLVE_LABELS = {
    "user_url": "URL trong tin nhắn → url_info → product detail",
    "session_fallback_url": "URL sản phẩm từ session cũ",
    "stock_status_filter": "GraphQL products + company_stock_id",
    "budget_browse": "Search + lọc theo ngân sách",
    "category_filter": "GraphQL category + dynamic attribute filter",
    "search_results": "CPS advanced/quick_search → url_info → detail",
    "serpapi": "SerpAPI site:cellphones.com.vn → CPS detail",
    "": "Không resolve được sản phẩm",
}

_STATUS_LABELS = {
    "success": "Trả lời thành công",
    "error": "Lỗi xử lý",
    "not_found": "Không tìm thấy sản phẩm",
    "keyword_empty": "Không bóc được từ khóa",
    "compare_not_found": "So sánh — thiếu sản phẩm",
    "ask_province": "Hỏi tỉnh/thành trước khi query shop",
}


def _message_id(row: dict[str, Any]) -> str:
    ts = str(row.get("ts") or "")
    chat = str(row.get("chat_id") or "")
    return f"{ts}|{chat}"


def _infer_keyword_method(row: dict[str, Any]) -> str:
    if row.get("compare_mode"):
        return "compare_extract"
    if row.get("keyword_source") == "color_follow_up" or row.get("query_route_source") == "color_follow_up":
        return "color_follow_up"
    kw_ms = row.get("latency_keyword_ms")
    if kw_ms is not None and int(kw_ms) <= 30:
        return "local_heuristic"
    if kw_ms is not None and int(kw_ms) > 200:
        return "llm_extract"
    return "auto"


def _keyword_method_label(method: str) -> str:
    return {
        "local_heuristic": "Heuristic cục bộ (regex / từ điển)",
        "color_follow_up": "Follow-up màu — reuse keyword session",
        "llm_extract": "LLM bóc tách từ khóa",
        "compare_extract": "Trích từ câu so sánh",
        "auto": "Tự động (local hoặc LLM)",
    }.get(method, method)


def _is_shop_stock_api_call(item: dict[str, Any]) -> bool:
    if item.get("phase") == "shop_stock":
        return True
    op = str(item.get("operation") or "").upper()
    if op in ("SHOP_STOCK", "SHOPS_STOCK"):
        return True
    return "shops_stock" in str(item.get("graphql_query") or "")


def _api_calls_list(row: dict[str, Any], *, phase: str | None = None) -> list[dict[str, Any]]:
    stored = row.get("api_calls_detail")
    if isinstance(stored, list) and stored:
        out: list[dict[str, Any]] = []
        for item in stored:
            if not isinstance(item, dict):
                continue
            if phase == "shop_stock":
                if not _is_shop_stock_api_call(item):
                    continue
            elif phase == "fetch":
                if _is_shop_stock_api_call(item) or item.get("phase") == "enrich":
                    continue
            elif phase == "enrich":
                if item.get("phase") != "enrich":
                    continue
            op = str(item.get("operation") or item.get("name") or "api")
            out.append(
                {
                    "key": op,
                    "name": str(
                        item.get("name")
                        or _OPERATION_LABELS.get(op, op)
                    ),
                    "description": _format_api_call_description(item),
                    "calls": 1,
                    "endpoint": item.get("endpoint") or "",
                    "operation": op,
                    "method": item.get("method") or "POST",
                    "filter_url": item.get("filter_url") or "",
                    "query": item.get("query") or "",
                    "graphql_query": item.get("graphql_query") or "",
                    "variables": item.get("variables"),
                    "curl": item.get("curl") or "",
                    "product_id": item.get("product_id") or "",
                    "matched_name": item.get("matched_name") or "",
                    "category_id": item.get("category_id") or "",
                }
            )
        return out

    if phase and phase != "fetch":
        return []

    mapping = [
        ("category_filter_calls", "GraphQL products (category filter)", "GetProductsByCategoryFilter"),
        ("search_products_calls", "CPS GraphQL Search", "advanced_search / quick_search"),
        ("cps_url_info_calls", "GraphQL url_info", "Resolve URL → product_id / category_id"),
        ("cps_product_detail_calls", "GraphQL product detail", "Chi tiết SP + variant"),
        ("serpapi_calls", "SerpAPI", "Google site:cellphones.com.vn"),
    ]
    out = []
    for key, name, desc in mapping:
        count = int(row.get(key) or 0)
        if count > 0:
            out.append({"key": key, "name": name, "description": desc, "calls": count})
    return out


_OPERATION_LABELS = {
    "URL_INFO": "GraphQL url_info",
    "getProductDataDetail": "GraphQL product detail",
    "GetProductsByCateId": "GraphQL products by category",
    "advanced_search": "CPS advanced_search",
    "quick_search": "CPS quick_search",
    "serpapi": "SerpAPI Google",
    "product_map": "Product map (local)",
    "SHOP_STOCK": "GraphQL shops_stock",
}


def _format_api_call_description(item: dict[str, Any]) -> str:
    parts: list[str] = []
    if item.get("filter_url"):
        parts.append(str(item["filter_url"]))
    elif item.get("query"):
        parts.append(f"query={item['query']}")
    if item.get("category_id"):
        parts.append(f"category_id={item['category_id']}")
    if item.get("budget_label"):
        parts.append(str(item["budget_label"]))
    if item.get("endpoint"):
        parts.append(str(item["endpoint"]))
    return " · ".join(parts) if parts else str(item.get("operation") or "")


def build_pipeline_trace(row: dict[str, Any]) -> dict[str, Any]:
    """Pipeline đầy đủ cho 1 event chat_message."""
    status = str(row.get("status") or "")
    intent = str(row.get("intent") or "")
    resolve = str(row.get("resolve_source") or "")
    keyword_method = _infer_keyword_method(row)

    steps: list[dict[str, Any]] = []

    steps.append(
        {
            "id": "receive",
            "title": "Nhận tin nhắn",
            "status": "done",
            "duration_ms": None,
            "details": {
                "platform": row.get("platform"),
                "chat_id": row.get("chat_id"),
                "user_id": row.get("user_id"),
                "user_question": row.get("user_question") or "",
                "question_len": row.get("question_len"),
                "is_follow_up": row.get("is_follow_up"),
                "thread_key": row.get("thread_key"),
            },
        }
    )

    if status.startswith("intent_") or intent:
        kind = intent or status.replace("intent_", "")
        steps.append(
            {
                "id": "intent",
                "title": "Phân loại intent",
                "status": "done",
                "duration_ms": None,
                "details": {
                    "kind": kind,
                    "action": "Trả lời nhanh — không fetch sản phẩm",
                },
            }
        )
        return _pack_trace(row, steps, early_exit=True)

    steps.append(
        {
            "id": "intent",
            "title": "Phân loại intent",
            "status": "done",
            "duration_ms": None,
            "details": {"kind": "product", "action": "Tiếp tục pipeline sản phẩm"},
        }
    )

    if status == "ask_province":
        steps.append(
            {
                "id": "province_gate",
                "title": "Hỏi tỉnh/thành",
                "status": "done",
                "duration_ms": None,
                "details": {
                    "pending": row.get("pending_province_for"),
                    "action": "Chờ user cung cấp vị trí",
                },
            }
        )
        return _pack_trace(row, steps, early_exit=True)

    if row.get("pending_province_for"):
        steps.append(
            {
                "id": "province_gate",
                "title": "Province gate",
                "status": "skipped",
                "duration_ms": None,
                "details": {"note": "Đã có tỉnh hoặc không cần"},
            }
        )

    kw_ms = row.get("latency_keyword_ms")
    resolved_filter = str(row.get("resolved_filter_url") or "")
    steps.append(
        {
            "id": "keyword",
            "title": "Bóc tách từ khóa / filter",
            "status": "done" if row.get("search_keywords") or status != "keyword_empty" else "failed",
            "duration_ms": kw_ms,
            "details": {
                "method": keyword_method,
                "method_label": _keyword_method_label(keyword_method),
                "keywords": row.get("search_keywords") or "",
                "resolved_filter_url": resolved_filter,
                "resolve_note": (
                    "Dùng category filter thay vì search keyword"
                    if resolved_filter
                    else ""
                ),
            },
        }
    )

    if status == "keyword_empty":
        return _pack_trace(row, steps, early_exit=True)

    fetch_ms = row.get("latency_fetch_ms")
    apis = _api_calls_list(row, phase="fetch")
    steps.append(
        {
            "id": "fetch",
            "title": "Tìm & fetch sản phẩm",
            "status": "done" if resolve else ("failed" if status == "not_found" else "skipped"),
            "duration_ms": fetch_ms,
            "details": {
                "resolve_source": resolve,
                "resolve_label": _RESOLVE_LABELS.get(resolve, resolve),
                "api_calls": apis,
                "resolved_filter_url": row.get("resolved_filter_url") or "",
                "ambiguous_search": bool(row.get("ambiguous_search")),
                "category_filter_id": row.get("category_filter_id"),
                "budget_label": row.get("budget_label"),
                "stock_filter_ids": row.get("stock_filter_ids"),
            },
        }
    )

    enrich = row.get("scenario_enrich")
    if isinstance(enrich, dict) and any(enrich.values()):
        active = [k for k, v in enrich.items() if v]
        steps.append(
            {
                "id": "enrich",
                "title": "Enrich theo scenario",
                "status": "done",
                "duration_ms": None,
                "details": {"scenarios": active},
            }
        )

    if row.get("shop_stock_scenario"):
        shop_apis = _api_calls_list(row, phase="shop_stock")
        steps.append(
            {
                "id": "shop_stock",
                "title": "Tồn cửa hàng",
                "status": "done",
                "duration_ms": None,
                "details": {
                    "matched_shops": row.get("shop_stock_matched"),
                    "endpoint": "GraphQL shops_stock",
                    "api_calls": shop_apis,
                },
            }
        )

    llm_ms = row.get("latency_gemini_ms")
    model = row.get("gemini_model") or ""
    if llm_ms is not None and int(llm_ms) > 0:
        steps.append(
            {
                "id": "llm",
                "title": "LLM sinh câu trả lời",
                "status": "done" if status == "success" else "failed",
                "duration_ms": llm_ms,
                "details": {
                    "provider": row.get("llm_provider") or LLM_PROVIDER,
                    "model": model,
                    "prompt_tokens": row.get("prompt_tokens"),
                    "completion_tokens": row.get("completion_tokens"),
                    "total_tokens": row.get("total_tokens"),
                },
            }
        )

    steps.append(
        {
            "id": "reply",
            "title": "Gửi phản hồi user",
            "status": "done" if status == "success" else ("failed" if status == "error" else "warn"),
            "duration_ms": row.get("total_latency_ms"),
            "details": {
                "status": status,
                "status_label": _STATUS_LABELS.get(status, status),
                "product_id": row.get("product_id"),
                "product_url": row.get("product_url"),
                "response_link_url": row.get("response_link_url"),
                "error": row.get("error"),
            },
        }
    )

    return _pack_trace(row, steps, early_exit=False)


def _pack_trace(
    row: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    early_exit: bool,
) -> dict[str, Any]:
    total = row.get("total_latency_ms")
    accounted = sum(int(s["duration_ms"]) for s in steps if s.get("duration_ms"))
    return {
        "id": _message_id(row),
        "ts": row.get("ts"),
        "platform": row.get("platform"),
        "status": row.get("status"),
        "early_exit": early_exit,
        "total_latency_ms": total,
        "accounted_latency_ms": accounted,
        "search_keywords": row.get("search_keywords") or "",
        "resolve_source": row.get("resolve_source") or "",
        "user_question": row.get("user_question") or "",
        "steps": steps,
    }


def recent_pipelines(
    rows: list[dict[str, Any]],
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    chat.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return [build_pipeline_trace(r) for r in chat[:limit]]


def get_pipeline_by_id(rows: list[dict[str, Any]], pipeline_id: str) -> dict[str, Any] | None:
    for row in rows:
        if row.get("event") != "chat_message":
            continue
        if _message_id(row) == pipeline_id:
            return build_pipeline_trace(row)
    return None
