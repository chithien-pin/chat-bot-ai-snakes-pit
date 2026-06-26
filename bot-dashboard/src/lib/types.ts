export type PipelineStep = {
  id: string;
  title: string;
  status: "done" | "failed" | "skipped" | "warn";
  duration_ms: number | null;
  details: Record<string, unknown>;
};

export type PipelineTrace = {
  id: string;
  ts: string;
  platform: string;
  status: string;
  early_exit: boolean;
  total_latency_ms: number;
  accounted_latency_ms: number;
  search_keywords: string;
  resolve_source: string;
  steps: PipelineStep[];
};

export type Overview = {
  total_messages: number;
  success_rate: number;
  status_counts: Record<string, number>;
  platform_counts: Record<string, number>;
  resolve_source_counts: Record<string, number>;
  latency: {
    total: LatencyStat;
    keyword: LatencyStat;
    fetch: LatencyStat;
    llm: LatencyStat;
  };
  feedback: {
    total: number;
    helpful: number;
    not_helpful: number;
    helpful_rate: number | null;
  };
  llm: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    messages_with_tokens: number;
    avg_prompt_tokens: number | null;
    avg_completion_tokens: number | null;
    avg_tokens: number | null;
    by_model: Record<
      string,
      {
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
        calls: number;
      }
    >;
  };
  shop_stock_queries: number;
  compare_queries: number;
  ambiguous_search: number;
};

export type LatencyStat = {
  avg: number | null;
  p50: number | null;
  p95: number | null;
  max: number | null;
};

export type Timeline = {
  labels: string[];
  total: number[];
  success: number[];
  error: number[];
  tokens?: {
    labels: string[];
    prompt_tokens: number[];
    completion_tokens: number[];
    total_tokens: number[];
  };
};

export type MessageRow = {
  ts: string;
  platform: string;
  chat_id?: string;
  user_id?: string;
  user_name?: string;
  thread_key?: string;
  status: string;
  resolve_source: string;
  search_keywords: string;
  product_id: string;
  total_latency_ms: number;
  latency_keyword_ms: number;
  latency_fetch_ms: number;
  latency_gemini_ms: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  gemini_model?: string;
  llm_provider?: string;
  is_follow_up?: boolean;
  reuse_product_context?: boolean;
  shop_stock_scenario?: boolean;
  shop_stock_trigger?: boolean;
  question_len?: number;
  error?: string;
};

export type MessageUserGroup = {
  user_id: string;
  user_name?: string;
  platform: string;
  message_count: number;
  last_ts: string;
  messages: MessageRow[];
};

export type MessageFilterUser = {
  user_id: string;
  user_name?: string;
  count: number;
  platform: string;
};

export type MessagesResponse = {
  messages: MessageRow[];
  total_matched: number;
  filters: {
    platforms: string[];
    statuses: string[];
    users: MessageFilterUser[];
  };
  groups?: MessageUserGroup[];
};

export type MessageQueryFilters = {
  platform?: string;
  status?: string;
  user_id?: string;
  shop_stock_only?: boolean;
  follow_up_only?: boolean;
  reuse_context_only?: boolean;
  group_by_user?: boolean;
};

export type SessionRow = {
  session_key: string;
  updated_at: string;
  turn_count: number;
  last_user: string;
  last_keywords: string;
  last_product: string;
  pending_province_for: string;
};

export type FeedbackTrainingEntry = {
  id: string;
  ts: string;
  platform: string;
  rating: "helpful" | "not_helpful" | string;
  status: "pending" | "accepted" | "rejected" | string;
  user_question: string;
  bot_answer: string;
  search_keywords: string;
  product_id: string;
  product_name: string;
  product_url: string;
  user_comment: string;
  admin_note: string;
  chat_id: string;
  user_id: string;
  message_id: string;
  accepted_at: string;
  rejected_at: string;
};

export type FeedbackTrainingStats = {
  total: number;
  pending: number;
  accepted: number;
  rejected: number;
  helpful: number;
  not_helpful: number;
};
