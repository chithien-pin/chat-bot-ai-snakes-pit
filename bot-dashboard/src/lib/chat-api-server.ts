const CHAT_API_BACKEND =
  process.env.API_BACKEND_URL?.trim() || "http://127.0.0.1:8080";

export async function proxyChatPost(path: string, body: unknown) {
  const res = await fetch(`${CHAT_API_BACKEND}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });

  const text = await res.text();
  let data: unknown = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text || "Backend response invalid" };
  }

  return { status: res.status, data };
}
