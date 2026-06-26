import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { sessionTokenForPassword } from "@/lib/auth-server";

const PUBLIC = new Set(["/login"]);

export async function middleware(request: NextRequest) {
  const password = process.env.DASHBOARD_PASSWORD?.trim();
  if (!password) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;
  if (
    PUBLIC.has(pathname)
    || pathname.startsWith("/_next")
    || pathname.startsWith("/api/auth/")
  ) {
    return NextResponse.next();
  }

  const session = request.cookies.get("dashboard_session")?.value;
  const expected = await sessionTokenForPassword(password);
  if (session && session === expected) {
    return NextResponse.next();
  }

  const login = new URL("/login", request.url);
  login.searchParams.set("from", pathname);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
