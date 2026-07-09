"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Filter, Users } from "lucide-react";
import { Header } from "@/components/layout/Header";
import { getMessages } from "@/lib/api";
import type { MessageFilterUser, MessageRow, MessageUserGroup } from "@/lib/types";
import { cn, fmtMs, fmtNum, fmtTs, statusColor } from "@/lib/utils";

function fmtTokens(v: number | null | undefined, model?: string) {
  if (v != null && !Number.isNaN(v)) return fmtNum(v);
  if (model === "template") return "—";
  return "—";
}

function shortUserId(userId: string) {
  if (!userId) return "Ẩn danh";
  if (userId.length <= 12) return userId;
  return `${userId.slice(0, 8)}…${userId.slice(-4)}`;
}

function userDisplayLabel(userId: string, userName?: string) {
  const name = (userName || "").trim();
  if (name) return name;
  return shortUserId(userId);
}

function MessageTable({ rows }: { rows: MessageRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-surface-border bg-surface-muted text-left text-xs uppercase tracking-wide text-text-muted">
          <th className="px-4 py-3">Time</th>
          <th className="px-4 py-3">User</th>
          <th className="px-4 py-3">Câu hỏi (USER)</th>
          <th className="px-4 py-3">Platform</th>
          <th className="px-4 py-3">Status</th>
          <th className="px-4 py-3">Flags</th>
          <th className="px-4 py-3">Keywords</th>
          <th className="px-4 py-3">Resolve</th>
          <th className="px-4 py-3">Latency</th>
          <th className="px-4 py-3">Tokens</th>
          <th className="px-4 py-3">Model</th>
          <th className="px-4 py-3"></th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={`${r.ts}-${r.platform}-${r.user_id || ""}`}
            className="border-b border-surface-border hover:bg-surface-muted/50"
          >
            <td className="px-4 py-3 whitespace-nowrap">{fmtTs(r.ts)}</td>
            <td className="max-w-[120px] truncate px-4 py-3 text-xs">
              {userDisplayLabel(r.user_id || "", r.user_name)}
            </td>
            <td
              className="max-w-[240px] truncate px-4 py-3 text-sm text-text-primary"
              title={r.user_question || undefined}
            >
              {r.user_question || "—"}
            </td>
            <td className="px-4 py-3">{r.platform}</td>
            <td className="px-4 py-3">
              <span className={cn("badge", statusColor(r.status))}>{r.status}</span>
            </td>
            <td className="px-4 py-3">
              <div className="flex flex-wrap gap-1">
                {r.is_follow_up ? (
                  <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700">
                    follow-up
                  </span>
                ) : null}
                {r.reuse_product_context ? (
                  <span className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold text-violet-700">
                    context
                  </span>
                ) : null}
                {r.shop_stock_scenario || r.shop_stock_trigger ? (
                  <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700">
                    shop stock
                  </span>
                ) : null}
              </div>
            </td>
            <td className="max-w-[180px] truncate px-4 py-3 font-medium">
              {r.search_keywords || "—"}
            </td>
            <td className="px-4 py-3">
              <code className="text-xs text-brand">{r.resolve_source || "—"}</code>
            </td>
            <td className="px-4 py-3 whitespace-nowrap">
              <span className="font-semibold">{fmtMs(r.total_latency_ms)}</span>
              <p className="text-[10px] text-text-muted">
                kw {fmtMs(r.latency_keyword_ms)} · fetch {fmtMs(r.latency_fetch_ms)} · llm{" "}
                {fmtMs(r.latency_gemini_ms)}
              </p>
            </td>
            <td className="px-4 py-3 text-xs">
              <p className="font-semibold">
                {fmtTokens(r.prompt_tokens, r.gemini_model)} /{" "}
                {fmtTokens(r.completion_tokens, r.gemini_model)}
              </p>
              {r.total_tokens != null ? (
                <p className="text-[10px] text-text-muted">Σ {fmtNum(r.total_tokens)}</p>
              ) : null}
            </td>
            <td className="px-4 py-3 text-xs">{r.gemini_model || "—"}</td>
            <td className="px-4 py-3">
              <Link
                href={`/pipeline?q=${encodeURIComponent(r.ts || "")}`}
                className="text-xs font-semibold text-brand hover:underline"
              >
                Pipeline
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function UserGroupCard({
  group,
  defaultOpen,
}: {
  group: MessageUserGroup;
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 border-b border-surface-border bg-surface-muted/60 px-4 py-3 text-left hover:bg-surface-muted"
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-text-muted" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-text-muted" />
        )}
        <Users className="h-4 w-4 shrink-0 text-brand" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold text-text-primary">
            {userDisplayLabel(group.user_id, group.user_name)}
          </p>
          <p className="text-xs text-text-muted">
            {group.platform || "—"} · {group.message_count} tin · mới nhất {fmtTs(group.last_ts)}
          </p>
          {group.user_name && group.user_id ? (
            <p className="truncate text-[10px] text-text-muted">{group.user_id}</p>
          ) : null}
        </div>
        {!group.user_name && group.user_id ? (
          <code className="hidden text-[10px] text-text-muted sm:block">{group.user_id}</code>
        ) : null}
      </button>
      {open ? (
        <div className="overflow-x-auto">
          <MessageTable rows={group.messages} />
        </div>
      ) : null}
    </div>
  );
}

