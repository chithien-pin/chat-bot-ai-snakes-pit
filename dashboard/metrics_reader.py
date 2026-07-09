"""
Đọc và aggregate metrics.log (JSON lines từ metrics.emit_metric).
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import METRICS_LOG_PATH

from cps_bot.core.user_display import (
    attach_user_names,
    build_user_display_map,
    ensure_lark_user_names,
)


def _parse_ts(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_metrics(
    *,
    path: Path | str | None = None,
    max_lines: int = 50_000,
    since_hours: int | None = None,
) -> list[dict[str, Any]]:
    file_path = Path(path or METRICS_LOG_PATH)
    if not file_path.is_file():
        return []

    since_dt: datetime | None = None
    if since_hours is not None:
        since_dt = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    rows: list[dict[str, Any]] = []
    with file_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            if since_dt is not None:
                ts = _parse_ts(str(row.get("ts") or ""))
                if ts and ts < since_dt:
                    continue
            rows.append(row)

    if len(rows) > max_lines:
        rows = rows[-max_lines:]
    return rows


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct / 100
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def _latency_stats(values: list[int | float]) -> dict[str, float | None]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return {"avg": None, "p50": None, "p95": None, "max": None}
    return {
        "avg": round(statistics.mean(nums), 1),
        "p50": round(_percentile(nums, 50) or 0, 1),
        "p95": round(_percentile(nums, 95) or 0, 1),
        "max": round(max(nums), 1),
    }


def build_overview(rows: list[dict[str, Any]]) -> dict[str, Any]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    feedback = [r for r in rows if r.get("event") == "message_feedback"]

    statuses = Counter(str(r.get("status") or "unknown") for r in chat)
    platforms = Counter(str(r.get("platform") or "unknown") for r in chat)
    resolve_sources = Counter(
        str(r.get("resolve_source") or "none") for r in chat if r.get("resolve_source")
    )

    success = statuses.get("success", 0)
    total_chat = len(chat)
    success_rate = round(success / total_chat * 100, 1) if total_chat else 0.0

    helpful = sum(1 for r in feedback if r.get("rating") == "helpful")
    not_helpful = sum(1 for r in feedback if r.get("rating") == "not_helpful")
    feedback_total = helpful + not_helpful

    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    llm_calls = 0
    by_model: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
        }
    )
    for row in chat:
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        total = int(row.get("total_tokens") or 0)
        if not total and not prompt and not completion:
            continue
        if not total:
            total = prompt + completion
        prompt_tokens += prompt
        completion_tokens += completion
        total_tokens += total
        llm_calls += 1
        model = str(row.get("gemini_model") or "unknown")
        bucket = by_model[model]
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        bucket["total_tokens"] += total
        bucket["calls"] += 1

    return {
        "total_messages": total_chat,
        "success_rate": success_rate,
        "status_counts": dict(statuses),
        "platform_counts": dict(platforms),
        "resolve_source_counts": dict(resolve_sources),
        "latency": {
            "total": _latency_stats([r.get("total_latency_ms") for r in chat]),
            "keyword": _latency_stats([r.get("latency_keyword_ms") for r in chat]),
            "fetch": _latency_stats([r.get("latency_fetch_ms") for r in chat]),
            "llm": _latency_stats([r.get("latency_gemini_ms") for r in chat]),
        },
        "feedback": {
            "total": feedback_total,
            "helpful": helpful,
            "not_helpful": not_helpful,
            "helpful_rate": round(helpful / feedback_total * 100, 1) if feedback_total else None,
        },
        "llm": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "messages_with_tokens": llm_calls,
            "avg_prompt_tokens": round(prompt_tokens / llm_calls, 1) if llm_calls else None,
            "avg_completion_tokens": round(completion_tokens / llm_calls, 1) if llm_calls else None,
            "avg_tokens": round(total_tokens / llm_calls, 1) if llm_calls else None,
            "by_model": dict(by_model),
        },
        "shop_stock_queries": sum(1 for r in chat if r.get("shop_stock_scenario")),
        "compare_queries": sum(1 for r in chat if r.get("compare_mode")),
        "ambiguous_search": sum(1 for r in chat if r.get("ambiguous_search")),
    }


def build_token_timeline(rows: list[dict[str, Any]], *, bucket_hours: int = 1) -> dict[str, Any]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    buckets: dict[str, dict[str, int]] = defaultdict(
        lambda: {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )

    for row in chat:
        ts = _parse_ts(str(row.get("ts") or ""))
        if not ts:
            continue
        prompt = int(row.get("prompt_tokens") or 0)
        completion = int(row.get("completion_tokens") or 0)
        total = int(row.get("total_tokens") or 0)
        if not total and not prompt and not completion:
            continue
        if not total:
            total = prompt + completion
        label = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:00")
        buckets[label]["prompt_tokens"] += prompt
        buckets[label]["completion_tokens"] += completion
        buckets[label]["total_tokens"] += total

    labels = sorted(buckets.keys())
    return {
        "labels": labels,
        "prompt_tokens": [buckets[l]["prompt_tokens"] for l in labels],
        "completion_tokens": [buckets[l]["completion_tokens"] for l in labels],
        "total_tokens": [buckets[l]["total_tokens"] for l in labels],
    }


def build_timeline(rows: list[dict[str, Any]], *, bucket_hours: int = 1) -> dict[str, Any]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    buckets: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0, "error": 0})

    for row in chat:
        ts = _parse_ts(str(row.get("ts") or ""))
        if not ts:
            continue
        label = ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:00")
        buckets[label]["total"] += 1
        status = str(row.get("status") or "")
        if status == "success":
            buckets[label]["success"] += 1
        elif status == "error":
            buckets[label]["error"] += 1

    labels = sorted(buckets.keys())
    return {
        "labels": labels,
        "total": [buckets[l]["total"] for l in labels],
        "success": [buckets[l]["success"] for l in labels],
        "error": [buckets[l]["error"] for l in labels],
    }


def build_pipeline_funnel(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    if not chat:
        return []

    stages = [
        ("Tổng tin nhắn", len(chat)),
        ("Intent sản phẩm", sum(1 for r in chat if not str(r.get("status") or "").startswith("intent_"))),
        ("Qua province gate", sum(1 for r in chat if r.get("status") not in ("ask_province",) and not str(r.get("status") or "").startswith("intent_"))),
        ("Có keywords", sum(1 for r in chat if r.get("status") not in ("keyword_empty", "ask_province") and not str(r.get("status") or "").startswith("intent_"))),
        ("Tìm được SP", sum(1 for r in chat if r.get("status") == "success")),
    ]
    return [{"stage": name, "count": count} for name, count in stages]


def build_scenario_enrichment(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("event") != "chat_message":
            continue
        enrich = row.get("scenario_enrich")
        if isinstance(enrich, dict):
            for key, active in enrich.items():
                if active:
                    counts[str(key)] += 1
    return dict(counts.most_common())


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _message_row(row: dict[str, Any]) -> dict[str, Any]:
    prompt = _opt_int(row.get("prompt_tokens"))
    completion = _opt_int(row.get("completion_tokens"))
    total = _opt_int(row.get("total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {
        "ts": row.get("ts"),
        "platform": row.get("platform"),
        "chat_id": row.get("chat_id") or "",
        "user_id": row.get("user_id") or "",
        "user_name": row.get("user_name") or "",
        "thread_key": row.get("thread_key") or "",
        "status": row.get("status"),
        "resolve_source": row.get("resolve_source") or "",
        "search_keywords": row.get("search_keywords") or "",
        "product_id": row.get("product_id") or "",
        "total_latency_ms": row.get("total_latency_ms"),
        "latency_keyword_ms": row.get("latency_keyword_ms"),
        "latency_fetch_ms": row.get("latency_fetch_ms"),
        "latency_gemini_ms": row.get("latency_gemini_ms"),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "gemini_model": row.get("gemini_model") or "",
        "llm_provider": row.get("llm_provider") or "",
        "is_follow_up": bool(row.get("is_follow_up")),
        "reuse_product_context": bool(row.get("reuse_product_context")),
        "shop_stock_scenario": bool(row.get("shop_stock_scenario")),
        "shop_stock_trigger": bool(row.get("shop_stock_trigger")),
        "question_len": row.get("question_len"),
        "user_question": (row.get("user_question") or "")[:500],
        "error": row.get("error") or "",
    }


def filter_chat_messages(
    rows: list[dict[str, Any]],
    *,
    platform: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    shop_stock_only: bool = False,
    follow_up_only: bool = False,
    reuse_context_only: bool = False,
) -> list[dict[str, Any]]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    if platform:
        chat = [r for r in chat if str(r.get("platform") or "") == platform]
    if status:
        chat = [r for r in chat if str(r.get("status") or "") == status]
    if user_id:
        chat = [r for r in chat if str(r.get("user_id") or "") == user_id]
    if shop_stock_only:
        chat = [
            r
            for r in chat
            if r.get("shop_stock_scenario") or r.get("shop_stock_trigger")
        ]
    if follow_up_only:
        chat = [r for r in chat if r.get("is_follow_up")]
    if reuse_context_only:
        chat = [r for r in chat if r.get("reuse_product_context")]
    return chat


def build_message_filter_options(
    rows: list[dict[str, Any]],
    *,
    name_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    chat = [r for r in rows if r.get("event") == "chat_message"]
    platforms = sorted({str(r.get("platform") or "") for r in chat if r.get("platform")})
    statuses = sorted({str(r.get("status") or "") for r in chat if r.get("status")})
    user_counts: Counter[str] = Counter()
    for row in chat:
        uid = str(row.get("user_id") or "").strip()
        if uid:
            user_counts[uid] += 1
    names = name_map or build_user_display_map(rows)
    users = [
        {
            "user_id": uid,
            "user_name": names.get(uid, ""),
            "count": count,
            "platform": _dominant_platform_for_user(chat, uid),
        }
        for uid, count in user_counts.most_common()
    ]
    return {
        "platforms": platforms,
        "statuses": statuses,
        "users": users,
    }


def _dominant_platform_for_user(chat: list[dict[str, Any]], user_id: str) -> str:
    counts: Counter[str] = Counter()
    for row in chat:
        if str(row.get("user_id") or "") != user_id:
            continue
        platform = str(row.get("platform") or "")
        if platform:
            counts[platform] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]


def group_messages_by_user(
    messages: list[dict[str, Any]],
    *,
    name_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for msg in messages:
        uid = str(msg.get("user_id") or "").strip() or "_anonymous"
        buckets[uid].append(msg)

    groups: list[dict[str, Any]] = []
    for uid, items in buckets.items():
        items.sort(key=lambda m: str(m.get("ts") or ""), reverse=True)
        real_uid = "" if uid == "_anonymous" else uid
        user_name = ""
        if name_map and real_uid:
            user_name = name_map.get(real_uid, "")
        if not user_name:
            for item in items:
                user_name = str(item.get("user_name") or "").strip()
                if user_name:
                    break
        groups.append(
            {
                "user_id": real_uid,
                "user_name": user_name,
                "platform": items[0].get("platform") or "",
                "message_count": len(items),
                "last_ts": items[0].get("ts"),
                "messages": items,
            }
        )
    groups.sort(key=lambda g: str(g.get("last_ts") or ""), reverse=True)
    return groups


def recent_messages(
    rows: list[dict[str, Any]],
    *,
    limit: int = 40,
    platform: str | None = None,
    status: str | None = None,
    user_id: str | None = None,
    shop_stock_only: bool = False,
    follow_up_only: bool = False,
    reuse_context_only: bool = False,
    group_by_user: bool = False,
) -> dict[str, Any]:
    filtered = filter_chat_messages(
        rows,
        platform=platform,
        status=status,
        user_id=user_id,
        shop_stock_only=shop_stock_only,
        follow_up_only=follow_up_only,
        reuse_context_only=reuse_context_only,
    )
    filtered.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    lark_user_ids = {
        str(r.get("user_id") or "").strip()
        for r in filtered
        if str(r.get("platform") or "") == "lark" and r.get("user_id")
    }
    ensure_lark_user_names(lark_user_ids)
    sliced = filtered[:limit]
    messages = [_message_row(row) for row in sliced]
    name_map = build_user_display_map(rows)
    result: dict[str, Any] = {
        "messages": messages,
        "total_matched": len(filtered),
        "filters": build_message_filter_options(rows, name_map=name_map),
    }
    if group_by_user:
        result["groups"] = group_messages_by_user(messages, name_map=name_map)
    attach_user_names(result, name_map)
    return result


def recent_feedback(rows: list[dict[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    fb = [r for r in rows if r.get("event") == "message_feedback"]
    fb.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    return [
        {
            "ts": r.get("ts"),
            "platform": r.get("platform"),
            "rating": r.get("rating"),
            "chat_id": r.get("chat_id"),
            "user_comment": (r.get("user_comment") or "")[:200],
        }
        for r in fb[:limit]
    ]


def build_api_call_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    totals = Counter()
    for row in rows:
        if row.get("event") != "chat_message":
            continue
        for key in (
            "serpapi_calls",
            "search_products_calls",
            "cps_url_info_calls",
            "cps_product_detail_calls",
        ):
            totals[key] += int(row.get(key) or 0)
    return dict(totals)
