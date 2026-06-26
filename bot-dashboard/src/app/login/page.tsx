"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { clearAuthCredentials, storeAuthCredentials } from "@/lib/auth";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const from = searchParams.get("from") || "/";
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        setError("Mật khẩu không đúng");
        return;
      }
      const data = (await res.json()) as { username?: string };
      storeAuthCredentials(data.username || "admin", password);
      router.replace(from.startsWith("/login") ? "/" : from);
      router.refresh();
    } catch {
      setError("Không kết nối được server");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-muted p-4">
      <form
        onSubmit={onSubmit}
        className="card w-full max-w-sm space-y-4 p-8"
      >
        <div>
          <h1 className="text-xl font-bold text-text-primary">Bot Dashboard</h1>
          <p className="mt-1 text-sm text-text-secondary">Nhập mật khẩu để truy cập</p>
        </div>
        <div>
          <label htmlFor="password" className="text-xs font-semibold uppercase text-text-muted">
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className="mt-1 w-full rounded-xl border border-surface-border bg-surface px-3 py-2 text-sm"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {error && <p className="text-sm text-danger">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-xl bg-brand py-2.5 text-sm font-semibold text-white hover:bg-brand-dark disabled:opacity-60"
        >
          {loading ? "Đang kiểm tra…" : "Đăng nhập"}
        </button>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-surface-muted">
          Loading…
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
