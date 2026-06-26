"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ChevronRight, GitBranch } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { PipelineTraceView } from "@/components/pipeline/PipelineTraceView";
import { getPipeline, getPipelines } from "@/lib/api";
import type { PipelineTrace } from "@/lib/types";
import { cn, fmtMs, fmtTs, statusColor } from "@/lib/utils";

export default function PipelinePage() {
  const [hours, setHours] = useState(168);
  const [list, setList] = useState<PipelineTrace[]>([]);
  const [selected, setSelected] = useState<PipelineTrace | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getPipelines(hours, 40);
      setList(data.pipelines);
      if (data.pipelines.length) {
        setSelected((prev) => prev ?? data.pipelines[0]);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => {
    load();
  }, [load]);

  const pick = async (id: string) => {
    try {
      const trace = await getPipeline(id);
      setSelected(trace);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <>
      <Header
        title="Message Pipeline"
        subtitle="Phân tích từng bước bot xử lý tin nhắn — intent, keywords, API, LLM, reply"
        hours={hours}
        onHoursChange={setHours}
        onRefresh={load}
      />

      <div className="mb-6 rounded-2xl border border-brand/20 bg-brand-light p-4 text-sm text-text-secondary">
        <p className="font-semibold text-brand-dark">Pipeline steps (đề xuất)</p>
        <p className="mt-1">
          Nhận tin → Intent → Province gate → Bóc keywords → Fetch CPS API → Enrich scenario →
          Shop stock → LLM → Reply user
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        <div className="card lg:col-span-4 overflow-hidden">
          <div className="border-b border-surface-border px-4 py-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <GitBranch className="h-4 w-4 text-brand" />
              Recent pipelines
            </h3>
          </div>
          <ul className="max-h-[640px] divide-y divide-surface-border overflow-y-auto">
            {loading && (
              <li className="p-4 text-sm text-text-muted">Loading…</li>
            )}
            {!loading && list.length === 0 && (
              <li className="p-4 text-sm text-text-muted">Chưa có dữ liệu metrics.log</li>
            )}
            {list.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => pick(p.id)}
                  className={cn(
                    "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-muted",
                    selected?.id === p.id && "bg-brand-light",
                  )}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{p.search_keywords || "(no keywords)"}</p>
                    <p className="text-xs text-text-muted">{fmtTs(p.ts)} · {p.platform}</p>
                  </div>
                  <div className="text-right">
                    <span className={cn("badge", statusColor(p.status))}>{p.status}</span>
                    <p className="mt-1 text-xs font-semibold text-brand">{fmtMs(p.total_latency_ms)}</p>
                  </div>
                  <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" />
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="lg:col-span-8">
          {selected ? (
            <PipelineTraceView trace={selected} />
          ) : (
            <div className="card flex h-64 items-center justify-center text-text-muted">
              Chọn một pipeline để xem chi tiết
            </div>
          )}
        </div>
      </div>

      <p className="mt-6 text-center text-xs text-text-muted">
        Xem chi tiết URL:{" "}
        <Link href="/messages" className="text-brand hover:underline">
          Messages table
        </Link>
      </p>
    </>
  );
}
