"use client";

import { useState, type FormEvent } from "react";
import { isValidChatName } from "@/lib/chat-auth";

type Props = {
  onSubmit: (name: string) => void;
};

export function ChatNameLogin({ onSubmit }: Props) {
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = name.trim();
    if (!isValidChatName(trimmed)) {
      setError("Vui lòng nhập tên (2–40 ký tự).");
      return;
    }
    setError("");
    onSubmit(trimmed);
  }

  return (
    <div className="chat-login-wrap">
      <div className="chat-login-card">
        <div className="chat-login-logo">CPS</div>
        <h1 style={{ fontSize: "1.5rem", fontWeight: 600, marginBottom: "0.5rem" }}>
          CellphoneS AI
        </h1>
        <p style={{ color: "#6e6e80", marginBottom: "1.5rem", fontSize: "0.95rem" }}>
          Nhập tên để bắt đầu chat thử nghiệm nội bộ
        </p>

        <form onSubmit={handleSubmit}>
          <label htmlFor="chat-name" style={{ display: "block", textAlign: "left" }}>
            <span style={{ fontSize: "0.875rem", color: "#6e6e80" }}>Tên của bạn</span>
            <input
              id="chat-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ví dụ: Minh, Lan, Team QA..."
              autoComplete="name"
              autoFocus
              maxLength={40}
              className="chat-name-input"
            />
          </label>
          {error && <p className="chat-error">{error}</p>}
          <button type="submit" className="chat-login-btn">
            Bắt đầu chat
          </button>
        </form>
      </div>
    </div>
  );
}
