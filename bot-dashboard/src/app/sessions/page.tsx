"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { getSessions } from "@/lib/api";
import type { SessionRow } from "@/lib/types";
import { fmtTs } from "@/lib/utils";

export default function SessionsPage() {
  const [total, setTotal] = useState(0);
  const [topics, setTopics] = useState(0);
  const [rows, setRows] = useState<SessionRow[]>([]);

  const load = useCallback(async () => {
    const data = await getSessions(40);
    setTotal(data.total);
    setTopics(data.active_topics);
    setRows(data.sessions);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <>
      <Header
        title="Sessions"
        subtitle="Phiên hội thoại từ sessions.db"
        hours={168}
        onHoursChange={() => {}}
        onRefresh={load}
      />

      <div className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="card p-4 text-center">
          <p className="text-2xl font-bold text-brand">{total}</p>
          <p className="text-xs text-text-muted">Total sessions</p>
        </div>
        <div className="card p-4 text-center">
          <p className="text-2xl font-bold text-brand">{topics}</p>
          <p className="text-xs text-text-muted">Active Lark topics</p>
        </div>
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-border bg-surface-muted text-left text-xs uppercase text-text-muted">
              <th className="px-4 py-3">Session</th>
              <th className="px-4 py-3">Updated</th>
              <th className="px-4 py-3">Turns</th>
              <th className="px-4 py-3">Keywords</th>
              <th className="px-4 py-3">Product</th>
              <th className="px-4 py-3">Pending</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.session_key} className="border-b border-surface-border">
                <td className="px-4 py-3 font-mono text-xs">{s.session_key.slice(0, 32)}</td>
                <td className="px-4 py-3">{fmtTs(s.updated_at)}</td>
                <td className="px-4 py-3">{s.turn_count}</td>
                <td className="px-4 py-3">{s.last_keywords || "—"}</td>
                <td className="px-4 py-3 max-w-[200px] truncate">{s.last_product || "—"}</td>
                <td className="px-4 py-3">{s.pending_province_for || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
