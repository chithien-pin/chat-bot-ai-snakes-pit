"use client";

import { RefreshCw } from "lucide-react";

type Props = {
  title: string;
  subtitle?: string;
  hours?: number;
  onHoursChange?: (h: number) => void;
  onRefresh?: () => void;
};

export function Header({ title, subtitle, hours, onHoursChange, onRefresh }: Props) {
  return (
    <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-text-primary">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-text-secondary">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-3">
        {hours != null && onHoursChange ? (
          <select
            value={hours}
            onChange={(e) => onHoursChange(Number(e.target.value))}
            className="rounded-xl border border-surface-border bg-surface px-4 py-2 text-sm font-medium shadow-sm outline-none focus:border-brand"
          >
            <option value={24}>24 giờ</option>
            <option value={72}>3 ngày</option>
            <option value={168}>7 ngày</option>
            <option value={720}>30 ngày</option>
          </select>
        ) : null}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="flex items-center gap-2 rounded-xl bg-brand px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-dark"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        )}
      </div>
    </header>
  );
}
