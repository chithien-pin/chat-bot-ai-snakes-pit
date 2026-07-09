"use client";

import { useState } from "react";
import {
  Bot,
  CheckCircle2,
  Circle,
  Copy,
  Check,
  KeyRound,
  MessageSquare,
  Search,
  Sparkles,
  Store,
  XCircle,
  Zap,
} from "lucide-react";
import type { PipelineStep, PipelineTrace } from "@/lib/types";
import { cn, fmtMs, fmtNum, fmtTs } from "@/lib/utils";

const STEP_ICONS: Record<string, typeof Bot> = {
  receive: MessageSquare,
  intent: Bot,
  province_gate: Store,
  keyword: KeyRound,
  fetch: Search,
  enrich: Sparkles,
  shop_stock: Store,
  llm: Sparkles,
  reply: Zap,
};

type ApiCallRow = {
  name: string;
  description: string;
  calls: number;
  filter_url?: string;
  operation?: string;
  method?: string;
  endpoint?: string;
  graphql_query?: string;
  variables?: Record<string, unknown>;
  curl?: string;
  query?: string;
};

function StepIcon({ step }: { step: PipelineStep }) {
  const Icon = STEP_ICONS[step.id] || Circle;
  const ok = step.status === "done";
  const fail = step.status === "failed";
  return (
    <div
      className={cn(
        "relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-2 bg-surface",
        ok && "border-success text-success",
        fail && "border-danger text-danger",
        step.status === "skipped" && "border-surface-border text-text-muted",
        step.status === "warn" && "border-warning text-warning",
      )}
    >
      {fail ? <XCircle className="h-5 w-5" /> : ok ? <CheckCircle2 className="h-5 w-5" /> : <Icon className="h-5 w-5" />}
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  return (
    <button
      type="button"
      onClick={copy}
      className="inline-flex items-center gap-1 rounded-md border border-surface-border bg-surface px-2 py-1 text-[10px] font-semibold text-text-secondary hover:bg-surface-muted"
    >
      {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
      {copied ? "Copied" : "Copy curl"}
    </button>
  );
}

function ApiCallCard({ api, index }: { api: ApiCallRow; index: number }) {
  const [open, setOpen] = useState(index === 0);
  const varsText =
    api.variables != null ? JSON.stringify(api.variables, null, 2) : "";

  return (
    <div className="rounded-lg border border-surface-border bg-surface overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start justify-between gap-2 px-3 py-2 text-left hover:bg-surface-muted/60"
      >
        <div className="min-w-0">
          <p className="font-medium text-text-primary">{api.name}</p>
          <p className="text-xs font-mono text-brand">{api.operation || "—"}</p>
          <p className="text-xs text-text-muted break-all">
            {(api.method || "POST").toUpperCase()} · {api.endpoint || api.description}
          </p>
        </div>
        <span className="badge shrink-0 bg-brand-light text-brand-dark">{open ? "▾" : "▸"}</span>
      </button>

      {open ? (
        <div className="space-y-3 border-t border-surface-border bg-surface-muted/40 px-3 py-3 text-xs">
          {api.filter_url ? (
            <div>
              <p className="font-semibold uppercase tracking-wide text-text-muted">Filter URL</p>
              <p className="mt-1 font-mono text-success break-all">{api.filter_url}</p>
            </div>
          ) : null}
          {api.query && !api.graphql_query ? (
            <div>
              <p className="font-semibold uppercase tracking-wide text-text-muted">Query / terms</p>
              <p className="mt-1 font-mono break-all">{api.query}</p>
            </div>
          ) : null}
          {varsText ? (
            <div>
              <p className="font-semibold uppercase tracking-wide text-text-muted">Variables</p>
              <pre className="mt-1 max-h-40 overflow-auto rounded-md bg-surface p-2 font-mono text-[11px] leading-relaxed">
                {varsText}
              </pre>
            </div>
          ) : null}
          {api.graphql_query ? (
            <div>
              <p className="font-semibold uppercase tracking-wide text-text-muted">GraphQL query</p>
              <pre className="mt-1 max-h-48 overflow-auto rounded-md bg-surface p-2 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
                {api.graphql_query}
              </pre>
            </div>
          ) : null}
          {api.curl ? (
            <div>
              <div className="mb-1 flex items-center justify-between gap-2">
                <p className="font-semibold uppercase tracking-wide text-text-muted">curl</p>
                <CopyButton text={api.curl} />
              </div>
              <pre className="max-h-56 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-[11px] leading-relaxed text-emerald-300 whitespace-pre-wrap">
                {api.curl}
              </pre>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function DetailBlock({ details }: { details: Record<string, unknown> }) {
  const entries = Object.entries(details).filter(([, v]) => v != null && v !== "" && v !== false);
  if (!entries.length) return null;

  return (
    <dl className="mt-3 grid gap-2 rounded-xl bg-surface-muted p-4 text-sm">
      {entries.map(([key, value]) => {
        if (key === "api_calls" && Array.isArray(value)) {
          const apis = value as ApiCallRow[];
          return (
            <div key={key} className="col-span-full">
              <dt className="text-xs font-semibold uppercase tracking-wide text-text-muted">
                API calls ({apis.length})
              </dt>
              <dd className="mt-2 space-y-2">
                {apis.map((api, i) => (
                  <ApiCallCard key={`${api.name}-${api.operation}-${i}`} api={api} index={i} />
                ))}
              </dd>
            </div>
          );
        }
        if (key === "scenarios" && Array.isArray(value)) {
          return (
            <div key={key} className="col-span-full">
              <dt className="text-xs font-semibold text-text-muted">Scenarios enriched</dt>
              <dd className="mt-1 flex flex-wrap gap-1">
                {(value as string[]).map((s) => (
                  <span key={s} className="badge bg-brand-light text-brand-dark">{s}</span>
                ))}
              </dd>
            </div>
          );
        }
        const label = {
          prompt_tokens: "tokens in",
          completion_tokens: "tokens out",
          total_tokens: "tokens total",
          user_question: "Câu hỏi user",
        }[key] || key.replace(/_/g, " ");
        const display =
          typeof value === "object" ? JSON.stringify(value) : String(value);
        return (
          <div key={key}>
            <dt className="text-xs capitalize text-text-muted">{label}</dt>
            <dd className="font-medium text-text-primary break-all">{display}</dd>
          </div>
        );
      })}
    </dl>
  );
}

export function PipelineTraceView({ trace }: { trace: PipelineTrace }) {
  return (
    <div className="card p-6">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-surface-border pb-6">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-text-muted">Pipeline trace</p>
          <h2 className="mt-1 text-lg font-bold">{fmtTs(trace.ts)}</h2>
          {trace.user_question ? (
            <p className="mt-2 max-w-2xl text-sm font-medium text-text-primary">
              <span className="text-text-muted">User: </span>
              {trace.user_question}
            </p>
          ) : null}
          <p className="mt-1 text-sm text-text-secondary">
            {trace.platform} · <span className="font-mono text-brand">{trace.search_keywords || "—"}</span>
          </p>
        </div>
        <div className="text-right">
          <p className="text-3xl font-bold text-brand">{fmtMs(trace.total_latency_ms)}</p>
          <p className="text-xs text-text-muted">Tổng thời gian reply</p>
          {trace.resolve_source && (
            <p className="mt-2 text-xs">
              <span className="badge bg-emerald-50 text-success">{trace.resolve_source}</span>
            </p>
          )}
        </div>
      </div>

      <div className="relative space-y-0">
        {trace.steps.map((step, idx) => (
          <div key={step.id} className="relative flex gap-4 pb-8 last:pb-0">
            {idx < trace.steps.length - 1 && <div className="pipeline-line" />}
            <StepIcon step={step} />
            <div className="min-w-0 flex-1 pt-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="font-semibold text-text-primary">{step.title}</h3>
                {step.duration_ms != null && (
                  <span className="badge bg-surface-muted text-text-secondary">{fmtMs(step.duration_ms)}</span>
                )}
              </div>
              <DetailBlock details={step.details} />
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-3 gap-4 rounded-xl bg-brand-light p-4 text-center text-sm">
        <div>
          <p className="text-xs text-text-muted">Accounted</p>
          <p className="font-bold text-brand-dark">{fmtMs(trace.accounted_latency_ms)}</p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Steps</p>
          <p className="font-bold text-brand-dark">{fmtNum(trace.steps.length)}</p>
        </div>
        <div>
          <p className="text-xs text-text-muted">Early exit</p>
          <p className="font-bold text-brand-dark">{trace.early_exit ? "Yes" : "No"}</p>
        </div>
      </div>
    </div>
  );
}
