#!/usr/bin/env python3
"""
Bot Operations Dashboard — FastAPI + static UI.

Chạy:
  .venv/bin/python dashboard_api.py
  # hoặc
  .venv/bin/uvicorn dashboard_api:app --host 0.0.0.0 --port 8080

Mở browser: http://localhost:8080
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from config import DASHBOARD_HOST, DASHBOARD_PORT, LLM_PROVIDER, active_llm_model
from dashboard.auth import (
    SESSION_COOKIE_NAME,
    dashboard_auth_enabled,
    verify_basic_auth,
    verify_session_token,
)
from dashboard.data_health import build_data_health
from dashboard.metrics_reader import (
    build_api_call_stats,
    build_overview,
    build_pipeline_funnel,
    build_scenario_enrichment,
    build_timeline,
    build_token_timeline,
    load_metrics,
    recent_feedback,
    recent_messages,
)
from dashboard.pipeline_trace import get_pipeline_by_id, recent_pipelines
from dashboard.session_reader import load_session_summary
from cps_bot.feedback.feedback_training import (
    accept_feedback_entry,
    list_feedback_entries,
    reject_feedback_entry,
    training_stats,
)

ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = ROOT / "dashboard" / "static"

app = FastAPI(title="CellphoneS Bot Dashboard", version="1.0.0")


class FeedbackActionBody(BaseModel):
    admin_note: str = ""


def _entry_to_dict(entry) -> dict:
    from dataclasses import asdict

    return asdict(entry)


class DashboardAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not dashboard_auth_enabled():
            return await call_next(request)

        path = request.url.path
        if path.startswith("/static"):
            return await call_next(request)

        auth_header = request.headers.get("authorization")
        session = request.cookies.get(SESSION_COOKIE_NAME)
        if verify_basic_auth(auth_header) or verify_session_token(session or ""):
            return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Unauthorized"},
            headers={"WWW-Authenticate": 'Basic realm="Bot Dashboard"'},
        )


app.add_middleware(DashboardAuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def api_config() -> dict:
    return {
        "llm_provider": LLM_PROVIDER,
        "llm_model": active_llm_model(),
        "static_dir": str(STATIC_DIR),
    }


@app.get("/api/overview")
async def api_overview(hours: int = Query(168, ge=1, le=720)) -> dict:
    rows = load_metrics(since_hours=hours)
    return {
        "hours": hours,
        "overview": build_overview(rows),
        "pipeline_funnel": build_pipeline_funnel(rows),
        "scenario_enrichment": build_scenario_enrichment(rows),
        "api_calls": build_api_call_stats(rows),
    }


@app.get("/api/timeline")
async def api_timeline(hours: int = Query(168, ge=1, le=720)) -> dict:
    rows = load_metrics(since_hours=hours)
    return {
        **build_timeline(rows),
        "tokens": build_token_timeline(rows),
    }


@app.get("/api/messages")
async def api_messages(
    hours: int = Query(168, ge=1, le=720),
    limit: int = Query(80, ge=1, le=500),
    platform: str | None = Query(None),
    status: str | None = Query(None),
    user_id: str | None = Query(None),
    shop_stock_only: bool = Query(False),
    follow_up_only: bool = Query(False),
    reuse_context_only: bool = Query(False),
    group_by_user: bool = Query(False),
) -> dict:
    rows = load_metrics(since_hours=hours)
    return recent_messages(
        rows,
        limit=limit,
        platform=platform,
        status=status,
        user_id=user_id,
        shop_stock_only=shop_stock_only,
        follow_up_only=follow_up_only,
        reuse_context_only=reuse_context_only,
        group_by_user=group_by_user,
    )


@app.get("/api/feedback")
async def api_feedback(
    hours: int = Query(168, ge=1, le=720),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    rows = load_metrics(since_hours=hours)
    return {"feedback": recent_feedback(rows, limit=limit)}


@app.get("/api/feedback/training")
async def api_feedback_training(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    entries = list_feedback_entries(status=status, limit=limit)
    return {
        "stats": training_stats(),
        "entries": [_entry_to_dict(e) for e in entries],
    }


@app.post("/api/feedback/training/{entry_id}/accept")
async def api_feedback_training_accept(
    entry_id: str,
    body: FeedbackActionBody | None = None,
) -> dict:
    note = (body.admin_note if body else "") or ""
    entry = accept_feedback_entry(entry_id, admin_note=note)
    if not entry:
        raise HTTPException(status_code=404, detail="Feedback entry not found")
    return {"ok": True, "entry": _entry_to_dict(entry)}


@app.post("/api/feedback/training/{entry_id}/reject")
async def api_feedback_training_reject(
    entry_id: str,
    body: FeedbackActionBody | None = None,
) -> dict:
    note = (body.admin_note if body else "") or ""
    entry = reject_feedback_entry(entry_id, admin_note=note)
    if not entry:
        raise HTTPException(status_code=404, detail="Feedback entry not found")
    return {"ok": True, "entry": _entry_to_dict(entry)}


@app.get("/api/sessions")
async def api_sessions(limit: int = Query(30, ge=1, le=100)) -> dict:
    return load_session_summary(limit=limit)


@app.get("/api/data-health")
async def api_data_health() -> dict:
    return build_data_health()


@app.get("/api/pipelines")
async def api_pipelines(
    hours: int = Query(168, ge=1, le=720),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    rows = load_metrics(since_hours=hours)
    return {"pipelines": recent_pipelines(rows, limit=limit)}


@app.get("/api/pipelines/{pipeline_id:path}")
async def api_pipeline_detail(
    pipeline_id: str,
    hours: int = Query(720, ge=1, le=720),
) -> dict:
    rows = load_metrics(since_hours=hours)
    trace = get_pipeline_by_id(rows, pipeline_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return trace


def main() -> None:
    import uvicorn

    uvicorn.run(
        "cps_bot.apps.dashboard:app",
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
