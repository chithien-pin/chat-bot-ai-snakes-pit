"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Overview, Timeline } from "@/lib/types";

const COLORS = ["#5b5fef", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4", "#d70018"];

type Props = {
  overview: Overview;
  timeline: Timeline;
  apiCalls: Record<string, number>;
  scenarios: Record<string, number>;
};

export function OverviewCharts({ overview, timeline, apiCalls, scenarios }: Props) {
  const timelineData = timeline.labels.map((label, i) => ({
    label: label.slice(5, 16),
    total: timeline.total[i],
    success: timeline.success[i],
    error: timeline.error[i],
  }));

  const statusData = Object.entries(overview.status_counts).map(([name, value]) => ({
    name,
    value,
  }));

  const resolveData = Object.entries(overview.resolve_source_counts).map(([name, value]) => ({
    name: name || "none",
    value,
  }));

  const latencyData = [
    { name: "Keyword", p95: overview.latency.keyword.p95 ?? 0 },
    { name: "Fetch", p95: overview.latency.fetch.p95 ?? 0 },
    { name: "LLM", p95: overview.latency.llm.p95 ?? 0 },
    { name: "Total", p95: overview.latency.total.p95 ?? 0 },
  ];

  const apiData = Object.entries(apiCalls).map(([name, value]) => ({
    name: name.replace(/_calls$/, "").replace(/_/g, " "),
    value,
  }));

  const scenData = Object.entries(scenarios)
    .slice(0, 8)
    .map(([name, value]) => ({ name, value }));

  const modelData = Object.entries(overview.llm.by_model || {}).map(([name, stats]) => ({
    name,
    prompt: stats.prompt_tokens,
    completion: stats.completion_tokens,
    total: stats.total_tokens,
    calls: stats.calls,
  }));

  const tokenTimeline = timeline.tokens;
  const tokenTimelineData = (tokenTimeline?.labels || []).map((label, i) => ({
    label: label.slice(5, 16),
    prompt: tokenTimeline?.prompt_tokens[i] ?? 0,
    completion: tokenTimeline?.completion_tokens[i] ?? 0,
    total: tokenTimeline?.total_tokens[i] ?? 0,
  }));

  return (
    <div className="grid grid-cols-12 gap-6">
      <div className="card col-span-12 lg:col-span-8 p-5">
        <h3 className="mb-4 text-sm font-semibold text-text-primary">Messages over time</h3>
        <ResponsiveContainer width="100%" height={280}>
          <AreaChart data={timelineData}>
            <defs>
              <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#5b5fef" stopOpacity={0.2} />
                <stop offset="95%" stopColor="#5b5fef" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" />
            <Tooltip />
            <Legend />
            <Area type="monotone" dataKey="total" stroke="#5b5fef" fill="url(#colorTotal)" strokeWidth={2} />
            <Area type="monotone" dataKey="success" stroke="#10b981" fill="transparent" strokeWidth={2} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="card col-span-12 lg:col-span-4 p-5">
        <h3 className="mb-4 text-sm font-semibold">Status distribution</h3>
        <ResponsiveContainer width="100%" height={280}>
          <PieChart>
            <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={55} outerRadius={90}>
              {statusData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="card col-span-12 md:col-span-6 lg:col-span-4 p-5">
        <h3 className="mb-4 text-sm font-semibold">Resolve source</h3>
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie data={resolveData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80}>
              {resolveData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>

      <div className="card col-span-12 md:col-span-6 lg:col-span-4 p-5">
        <h3 className="mb-4 text-sm font-semibold">Latency p95 (ms)</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={latencyData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="p95" fill="#5b5fef" radius={[6, 6, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {tokenTimelineData.length > 0 && (
        <div className="card col-span-12 lg:col-span-8 p-5">
          <h3 className="mb-4 text-sm font-semibold text-text-primary">LLM tokens over time</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={tokenTimelineData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#9ca3af" />
              <YAxis tick={{ fontSize: 11 }} stroke="#9ca3af" />
              <Tooltip />
              <Legend />
              <Bar dataKey="prompt" name="In (prompt)" stackId="tokens" fill="#5b5fef" />
              <Bar dataKey="completion" name="Out (completion)" stackId="tokens" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {modelData.length > 0 && (
        <div className="card col-span-12 lg:col-span-4 p-5">
          <h3 className="mb-4 text-sm font-semibold">Tokens by model</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={modelData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
              <XAxis type="number" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend />
              <Bar dataKey="prompt" name="In" stackId="m" fill="#5b5fef" />
              <Bar dataKey="completion" name="Out" stackId="m" fill="#10b981" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="card col-span-12 lg:col-span-4 p-5">
        <h3 className="mb-4 text-sm font-semibold">CPS API calls</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={apiData} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
            <XAxis type="number" tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="name" width={100} tick={{ fontSize: 10 }} />
            <Tooltip />
            <Bar dataKey="value" fill="#06b6d4" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {scenData.length > 0 && (
        <div className="card col-span-12 p-5">
          <h3 className="mb-4 text-sm font-semibold">Scenario enrichment</h3>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={scenData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e8ecf3" />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#8b5cf6" radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
