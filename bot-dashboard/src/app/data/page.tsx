"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/layout/Header";
import { getDataHealth } from "@/lib/api";
import { fmtTs } from "@/lib/utils";

export default function DataPage() {
  const [health, setHealth] = useState<Record<string, Record<string, unknown>>>({});

  const load = useCallback(async () => {
    setHealth(await getDataHealth());
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const blocks = [
    { key: "menu_category_map", title: "Menu → Category map" },
    { key: "category_attributes_map", title: "Category attributes" },
  ];

  return (
    <>
      <Header
        title="Data Sync Health"
        subtitle="Trạng thái menu map & category attributes sync"
        hours={168}
        onHoursChange={() => {}}
        onRefresh={load}
      />

      <div className="grid gap-6 md:grid-cols-2">
        {blocks.map(({ key, title }) => {
          const m = health[key] || {};
          return (
            <div key={key} className="card p-6">
              <h3 className="font-semibold text-text-primary">{title}</h3>
              {!m.exists ? (
                <p className="mt-4 text-sm text-text-muted">File chưa tồn tại</p>
              ) : (
                <dl className="mt-4 grid gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-text-muted">Path</dt>
                    <dd className="font-mono text-xs break-all">{String(m.path)}</dd>
                  </div>
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <dt className="text-xs text-text-muted">Size</dt>
                      <dd className="font-semibold">{String(m.size_mb)} MB</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-text-muted">Categories</dt>
                      <dd className="font-semibold">{String(m.category_count ?? m.menu_entries ?? "—")}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-text-muted">Synced</dt>
                      <dd>{fmtTs(String(m.updated_at || ""))}</dd>
                    </div>
                    <div>
                      <dt className="text-xs text-text-muted">Processed</dt>
                      <dd>{String(m.processed_ids ?? "—")}</dd>
                    </div>
                  </div>
                </dl>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
