"""
Luồng xử lý tin nhắn chat — dùng chung cho web UI (và có thể tái sử dụng sau này).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from config import (
    FAST_BROWSE_REPLY,
    LLM_MAX_SEARCH_RESULTS,
    LLM_PROVIDER,
    SLIM_LLM_PAYLOAD,
)
from cps_bot.browse.budget_browse import is_budget_browse_query
from cps_bot.browse.fast_reply import (
    build_browse_list_reply,
    build_color_sibling_reply,
    can_fast_browse_reply,
    can_fast_color_sibling_reply,
    slim_payload_for_llm,
)
from cps_bot.core.api_trace import api_trace_scope, trace_phase
from cps_bot.core.conversation import (
    append_turn,
    clear_session,
    format_context_block,
    get_session,
    has_product_context,
    mirror_session_to_chat_level,
    resolve_session,
    session_scope_key,
)
from cps_bot.core.location_flow import handle_province_gate, shop_question_for_session
from cps_bot.core.metrics import emit_metric
from cps_bot.core.session_store import load_session_store
from cps_bot.cps.cps_api import (
    attach_shop_stock_to_payload,
    classify_question_scenarios,
    enrich_payload_for_scenarios,
    fetch_product_for_query,
    is_color_variant_list_query,
    is_stock_status_browse_query,
    should_attach_shop_stock,
)
from cps_bot.cps.scraper import (
    build_product_payload,
    build_response_link_url,
    format_product_links_appendix,
    is_browse_list_mode,
    product_url_from_record,
    should_attach_product_links_appendix,
)
from cps_bot.feedback.feedback import cache_feedback_context
from cps_bot.llm.disambiguation import (
    build_disambiguation_message,
    resolve_disambiguation_choice,
)
from cps_bot.llm.gemini_client import (
    _mentions_new_product,
    analyze_product_with_meta,
    extract_compare_product_queries,
    extract_search_keywords,
    is_contextual_follow_up,
    llm_provider_display_name,
    needs_query_expansion,
    references_prior_product,
    should_reuse_product_identity,
)
from cps_bot.llm.message_intent import is_social_message, resolve_message_intent
from cps_bot.llm.query_router import apply_route_to_keywords, resolve_query_route
from cps_bot.llm.answer_guard import check_answer_numbers

logger = logging.getLogger(__name__)

MAX_REPLY_LENGTH = 8000
WEB_CHAT_ID_PREFIX = "web"

StatusCallback = Callable[[str], Awaitable[None] | None]

_session_store: dict[str, Any] | None = None


def get_web_session_store() -> dict[str, Any]:
    global _session_store
    if _session_store is None:
        _session_store = load_session_store()
    return _session_store


def web_chat_id(session_id: str) -> str:
    return f"{WEB_CHAT_ID_PREFIX}:{session_id}"


def truncate_reply(text: str, max_len: int = MAX_REPLY_LENGTH) -> str:
    if len(text) <= max_len:
        return text
    suffix = "\n\n… (đã rút gọn)"
    return text[: max_len - len(suffix)] + suffix


@dataclass
class ChatPipelineResult:
    reply: str
    message_id: str
    status: str
    product_url: str = ""
    product_name: str = ""
    product_id: str = ""
    search_keywords: str = ""
    response_link_url: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


async def _emit_status(callback: StatusCallback | None, text: str) -> None:
    if not callback:
        return
    result = callback(text)
    if asyncio.iscoroutine(result):
        await result


async def process_chat_message(
    user_question: str,
    *,
    session_id: str,
    user_id: str = "anonymous",
    user_name: str = "",
    on_status: StatusCallback | None = None,
) -> ChatPipelineResult:
    """Xử lý một câu hỏi — luồng giống Telegram/Lark."""
    user_question = (user_question or "").strip()
    if not user_question:
        return ChatPipelineResult(
            reply="Vui lòng nhập câu hỏi.",
            message_id="",
            status="empty",
        )

    store = get_web_session_store()
    chat_id = web_chat_id(session_id)
    thread_key = None
    session = get_session(store, chat_id, user_id, thread_key=thread_key)
    session_key = session_scope_key(chat_id, user_id, thread_key=thread_key)
    message_id = uuid.uuid4().hex[:16]

    pending = session.get("pending_disambiguation") or []
    disambig_pick = resolve_disambiguation_choice(user_question, pending) if pending else None
    forced_product_url = ""
    if disambig_pick:
        session.pop("pending_disambiguation", None)
        forced_product_url = product_url_from_record(disambig_pick)

    context_session = resolve_session(store, chat_id, user_id, thread_key=thread_key)
    conversation_context = format_context_block(context_session)
    social = is_social_message(user_question)
    is_follow_up = (
        not social
        and is_contextual_follow_up(user_question, conversation_context)
    )
    reuse_product_context = not social and (
        is_follow_up
        or references_prior_product(user_question)
        or (
            has_product_context(context_session)
            and not _mentions_new_product(user_question)
        )
    )
    last_product = context_session.get("last_product") or {}
    reuse_product_identity = should_reuse_product_identity(
        user_question,
        conversation_context,
        last_keywords=context_session.get("last_keywords") or "",
        last_product_name=last_product.get("name") or "",
    )
    started = time.perf_counter()
    metric_data: dict[str, object] = {
        "platform": "web",
        "chat_id": str(chat_id),
        "user_id": str(user_id or ""),
        "user_name": user_name,
        "is_follow_up": is_follow_up,
        "reuse_product_context": reuse_product_context,
        "reuse_product_identity": reuse_product_identity,
        "question_len": len(user_question),
        "llm_provider": LLM_PROVIDER,
    }

    intent = resolve_message_intent(
        user_question,
        conversation_context=conversation_context,
        has_product_context=has_product_context(context_session),
        is_follow_up=is_follow_up,
        has_pending_disambiguation=bool(pending),
        has_pending_province=bool(session.get("pending_province_for")),
    )
    if intent.kind != "product" and intent.reply:
        metric_data["intent"] = intent.kind
        metric_data["status"] = f"intent_{intent.kind}"
        append_turn(
            session,
            user=user_question,
            assistant=intent.reply,
            keywords="",
            product_name="",
            product_url="",
            session_key=session_key,
        )
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return ChatPipelineResult(
            reply=intent.reply,
            message_id=message_id,
            status=str(metric_data["status"]),
            metrics=dict(metric_data),
        )

    province_gate = handle_province_gate(
        user_question,
        session,
        has_product_context=has_product_context(context_session),
    )
    if province_gate.should_ask:
        session["pending_province_for"] = province_gate.pending_kind
        metric_data["status"] = "ask_province"
        metric_data["pending_province_for"] = province_gate.pending_kind
        append_turn(
            session,
            user=user_question,
            assistant=province_gate.reply,
            keywords="",
            product_name="",
            product_url="",
            session_key=session_key,
        )
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return ChatPipelineResult(
            reply=province_gate.reply,
            message_id=message_id,
            status="ask_province",
            metrics=dict(metric_data),
        )

    query_province_id = province_gate.province_id
    resume_shop_stock = session.pop("resume_shop_stock", False)
    resume_store_locator = session.pop("resume_store_locator", False)
    shop_question = (
        shop_question_for_session(session, user_question)
        if resume_shop_stock or resume_store_locator
        else user_question
    )

    await _emit_status(on_status, "🔍 Đang tìm kiếm thông tin...")

    product_url = ""
    response_link_url = ""
    try:
        compare_queries = extract_compare_product_queries(user_question)

        t0 = time.perf_counter()
        kw_context = conversation_context if reuse_product_context else ""
        if compare_queries:
            search_keywords = compare_queries[0]
        else:
            stock_browse = is_stock_status_browse_query(user_question)
            budget_browse = is_budget_browse_query(user_question)
            query_route = await asyncio.to_thread(
                resolve_query_route,
                user_question,
                conversation_context=kw_context,
            )
            metric_data["query_route_mode"] = query_route.mode
            metric_data["query_route_source"] = query_route.source
            metric_data["query_route_confidence"] = query_route.confidence
            if query_route.confidence < 0.85:
                metric_data["low_confidence_route"] = True

            if query_route.confidence >= 0.85 and query_route.search_keywords:
                search_keywords = query_route.search_keywords
            else:
                if (
                    needs_query_expansion(user_question)
                    and not stock_browse
                    and not budget_browse
                ):
                    await _emit_status(on_status, "✍️ Đang hiểu câu hỏi của bạn...")
                search_keywords = await asyncio.to_thread(
                    extract_search_keywords, user_question, kw_context
                )
                search_keywords = apply_route_to_keywords(query_route, search_keywords)
            budget_browse = budget_browse or query_route.mode == "budget_browse"
        metric_data["latency_keyword_ms"] = int((time.perf_counter() - t0) * 1000)
        stock_browse = is_stock_status_browse_query(user_question)
        budget_browse = is_budget_browse_query(user_question)
        if not search_keywords and not stock_browse and not budget_browse:
            clarify = resolve_message_intent(
                user_question,
                conversation_context=conversation_context,
                has_product_context=has_product_context(context_session),
                is_follow_up=is_follow_up,
            ).reply
            reply = clarify or "😔 Không hiểu được sản phẩm bạn cần tìm."
            metric_data["status"] = "keyword_empty"
            emit_metric(
                "chat_message",
                **metric_data,
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return ChatPipelineResult(
                reply=reply,
                message_id=message_id,
                status="keyword_empty",
                metrics=dict(metric_data),
            )

        fallback_url = ""
        fallback_product_id: str | int = ""
        session_fallback_parent_id: str | int = ""
        session_last_keywords = context_session.get("last_keywords") or ""
        session_last_product_name = last_product.get("name") or ""
        if forced_product_url:
            fallback_url = forced_product_url
        elif reuse_product_identity or (
            is_color_variant_list_query(user_question)
            and last_product.get("product_id")
            and has_product_context(context_session)
        ):
            fallback_url = last_product.get("url") or ""
            fallback_product_id = last_product.get("product_id") or ""
            session_fallback_parent_id = last_product.get("parent_id") or ""

        if (stock_browse or budget_browse) and not search_keywords:
            await _emit_status(on_status, "🔍 Đang tìm sản phẩm phù hợp...")
        else:
            await _emit_status(on_status, f"🔍 Đang tìm: {search_keywords}...")

        t1 = time.perf_counter()
        compare_products: list[dict[str, Any]] = []
        if compare_queries:
            await _emit_status(on_status, "⚖️ Đang so sánh 2 sản phẩm...")
            fetch_stats: dict[str, Any] = {}
            for kw in compare_queries[:2]:
                sub_results, sub_detail, sub_stats = await fetch_product_for_query(
                    kw,
                    user_message=user_question,
                )
                for key, val in sub_stats.items():
                    if isinstance(val, int):
                        fetch_stats[key] = int(fetch_stats.get(key, 0)) + val
                    elif key == "resolve_source" and val:
                        fetch_stats[key] = val
                    elif key == "api_calls_detail":
                        from cps_bot.core.api_trace import merge_api_calls_detail

                        merge_api_calls_detail(fetch_stats, sub_stats)
                if sub_detail:
                    compare_products.append(sub_detail)
            results = []
            detail = compare_products[0] if compare_products else {}
        else:
            results, detail, fetch_stats = await fetch_product_for_query(
                search_keywords,
                user_message=user_question,
                fallback_url=fallback_url,
                fallback_product_id=fallback_product_id,
                session_fallback_parent_id=session_fallback_parent_id,
                session_last_keywords=session_last_keywords,
                session_last_product_name=session_last_product_name,
            )
        metric_data["latency_fetch_ms"] = int((time.perf_counter() - t1) * 1000)
        metric_data.update(fetch_stats)
        if fetch_stats.get("resolved_filter_url"):
            metric_data["search_keywords"] = fetch_stats["resolved_filter_url"]

        if compare_queries and len(compare_products) < 2:
            reply = (
                "😔 Chưa tìm đủ 2 sản phẩm để so sánh.\n"
                "Thử gõ rõ tên từng máy, vd: _So sánh iPhone 16 Pro Max và S25 Ultra_"
            )
            metric_data["status"] = "compare_not_found"
            emit_metric(
                "chat_message",
                **metric_data,
                total_latency_ms=int((time.perf_counter() - started) * 1000),
            )
            return ChatPipelineResult(
                reply=reply,
                message_id=message_id,
                status="compare_not_found",
                search_keywords=search_keywords,
                metrics=dict(metric_data),
            )

        if not results and not detail:
            scenarios = classify_question_scenarios(shop_question)
            if scenarios.get("store_locator") or resume_store_locator:
                detail = {
                    "name": "Cửa hàng CellphoneS",
                    "product_id": "",
                    "url": "",
                    "price": "",
                }
            else:
                hint = (
                    f"\n\n_Từ khóa đã tìm: {search_keywords}_"
                    if search_keywords != user_question
                    else ""
                )
                reply = (
                    "😔 Không tìm thấy sản phẩm phù hợp trên CellphoneS.\n"
                    "Thử hỏi lại với tên sản phẩm cụ thể hơn nhé!"
                    f"{hint}"
                )
                metric_data["status"] = "not_found"
                metric_data["search_keywords"] = search_keywords
                emit_metric(
                    "chat_message",
                    **metric_data,
                    total_latency_ms=int((time.perf_counter() - started) * 1000),
                )
                return ChatPipelineResult(
                    reply=reply,
                    message_id=message_id,
                    status="not_found",
                    search_keywords=search_keywords,
                    metrics=dict(metric_data),
                )

        if fetch_stats.get("ambiguous_search") and len(results) >= 2:
            session["pending_disambiguation"] = results[:3]
            metric_data["ambiguous_search"] = True

        metric_data["resolve_source"] = fetch_stats.get("resolve_source", "")

        await _emit_status(on_status, "📦 Đã tìm thấy sản phẩm. Đang phân tích dữ liệu...")

        product_url = product_url_from_record(detail) or (
            product_url_from_record(results[0]) if results else ""
        )
        if compare_products:
            payload = {
                "compare_mode": True,
                "compare_products": compare_products,
                "primary_product": compare_products[0],
                "search_results": [
                    {
                        "name": p.get("name", ""),
                        "price": p.get("price", ""),
                        "url": p.get("url", ""),
                        "product_id": p.get("product_id", ""),
                    }
                    for p in compare_products
                ],
            }
            response_link_url = product_url_from_record(compare_products[0]) or ""
            metric_data["compare_mode"] = True
        else:
            payload = build_product_payload(results, detail)
            response_link_url = build_response_link_url(
                search_results=results,
                detail=detail,
                search_keywords=search_keywords,
            )

        browse_list = is_browse_list_mode(detail)
        need_shop_stock = bool(
            detail.get("product_id")
            and not detail.get("stock_browse_list_mode")
            and not detail.get("budget_browse_list_mode")
            and should_attach_shop_stock(
                shop_question,
                resume=resume_shop_stock,
                reuse_product_context=reuse_product_context,
            )
        )
        need_enrich = not browse_list

        async def _run_shop_stock() -> tuple[Any, int]:
            t0 = time.perf_counter()
            async with api_trace_scope(metric_data):
                with trace_phase("shop_stock"):
                    ctx = await attach_shop_stock_to_payload(
                        payload,
                        detail,
                        user_question=shop_question,
                        province_id=query_province_id,
                    )
            return ctx, int((time.perf_counter() - t0) * 1000)

        async def _run_enrich() -> tuple[dict[str, bool], int]:
            t0 = time.perf_counter()
            flags = await enrich_payload_for_scenarios(
                payload,
                detail,
                user_question=shop_question,
                province_id=query_province_id,
                api_trace_stats=metric_data,
            )
            return flags, int((time.perf_counter() - t0) * 1000)

        shop_ctx = None
        scenario_flags: dict[str, bool] = {}
        if need_shop_stock and need_enrich:
            metric_data["shop_stock_trigger"] = True
            await _emit_status(
                on_status,
                "🏪 Đang kiểm tra tồn cửa hàng và dữ liệu bổ sung...",
            )
            shop_result, enrich_result = await asyncio.gather(
                _run_shop_stock(),
                _run_enrich(),
                return_exceptions=True,
            )
            if isinstance(shop_result, Exception):
                logger.warning("shop_stock parallel lỗi: %s", shop_result)
            else:
                shop_ctx, shop_ms = shop_result
                metric_data["latency_shop_stock_ms"] = shop_ms
            if isinstance(enrich_result, Exception):
                logger.warning("enrich parallel lỗi: %s", enrich_result)
            else:
                scenario_flags, enrich_ms = enrich_result
                metric_data["latency_enrich_ms"] = enrich_ms
        elif need_shop_stock:
            metric_data["shop_stock_trigger"] = True
            await _emit_status(on_status, "🏪 Đang kiểm tra tồn cửa hàng...")
            shop_ctx, shop_ms = await _run_shop_stock()
            metric_data["latency_shop_stock_ms"] = shop_ms
        elif need_enrich:
            scenario_flags, enrich_ms = await _run_enrich()
            metric_data["latency_enrich_ms"] = enrich_ms

        if shop_ctx:
            metric_data["shop_stock_scenario"] = True
            metric_data["shop_stock_matched"] = shop_ctx.get("matched_shops_count", 0)
        if scenario_flags:
            metric_data["scenario_enrich"] = scenario_flags

        t2 = time.perf_counter()
        gemini_meta: dict[str, Any] = {}
        if can_fast_color_sibling_reply(payload, user_question):
            answer = build_color_sibling_reply(
                user_question,
                payload,
                response_link_url=response_link_url,
            )
            metric_data["fast_color_sibling_reply"] = True
            metric_data["gemini_model"] = "template"
        elif FAST_BROWSE_REPLY and can_fast_browse_reply(
            detail, payload.get("search_results") or []
        ):
            answer = build_browse_list_reply(
                user_question,
                detail,
                payload.get("search_results") or [],
                response_link_url=response_link_url,
            )
            metric_data["fast_browse_reply"] = True
            metric_data["gemini_model"] = "template"
        else:
            llm_label = llm_provider_display_name()
            await _emit_status(on_status, f"🤖 Đang phân tích với {llm_label}...")
            llm_payload = (
                slim_payload_for_llm(payload, max_results=LLM_MAX_SEARCH_RESULTS)
                if SLIM_LLM_PAYLOAD
                else payload
            )
            answer, gemini_meta = await asyncio.to_thread(
                analyze_product_with_meta,
                user_question,
                llm_payload,
                conversation_context,
            )
        metric_data["latency_gemini_ms"] = int((time.perf_counter() - t2) * 1000)
        if gemini_meta:
            metric_data.update(
                {
                    "gemini_model": gemini_meta.get("model", ""),
                    "prompt_tokens": int(gemini_meta.get("prompt_tokens", 0) or 0),
                    "completion_tokens": int(gemini_meta.get("completion_tokens", 0) or 0),
                    "total_tokens": int(gemini_meta.get("total_tokens", 0) or 0),
                }
            )

        price_mismatches = check_answer_numbers(answer, payload)
        if price_mismatches:
            metric_data["price_mismatch_detected"] = True
            metric_data["price_mismatch_numbers"] = price_mismatches
            logger.warning(
                "Price mismatch in answer (log-only): %s question=%r",
                price_mismatches,
                user_question[:120],
            )

        answer = truncate_reply(answer)
        search_list = payload.get("search_results") or []
        scenarios = payload.get("question_scenarios") or {}
        if should_attach_product_links_appendix(
            detail,
            scenarios=scenarios,
            compare_mode=bool(metric_data.get("compare_mode")),
            ambiguous_search=bool(fetch_stats.get("ambiguous_search")),
            fast_browse_reply=bool(metric_data.get("fast_browse_reply")),
        ):
            appendix = format_product_links_appendix(search_list)
            if appendix and appendix not in answer:
                answer = truncate_reply(f"{answer}{appendix}")

        disambig_msg = (
            build_disambiguation_message(results) if fetch_stats.get("ambiguous_search") else ""
        )
        if disambig_msg and disambig_msg not in answer:
            answer = truncate_reply(f"{answer}\n\n{disambig_msg}")

        product_name = (
            detail.get("name") or (results[0].get("name") if results else "") or ""
        ).strip()
        append_turn(
            session,
            user=user_question,
            assistant=answer,
            keywords=search_keywords,
            product_name=product_name,
            product_url=product_url,
            product_id=detail.get("product_id", ""),
            parent_product_id=detail.get("parent_id", ""),
            session_key=session_key,
        )
        mirror_session_to_chat_level(store, chat_id, user_id, session)

        cache_feedback_context(
            chat_id=str(chat_id),
            message_id=message_id,
            user_question=user_question,
            bot_answer=answer,
            search_keywords=search_keywords,
            product_id=str(detail.get("product_id") or ""),
            product_name=product_name,
            product_url=product_url,
        )

        metric_data["status"] = "success"
        metric_data["search_keywords"] = search_keywords
        metric_data["product_id"] = detail.get("product_id", "")
        metric_data["product_url"] = product_url
        metric_data["response_link_url"] = response_link_url
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )

        return ChatPipelineResult(
            reply=answer,
            message_id=message_id,
            status="success",
            product_url=product_url,
            product_name=product_name,
            product_id=str(detail.get("product_id") or ""),
            search_keywords=search_keywords,
            response_link_url=response_link_url,
            metrics=dict(metric_data),
        )

    except Exception as exc:
        logger.exception("Web chat pipeline error: %s", exc)
        friendly = (
            "⚠️ Đã xảy ra lỗi khi xử lý yêu cầu.\n"
            "Vui lòng thử lại sau ít phút."
        )
        metric_data["status"] = "error"
        metric_data["error"] = str(exc)[:200]
        emit_metric(
            "chat_message",
            **metric_data,
            total_latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return ChatPipelineResult(
            reply=friendly,
            message_id=message_id,
            status="error",
            metrics=dict(metric_data),
        )


def clear_web_chat_session(session_id: str, user_id: str = "anonymous") -> None:
    store = get_web_session_store()
    clear_session(store, web_chat_id(session_id), user_id, thread_key=None)
