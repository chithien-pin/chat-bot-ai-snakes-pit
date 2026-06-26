import clsx from "clsx";

export function cn(...inputs: (string | false | null | undefined)[]) {
  return clsx(inputs);
}

export function fmtNum(n: number | null | undefined) {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toLocaleString("vi-VN");
}

export function fmtMs(n: number | null | undefined) {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}s`;
  return `${n}ms`;
}

export function fmtTs(ts: string | undefined) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("vi-VN", { hour12: false });
  } catch {
    return ts;
  }
}

export function statusColor(status: string) {
  if (status === "success" || status === "done") return "text-success bg-emerald-50";
  if (status === "error" || status === "failed") return "text-danger bg-red-50";
  if (status.startsWith("intent_") || status === "ask_province" || status === "warn")
    return "text-warning bg-amber-50";
  return "text-text-secondary bg-surface-muted";
}
