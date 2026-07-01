import { NextRequest, NextResponse } from "next/server";
import { proxyChatPost } from "@/lib/chat-api-server";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { status, data } = await proxyChatPost("/api/chat/feedback", body);
    return NextResponse.json(data, { status });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Proxy error";
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}
