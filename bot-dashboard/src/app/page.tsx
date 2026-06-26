"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  Clock,
  MessageSquare,
  ThumbsUp,
  TrendingUp,
  Zap,
} from "lucide-react";
import { Header } from "@/components/layout/Header";
import { OverviewCharts } from "@/components/charts/OverviewCharts";
import { KpiCard } from "@/components/ui/KpiCard";
import { getConfig, getOverview, getTimeline } from "@/lib/api";
import type { Overview, Timeline } from "@/lib/types";
import { fmtMs, fmtNum } from "@/lib/utils";

export default function OverviewPage() {
  const [hours, setHours] = useState(168);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [extra, setExtra] = useState<{
    api_calls: Record<string, number>;
    scenario_enrichment: Record<string, number>;
    llm_model: string;
    llm_provider: string;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ov, tl, cfg] = await Promise.all([getOverview(hours), getTimeline(hours), getConfig()]);
      setOverview(ov.overview);
      setTimeline(tl);
      setExtra({
        api_calls: ov.api_calls,
        scenario_enrichment: ov.scenario_enrichment,
        llm_model: cfg.llm_model,
        llm_provider: cfg.llm_provider,
      });
    } catch (e) {
      console.error(e);
      setError(
        "Không kết nối được API backend. Chạy: .venv/bin/python dashboard_api.py (port 8080)",
      );
      setOverview(null);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !overview) {
    return (
      <div className="flex h-64 items-center justify-center text-text-muted">
        Loading analytics…
      </div>
    );
  }

  if (error || !overview) {
    return (
      <>
        <Header
          title="Analytics Overview"
          subtitle="Inspired by Analytics Dashboard — realtime bot metrics"
          hours={hours}
          onHoursChange={setHours}
          onRefresh={load}
        />
        <div className="card border-danger/30 bg-red-50 p-6 text-center text-danger">
          <p className="font-semibold">{error || "Không có dữ liệu"}</p>
          <p className="mt-2 text-sm text-text-secondary">
            Terminal 1: <code>.venv/bin/python dashboard_api.py</code>
            <br />
            Terminal 2: <code>npm run dev</code>
          </p>
        </div>
      </>
    );
  }

  const ov = overview;

  return (
    <>
      <Header
        title="Analytics Overview"
        subtitle="Inspired by Analytics Dashboard — realtime bot metrics"
        hours={hours}
        onHoursChange={setHours}
        onRefresh={load}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Total messages"
          value={fmtNum(ov.total_messages)}
          sub="chat_message events"
          icon={MessageSquare}
        />
        <KpiCard
          label="Success rate"
          value={`${ov.success_rate}%`}
          sub={`${ov.status_counts.success || 0} successful`}
          icon={TrendingUp}
          accent="success"
        />
        <KpiCard
          label="Reply time p95"
          value={fmtMs(ov.latency.total.p95 ?? undefined)}
          sub={`avg ${fmtMs(ov.latency.total.avg ?? undefined)}`}
          icon={Clock}
          accent="warning"
        />
        <KpiCard
          label="LLM tokens (total)"
          value={fmtNum(ov.llm.total_tokens)}
          sub={
            extra
              ? `${extra.llm_provider} · ${extra.llm_model}`
              : `avg ${fmtNum(ov.llm.avg_tokens ?? undefined)}/msg`
          }
          icon={Zap}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Tokens in (prompt)"
          value={fmtNum(ov.llm.prompt_tokens)}
          sub={`avg ${fmtNum(ov.llm.avg_prompt_tokens ?? undefined)}/msg`}
          icon={ArrowDownLeft}
          accent="brand"
        />
        <KpiCard
          label="Tokens out (completion)"
          value={fmtNum(ov.llm.completion_tokens)}
          sub={`avg ${fmtNum(ov.llm.avg_completion_tokens ?? undefined)}/msg`}
          icon={ArrowUpRight}
          accent="success"
        />
        <KpiCard
          label="LLM calls"
          value={fmtNum(ov.llm.messages_with_tokens)}
          sub={`${Object.keys(ov.llm.by_model || {}).length} model(s) used`}
          icon={Zap}
        />
        <KpiCard
          label="Feedback helpful"
          value={ov.feedback.helpful_rate != null ? `${ov.feedback.helpful_rate}%` : "—"}
          sub={`${ov.feedback.helpful} / ${ov.feedback.total}`}
          icon={ThumbsUp}
          accent="success"
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
        <KpiCard
          label="Shop stock queries"
          value={fmtNum(ov.shop_stock_queries)}
          icon={MessageSquare}
          accent="brand"
        />
        <KpiCard
          label="Ambiguous search"
          value={fmtNum(ov.ambiguous_search)}
          icon={TrendingUp}
          accent="danger"
        />
      </div>

      {timeline && extra && (
        <div className="mt-8">
          <OverviewCharts
            overview={ov}
            timeline={timeline}
            apiCalls={extra.api_calls}
            scenarios={extra.scenario_enrichment}
          />
        </div>
      )}
    </>
  );
}
