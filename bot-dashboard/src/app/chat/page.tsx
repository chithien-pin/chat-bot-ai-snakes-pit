"use client";

import { useCallback, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowUp, CreditCard, Gift, Palette, Scale, Store, Trash2, LogOut, Tag } from "lucide-react";

import { clearChatSession, sendChatFeedback, sendChatMessage } from "@/lib/api";
import {
  chatUserIdForName,
  clearChatDisplayName,
  getChatDisplayName,
  setChatDisplayName,
} from "@/lib/chat-auth";
import { ChatNameLogin } from "@/components/chat/ChatNameLogin";
import { ChatHelpModal } from "@/components/chat/ChatHelpModal";

const SESSION_KEY = "cps_web_chat_session";

type ChatRole = "user" | "assistant";

type ChatEntry = {
  id: string;
  role: ChatRole;
  content: string;
  messageId?: string;
  productUrl?: string;
  feedback?: "helpful" | "not_helpful";
};

const STARTER_PROMPTS = [
  {
    title: "Giá iPhone 17 Pro Max",
    desc: "Hỏi giá và khuyến mãi Smember",
    prompt: "Giá iPhone 17 Pro Max 256GB hôm nay?",
  },
  {
    title: "Tồn cửa hàng",
    desc: "Shop còn hàng theo màu/dung lượng",
    prompt: "Shop còn iPhone 17 Pro Max 256GB màu titan không?",
  },
  {
    title: "Trả góp Techcombank",
    desc: "Kỳ hạn, thẻ Visa, phí chuyển đổi",
    prompt: "Trả góp Techcombank iPhone 17 256gb 6 tháng thẻ Visa",
  },
  {
    title: "So sánh 2 sản phẩm",
    desc: "Camera, pin, giá, ưu đãi",
    prompt: "So sánh iPhone 17 Pro Max và Galaxy S26 Ultra",
  },
];

/** Chip gợi ý hỏi tiếp — hiển thị phía trên input khi đang trong hội thoại. */
const FOLLOW_UP_CHIPS = [
  { label: "Còn hàng shop", prompt: "Shop còn hàng không?", icon: Store },
  { label: "Giá Smember", prompt: "Giá Smember bao nhiêu?", icon: Tag },
  { label: "Trả góp", prompt: "Trả góp được không?", icon: CreditCard },
  { label: "Khuyến mãi", prompt: "Có khuyến mãi gì không?", icon: Gift },
  { label: "Màu khác", prompt: "Còn màu nào khác?", icon: Palette },
  { label: "So sánh SP", prompt: "So sánh với sản phẩm tương tự", icon: Scale },
];

