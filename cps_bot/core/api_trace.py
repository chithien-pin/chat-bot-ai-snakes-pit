"""
Ghi chi tiết HTTP/GraphQL calls vào stats (metrics → dashboard pipeline).
"""
from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from typing import Any, AsyncIterator, Iterator

_MAX_QUERY_CHARS = 12_000
_MAX_CURL_CHARS = 16_000
_MAX_CALLS = 40

_trace_stats: ContextVar[dict[str, Any] | None] = ContextVar("api_trace_stats", default=None)
_trace_phase: ContextVar[str] = ContextVar("api_trace_phase", default="fetch")


def _extract_operation_name(query: str) -> str:
    match = re.search(r"\b(query|mutation)\s+(\w+)", query or "")
    if match:
        return match.group(2)
    return "anonymous"


def _compact_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def build_curl_post(
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> str:
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    parts = [f"curl -sS -X POST {_shell_quote(url)}"]
    for key, value in hdrs.items():
        parts.append(f"  -H {_shell_quote(f'{key}: {value}')}")
    if json_body is not None:
        body = _compact_json(json_body)
        if len(body) > _MAX_CURL_CHARS - 200:
            body = body[: _MAX_CURL_CHARS - 200] + "…"
        parts.append(f"  -d {_shell_quote(body)}")
    return " \\\n".join(parts)


def build_curl_get(url: str, *, params: dict[str, Any] | None = None) -> str:
    from urllib.parse import urlencode

    full = url
    if params:
        full = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    return f"curl -sS {_shell_quote(full)}"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def record_api_call(
    stats: dict[str, Any] | None,
    *,
    name: str = "",
    operation: str = "",
    method: str = "POST",
    endpoint: str = "",
    graphql_query: str = "",
    variables: dict[str, Any] | None = None,
    curl: str = "",
    **extra: Any,
) -> None:
    if stats is None:
        return
    detail = stats.setdefault("api_calls_detail", [])
    if not isinstance(detail, list):
        return
    if len(detail) >= _MAX_CALLS:
        return

    op = operation or _extract_operation_name(graphql_query)
    phase = _trace_phase.get()
    entry: dict[str, Any] = {
        "name": name or op or "API call",
        "operation": op,
        "method": method.upper(),
        "endpoint": endpoint,
        "phase": phase,
    }
    if graphql_query:
        q = graphql_query.strip()
        if len(q) > _MAX_QUERY_CHARS:
            q = q[: _MAX_QUERY_CHARS - 20] + "\n… (truncated)"
        entry["graphql_query"] = q
    if variables is not None:
        entry["variables"] = variables
    if curl:
        entry["curl"] = curl[:_MAX_CURL_CHARS]
    elif endpoint and method.upper() == "POST" and graphql_query:
        entry["curl"] = build_curl_post(
            endpoint,
            json_body={"query": graphql_query.strip(), "variables": variables or {}},
        )
    for key, value in extra.items():
        if value is not None and value != "" and value != []:
            entry[key] = value
    detail.append(entry)


def record_from_context(
    *,
    name: str = "",
    operation: str = "",
    method: str = "POST",
    endpoint: str = "",
    graphql_query: str = "",
    variables: dict[str, Any] | None = None,
    curl: str = "",
    **extra: Any,
) -> None:
    stats = _trace_stats.get()
    record_api_call(
        stats,
        name=name,
        operation=operation,
        method=method,
        endpoint=endpoint,
        graphql_query=graphql_query,
        variables=variables,
        curl=curl,
        **extra,
    )


@asynccontextmanager
async def api_trace_scope(stats: dict[str, Any]) -> AsyncIterator[None]:
    token = _trace_stats.set(stats)
    try:
        yield
    finally:
        _trace_stats.reset(token)


@contextmanager
def trace_phase(phase: str) -> Iterator[None]:
    token = _trace_phase.set(phase)
    try:
        yield
    finally:
        _trace_phase.reset(token)


def merge_api_calls_detail(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Gộp api_calls_detail khi compare 2 sản phẩm."""
    src = source.get("api_calls_detail")
    if not isinstance(src, list) or not src:
        return
    dst = target.setdefault("api_calls_detail", [])
    if not isinstance(dst, list):
        target["api_calls_detail"] = list(src)
        return
    for item in src:
        if len(dst) >= _MAX_CALLS:
            break
        dst.append(item)
