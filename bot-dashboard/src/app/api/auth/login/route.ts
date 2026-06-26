import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { passwordsMatch, sessionTokenForPassword } from "@/lib/auth-server";

export async function POST(request: Request) {
  const configured = process.env.DASHBOARD_PASSWORD?.trim();
  if (!configured) {
    return NextResponse.json({ ok: true, username: "admin" });
  }

  let body: { password?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid body" }, { status: 400 });
  }

  const password = (body.password || "").trim();
  const user = process.env.DASHBOARD_USER || "admin";

  if (!passwordsMatch(password, configured)) {
    return NextResponse.json({ detail: "Unauthorized" }, { status: 401 });
  }

  const token = await sessionTokenForPassword(password);
  const cookieStore = await cookies();
  cookieStore.set("dashboard_session", token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 24 * 7,
  });

  return NextResponse.json({ ok: true, username: user });
}