function randomId(): string {
  if (typeof crypto !== "undefined" && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return `u-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function getSessionId(): string {
  if (typeof window === "undefined") return "default";
  let id = localStorage.getItem(SESSION_KEY);
  if (!id) {
    id = randomId();
    localStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

function userInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "U";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function ChatPage() {
  const [ready, setReady] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [helpOpen, setHelpOpen] = useState(false);

  const sessionId = useRef("default");
  const userId = useRef("");
  const threadRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    sessionId.current = getSessionId();
    const name = getChatDisplayName();
    setDisplayName(name);
    if (name) userId.current = chatUserIdForName(name);
    setReady(true);
  }, []);

  useEffect(() => {
    threadRef.current?.scrollTo({
      top: threadRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading, statusText]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const handleNameLogin = (name: string) => {
    setChatDisplayName(name);
    setDisplayName(name);
    userId.current = chatUserIdForName(name);
    setMessages([]);
    setInput("");
  };

  const handleChangeName = () => {
    clearChatDisplayName();
    setDisplayName("");
    setMessages([]);
    setInput("");
  };

  const submitMessage = useCallback(
    async (text: string) => {
      const question = text.trim();
      if (!question || loading || !displayName) return;

      setMessages((prev) => [
        ...prev,
        { id: randomId(), role: "user", content: question },
      ]);
      setInput("");
      setLoading(true);
      setStatusText("Đang tìm kiếm thông tin sản phẩm...");

      try {
        const res = await sendChatMessage(
          question,
          sessionId.current,
          userId.current,
          displayName,
        );
        setMessages((prev) => [
          ...prev,
          {
            id: randomId(),
            role: "assistant",
            content: res.reply,
            messageId: res.message_id,
            productUrl: res.product_url || res.response_link_url,
          },
        ]);
      } catch (err) {
        console.error(err);
        const detail = err instanceof Error ? err.message : "Lỗi không xác định";
        setMessages((prev) => [
          ...prev,
          {
            id: randomId(),
            role: "assistant",
            content: `⚠️ Không nhận được phản hồi từ bot.\n\n_${detail}_\n\nKiểm tra \`dashboard_api.py\` đang chạy trên cổng 8080.`,
          },
        ]);
      } finally {
        setLoading(false);
        setStatusText("");
      }
    },
    [loading, displayName],
  );

  const handleSuggestionClick = (prompt: string) => {
    if (loading) return;
    setInput(prompt);
    requestAnimationFrame(() => {
      textareaRef.current?.focus();
      const el = textareaRef.current;
      if (el) {
        el.selectionStart = el.selectionEnd = prompt.length;
      }
    });
  };

  const handleSubmit = (e?: { preventDefault?: () => void }) => {
    e?.preventDefault?.();
    if (input.trim()) void submitMessage(input);
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleClear = async () => {
    if (loading) return;
    try {
      await clearChatSession(sessionId.current, userId.current);
      setMessages([]);
      setInput("");
    } catch (err) {
      console.error(err);
    }
  };

  const handleFeedback = async (
    entry: ChatEntry,
    rating: "helpful" | "not_helpful",
  ) => {
    if (!entry.messageId || entry.feedback) return;
    try {
      await sendChatFeedback(
        sessionId.current,
        userId.current,
        entry.messageId,
        rating,
      );
      setMessages((prev) =>
        prev.map((m) => (m.id === entry.id ? { ...m, feedback: rating } : m)),
      );
    } catch (err) {
      console.error(err);
    }
  };

  if (!ready) return null;
  if (!displayName) return <ChatNameLogin onSubmit={handleNameLogin} />;

  const hasThread = messages.length > 0;

  return (
    <div className="chat-shell">
      <button
        type="button"
        className="chat-help-fab"
        onClick={() => setHelpOpen(true)}
        aria-label="Hướng dẫn cách chat"
        title="Hướng dẫn cách chat"
      >
        ?
      </button>

      <ChatHelpModal
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        onTryExample={handleSuggestionClick}
      />

      <header className="chat-header">
        <div>
          <div className="chat-header-title">CellphoneS AI</div>
          <div className="chat-header-sub">Xin chào, {displayName}</div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {hasThread && (
            <button type="button" className="chat-header-btn" onClick={() => void handleClear()}>
              <Trash2 size={14} style={{ display: "inline", marginRight: 4, verticalAlign: -2 }} />
              Xóa chat
            </button>
          )}
          <button type="button" className="chat-header-btn" onClick={handleChangeName}>
            <LogOut size={14} style={{ display: "inline", marginRight: 4, verticalAlign: -2 }} />
            Đổi tên
          </button>
        </div>
      </header>

      <div ref={threadRef} className="chat-messages">
        {!hasThread && !loading ? (
          <div className="chat-empty">
            <h1>Bạn cần tư vấn gì?</h1>
            <div className="chat-suggestions">
              {STARTER_PROMPTS.map((item) => (
                <button
                  key={item.title}
                  type="button"
                  className="chat-suggestion"
                  onClick={() => handleSuggestionClick(item.prompt)}
                >
                  <div className="chat-suggestion-title">{item.title}</div>
                  <div className="chat-suggestion-desc">{item.desc}</div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((entry) => (
              <div
                key={entry.id}
                className={`chat-row ${entry.role === "user" ? "chat-row-user" : "chat-row-assistant"}`}
              >
                <div className="chat-row-inner">
                  <div
                    className={`chat-avatar ${entry.role === "user" ? "chat-avatar-user" : "chat-avatar-bot"}`}
                  >
                    {entry.role === "user" ? userInitials(displayName) : "AI"}
                  </div>
                  <div className="chat-bubble">
                    {entry.content}
                    {entry.role === "assistant" && entry.messageId && (
                      <div className="chat-meta">
                        {entry.productUrl && (
                          <a href={entry.productUrl} target="_blank" rel="noopener noreferrer">
                            Xem trên CellphoneS →
                          </a>
                        )}
                        {!entry.feedback ? (
                          <>
                            <button
                              type="button"
                              onClick={() => void handleFeedback(entry, "helpful")}
                            >
                              👍 Hữu ích
                            </button>
                            <button
                              type="button"
                              onClick={() => void handleFeedback(entry, "not_helpful")}
                            >
                              👎 Không hữu ích
                            </button>
                          </>
                        ) : (
                          <span style={{ fontSize: "0.75rem", color: "#6e6e80" }}>
                            {entry.feedback === "helpful"
                              ? "✓ Cảm ơn đánh giá"
                              : "✓ Đã ghi nhận phản hồi"}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}

            {loading && (
              <div className="chat-row chat-row-assistant">
                <div className="chat-row-inner">
                  <div className="chat-avatar chat-avatar-bot">AI</div>
                  <div className="chat-bubble">
                    <div className="chat-typing" aria-label="Đang trả lời">
                      <span />
                      <span />
                      <span />
                    </div>
                    {statusText && (
                      <div style={{ fontSize: "0.8rem", color: "#6e6e80", marginTop: "0.5rem" }}>
                        {statusText}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      <div className="chat-composer-wrap">
        {hasThread && (
          <div className="chat-quick-chips" role="group" aria-label="Gợi ý câu hỏi nhanh">
            {FOLLOW_UP_CHIPS.map((chip) => {
              const Icon = chip.icon;
              return (
                <button
                  key={chip.label}
                  type="button"
                  className="chat-quick-chip"
                  disabled={loading}
                  onClick={() => handleSuggestionClick(chip.prompt)}
                >
                  <Icon size={14} aria-hidden />
                  {chip.label}
                </button>
              );
            })}
          </div>
        )}
        <form
          className="chat-composer-box"
          onSubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          <textarea
            ref={textareaRef}
            className="chat-composer-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Hỏi về sản phẩm CellphoneS..."
            rows={1}
            disabled={loading}
          />
          <button
            type="submit"
            className="chat-send-btn"
            disabled={loading || !input.trim()}
            aria-label="Gửi"
          >
            <ArrowUp size={18} />
          </button>
        </form>
        <p
          style={{
            textAlign: "center",
            fontSize: "0.7rem",
            color: "#9ca3af",
            marginTop: "0.5rem",
          }}
        >
          Bot có thể mắc lỗi. Giá và tồn kho vui lòng xác nhận trên cellphones.com.vn
        </p>
      </div>
    </div>
  );
}
