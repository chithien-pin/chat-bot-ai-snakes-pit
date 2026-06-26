"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, Clock, ThumbsDown, ThumbsUp, X } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { KpiCard } from "@/components/ui/KpiCard";
import {
  acceptFeedbackTraining,
  getFeedbackTraining,
  rejectFeedbackTraining,
} from "@/lib/api";
import type { FeedbackTrainingEntry, FeedbackTrainingStats } from "@/lib/types";
import { cn, fmtTs } from "@/lib/utils";

const STATUS_FILTERS = [
  { id: "", label: "Tất cả" },
  { id: "pending", label: "Chờ duyệt" },
  { id: "accepted", label: "Đã accept" },
  { id: "rejected", label: "Đã reject" },
] as const;

function ratingBadge(rating: string) {
  if (rating === "helpful") return "text-success bg-emerald-50";
  if (rating === "not_helpful") return "text-danger bg-red-50";
  return "text-text-secondary bg-surface-muted";
}

function statusBadge(status: string) {
  if (status === "accepted") return "text-success bg-emerald-50";
  if (status === "rejected") return "text-danger bg-red-50";
  if (status === "pending") return "text-warning bg-amber-50";
  return "text-text-secondary bg-surface-muted";
}

export default function FeedbackPage() {
  const [statusFilter, setStatusFilter] = useState("pending");
  const [stats, setStats] = useState<FeedbackTrainingStats | null>(null);
  const [rows, setRows] = useState<FeedbackTrainingEntry[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const data = await getFeedbackTraining(statusFilter || undefined, 80);
    setStats(data.stats);
    setRows(data.entries);
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleAccept(entry: FeedbackTrainingEntry) {
    setBusyId(entry.id);
    try {
      await acceptFeedbackTraining(entry.id, notes[entry.id] || "");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(entry: FeedbackTrainingEntry) {
    setBusyId(entry.id);
    try {
      await rejectFeedbackTraining(entry.id, notes[entry.id] || "");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <Header
        title="Feedback Training"
        subtitle="Duyệt feedback user → few-shot training cho LLM"
        onRefresh={load}
      />

      {stats ? (
        <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KpiCard label="Chờ duyệt" value={String(stats.pending)} sub="pending" icon={Clock} accent="warning" />
          <KpiCard label="Đã accept" value={String(stats.accepted)} sub="dùng train bot" icon={Check} accent="success" />
          <KpiCard label="Hữu ích" value={String(stats.helpful)} icon={ThumbsUp} />
          <KpiCard label="Không hữu ích" value={String(stats.not_helpful)} icon={ThumbsDown} accent="danger" />
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap gap-2">
        {STATUS_FILTERS.map(({ id, label }) => (
          <button
            key={id || "all"}
            type="button"
            onClick={() => setStatusFilter(id)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-xs font-semibold transition",
              statusFilter === id
                ? "bg-brand text-white"
                : "bg-surface-muted text-text-secondary hover:bg-brand-light",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="space-y-4">
        {rows.length === 0 ? (
          <div className="card p-8 text-center text-sm text-text-muted">
            Không có feedback nào trong bộ lọc này.
          </div>
        ) : (
          rows.map((entry) => (
            <article key={entry.id} className="card space-y-3 p-4">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono text-text-muted">{entry.id}</span>
                <span className="badge bg-surface-muted text-text-secondary">{entry.platform}</span>
                <span className={cn("badge", ratingBadge(entry.rating))}>
                  {entry.rating === "helpful" ? "👍 Hữu ích" : "👎 Không hữu ích"}
                </span>
                <span className={cn("badge", statusBadge(entry.status))}>{entry.status}</span>
                <span className="text-text-muted">{fmtTs(entry.ts)}</span>
              </div>

              {entry.user_question ? (
                <div>
                  <p className="text-xs font-semibold uppercase text-text-muted">Câu hỏi</p>
                  <p className="text-sm">{entry.user_question}</p>
                </div>
              ) : null}

              {entry.bot_answer ? (
                <div>
                  <p className="text-xs font-semibold uppercase text-text-muted">Câu trả lời bot</p>
                  <p className="whitespace-pre-wrap text-sm text-text-secondary">{entry.bot_answer}</p>
                </div>
              ) : null}

              {entry.user_comment ? (
                <div>
                  <p className="text-xs font-semibold uppercase text-text-muted">Ý kiến user</p>
                  <p className="text-sm italic">{entry.user_comment}</p>
                </div>
              ) : null}

              {(entry.product_name || entry.search_keywords) ? (
                <p className="text-xs text-text-muted">
                  {entry.product_name ? `SP: ${entry.product_name}` : ""}
                  {entry.search_keywords ? ` · kw: ${entry.search_keywords}` : ""}
                </p>
              ) : null}

              {entry.status === "pending" ? (
                <div className="space-y-2 border-t border-surface-border pt-3">
                  <textarea
                    className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm"
                    rows={2}
                    placeholder="Ghi chú admin (vd: cách trả lời nên dùng cho câu tương tự)..."
                    value={notes[entry.id] || ""}
                    onChange={(e) =>
                      setNotes((prev) => ({ ...prev, [entry.id]: e.target.value }))
                    }
                  />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={busyId === entry.id}
                      onClick={() => handleAccept(entry)}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
                    >
                      <Check className="h-4 w-4" />
                      Accept — dùng train bot
                    </button>
                    <button
                      type="button"
                      disabled={busyId === entry.id}
                      onClick={() => handleReject(entry)}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-surface-border px-3 py-1.5 text-xs font-semibold text-text-secondary hover:bg-surface-muted disabled:opacity-50"
                    >
                      <X className="h-4 w-4" />
                      Reject
                    </button>
                  </div>
                </div>
              ) : entry.admin_note ? (
                <p className="border-t border-surface-border pt-2 text-xs text-text-muted">
                  Admin: {entry.admin_note}
                </p>
              ) : null}
            </article>
          ))
        )}
      </div>
    </>
  );
}
