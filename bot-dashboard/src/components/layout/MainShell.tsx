"use client";

import { usePathname } from "next/navigation";

export function MainShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const isLogin = path === "/login";

  if (isLogin) {
    return <>{children}</>;
  }

  return (
    <main className="min-h-screen pl-[var(--sidebar-width)]">
      <div className="mx-auto max-w-[1400px] px-6 py-8">{children}</div>
    </main>
  );
}
