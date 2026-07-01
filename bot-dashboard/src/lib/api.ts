import { authFetchInit } from "./auth";

const API = process.env.NEXT_PUBLIC_API_URL?.trim() || "";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API}${path}`, authFetchInit());
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export function getOverview(hours = 168) {
  return fetchJson<{
    overview: import("./types").Overview;
    pipeline_funnel: { stage: string; count: number }[];
    scenario_enrichment: Record<string, number>;
    api_calls: Record<string, number>;
  }>(`/api/overview?hours=${hours}`);
}

export function getTimeline(hours = 168) {
  return fetchJson<import("./types").Timeline>(`/api/timeline?hours=${hours}`);
}

export function getMessages(
  hours = 168,
  limit = 80,
  filters: import("./types").MessageQueryFilters = {},
) {
  const q = new URLSearchParams({
    hours: String(hours),
    limit: String(limit),
  });
  if (filters.platform) q.set("platform", filters.platform);
  if (filters.status) q.set("status", filters.status);
  if (filters.user_id) q.set("user_id", filters.user_id);
  if (filters.shop_stock_only) q.set("shop_stock_only", "true");
  if (filters.follow_up_only) q.set("follow_up_only", "true");
  if (filters.reuse_context_only) q.set("reuse_context_only", "true");
  if (filters.group_by_user) q.set("group_by_user", "true");
  return fetchJson<import("./types").MessagesResponse>(`/api/messages?${q}`);
}

export function getPipelines(hours = 168, limit = 30) {
  return fetchJson<{ pipelines: import("./types").PipelineTrace[] }>(
    `/api/pipelines?hours=${hours}&limit=${limit}`,
  );
}

export function getPipeline(id: string) {
  return fetchJson<import("./types").PipelineTrace>(
    `/api/pipelines/${encodeURIComponent(id)}`,
  );
}

export function getSessions(limit = 25) {
  return fetchJson<{
    total: number;
    active_topics: number;
    sessions: import("./types").SessionRow[];
  }>(`/api/sessions?limit=${limit}`);
}

export function getDataHealth() {
  return fetchJson<Record<string, Record<string, unknown>>>(`/api/data-health`);
}

export function getConfig() {
  return fetchJson<{ llm_provider: string; llm_model: string }>(`/api/config`);
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const auth = authFetchInit();
  const res = await fetch(`${API}${path}`, {
    ...auth,
    method: "POST",
    headers: {
      ...(auth.headers as Record<string, string>),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export function getFeedbackTraining(status?: string, limit = 50) {
  const q = new URLSearchParams({ limit: String(limit) });
  if (status) q.set("status", status);
  return fetchJson<{
    stats: import("./types").FeedbackTrainingStats;
    entries: import("./types").FeedbackTrainingEntry[];
  }>(`/api/feedback/training?${q}`);
}

export function acceptFeedbackTraining(entryId: string, adminNote = "") {
  return postJson<{ ok: boolean; entry: import("./types").FeedbackTrainingEntry }>(
    `/api/feedback/training/${encodeURIComponent(entryId)}/accept`,
    { admin_note: adminNote },
  );
}

export function rejectFeedbackTraining(entryId: string, adminNote = "") {
  return postJson<{ ok: boolean; entry: import("./types").FeedbackTrainingEntry }>(
    `/api/feedback/training/${encodeURIComponent(entryId)}/reject`,
    { admin_note: adminNote },
  );
}

export type ChatMessageResponse = {
  reply: string;
  message_id: string;
  status: string;
  product_url: string;
  product_name: string;
  product_id: string;
  search_keywords: string;
  response_link_url: string;
};

export function sendChatMessage(
  message: string,
  sessionId: string,
  userId: string,
  userName = "",
) {
  return postJsonPublic<ChatMessageResponse>("/api/chat", {
    message,
    session_id: sessionId,
    user_id: userId,
    user_name: userName,
  });
}

export function clearChatSession(sessionId: string, userId: string) {
  return postJsonPublic<{ ok: boolean }>("/api/chat/clear", {
    session_id: sessionId,
    user_id: userId,
  });
}

export function sendChatFeedback(
  sessionId: string,
  userId: string,
  messageId: string,
  rating: "helpful" | "not_helpful",
  comment = "",
) {
  return postJsonPublic<{ ok: boolean }>("/api/chat/feedback", {
    session_id: sessionId,
    user_id: userId,
    message_id: messageId,
    rating,
    comment,
  });
}

async function postJsonPublic<T>(path: string, body: unknown): Promise<T> {
  const API = process.env.NEXT_PUBLIC_API_URL?.trim() || "";
  const res = await fetch(`${API}${path}`, {
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
    data = { detail: text };
  }
  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return data as T;
}