export default function MessagesPage() {
  const [hours, setHours] = useState(168);
  const [rows, setRows] = useState<MessageRow[]>([]);
  const [groups, setGroups] = useState<MessageUserGroup[]>([]);
  const [totalMatched, setTotalMatched] = useState(0);
  const [filterOptions, setFilterOptions] = useState<{
    platforms: string[];
    statuses: string[];
    users: MessageFilterUser[];
  }>({ platforms: [], statuses: [], users: [] });

  const [platform, setPlatform] = useState("");
  const [status, setStatus] = useState("");
  const [userId, setUserId] = useState("");
  const [shopStockOnly, setShopStockOnly] = useState(false);
  const [followUpOnly, setFollowUpOnly] = useState(false);
  const [reuseContextOnly, setReuseContextOnly] = useState(false);
  const [groupByUser, setGroupByUser] = useState(true);

  const load = useCallback(async () => {
    const data = await getMessages(hours, 120, {
      platform: platform || undefined,
      status: status || undefined,
      user_id: userId || undefined,
      shop_stock_only: shopStockOnly,
      follow_up_only: followUpOnly,
      reuse_context_only: reuseContextOnly,
      group_by_user: groupByUser,
    });
    setRows(data.messages);
    setGroups(data.groups || []);
    setTotalMatched(data.total_matched);
    setFilterOptions(data.filters);
  }, [
    hours,
    platform,
    status,
    userId,
    shopStockOnly,
    followUpOnly,
    reuseContextOnly,
    groupByUser,
  ]);

  useEffect(() => {
    load();
  }, [load]);

  const larkUsers = useMemo(
    () => filterOptions.users.filter((u) => u.platform === "lark" || !u.platform),
    [filterOptions.users],
  );

  const resetFilters = () => {
    setPlatform("");
    setStatus("");
    setUserId("");
    setShopStockOnly(false);
    setFollowUpOnly(false);
    setReuseContextOnly(false);
  };

  const hasActiveFilters =
    platform || status || userId || shopStockOnly || followUpOnly || reuseContextOnly;

  return (
    <>
      <Header
        title="Messages"
        subtitle="Lịch sử tin nhắn — gom nhóm theo user Lark, lọc theo trạng thái & shop stock"
        hours={hours}
        onHoursChange={setHours}
        onRefresh={load}
      />

      <div className="card mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Filter className="h-4 w-4 text-brand" />
          <span className="text-sm font-semibold">Bộ lọc</span>
          {hasActiveFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="ml-auto text-xs font-semibold text-brand hover:underline"
            >
              Xóa lọc
            </button>
          ) : null}
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs font-medium text-text-muted">
            Platform
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="mt-1 w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">Tất cả</option>
              {filterOptions.platforms.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-text-muted">
            User Lark
            <select
              value={userId}
              onChange={(e) => setUserId(e.target.value)}
              className="mt-1 w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">Tất cả user</option>
              {larkUsers.map((u) => (
                <option key={u.user_id} value={u.user_id}>
                  {userDisplayLabel(u.user_id, u.user_name)} ({u.count})
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs font-medium text-text-muted">
            Status
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              className="mt-1 w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm"
            >
              <option value="">Tất cả</option>
              {filterOptions.statuses.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-col justify-end gap-2 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={groupByUser}
                onChange={(e) => setGroupByUser(e.target.checked)}
              />
              Gom nhóm theo user
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={shopStockOnly}
                onChange={(e) => setShopStockOnly(e.target.checked)}
              />
              Chỉ shop stock
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={followUpOnly}
                onChange={(e) => setFollowUpOnly(e.target.checked)}
              />
              Chỉ follow-up
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={reuseContextOnly}
                onChange={(e) => setReuseContextOnly(e.target.checked)}
              />
              Chỉ reuse context
            </label>
          </div>
        </div>
        <p className="mt-3 text-xs text-text-muted">
          Hiển thị {rows.length} / {totalMatched} tin khớp bộ lọc
        </p>
      </div>

      {groupByUser && groups.length > 0 ? (
        <div className="space-y-4">
          {groups.map((group, idx) => (
            <UserGroupCard key={group.user_id || "_anon"} group={group} defaultOpen={idx === 0} />
          ))}
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <MessageTable rows={rows} />
        </div>
      )}
    </>
  );
}
