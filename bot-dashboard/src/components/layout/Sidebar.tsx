"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BarChart3,
  Database,
  GitBranch,
  LayoutDashboard,
  LogOut,
  MessageSquare,
  ThumbsUp,
  Users,
} from "lucide-react";
import { clearAuthCredentials } from "@/lib/auth";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/pipeline", label: "Pipeline", icon: GitBranch },
  { href: "/messages", label: "Messages", icon: MessageSquare },
  { href: "/feedback", label: "Feedback", icon: ThumbsUp },
  { href: "/sessions", label: "Sessions", icon: Users },
  { href: "/data", label: "Data Sync", icon: Database },
];

export function Sidebar() {
  const path = usePathname();
  const router = useRouter();

  if (path === "/login") {
    return null;
  }

  async function logout() {
    clearAuthCredentials();
    await fetch("/api/auth/logout", { method: "POST" });
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-[var(--sidebar-width)] flex-col border-r border-surface-border bg-surface px-4 py-6">
      <div className="mb-8 flex items-center gap-3 px-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand to-brand-dark text-white shadow-md">
          <Activity className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-bold text-text-primary">CPS Bot</p>
          <p className="text-xs text-text-muted">Analytics</p>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              "nav-item",
              (href === "/" ? path === "/" : path.startsWith(href)) && "nav-item-active",
            )}
          >
            <Icon className="h-5 w-5 shrink-0" />
            {label}
          </Link>
        ))}
      </nav>

      <div className="mt-auto space-y-2">
        <button
          type="button"
          onClick={logout}
          className="nav-item w-full text-left text-text-muted hover:text-danger"
        >
          <LogOut className="h-5 w-5 shrink-0" />
          Đăng xuất
        </button>
        <div className="rounded-xl bg-brand-light p-4">
        <div className="flex items-center gap-2 text-brand-dark">
          <BarChart3 className="h-4 w-4" />
          <span className="text-xs font-semibold">Live metrics</span>
        </div>
        <p className="mt-1 text-xs text-text-secondary">
          Dữ liệu từ <code className="text-[10px]">metrics.log</code>
        </p>
        </div>
      </div>
    </aside>
  );
}
