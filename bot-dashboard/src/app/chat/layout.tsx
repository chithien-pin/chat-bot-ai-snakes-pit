import type { Metadata } from "next";
import "./chat.css";

export const metadata: Metadata = {
  title: "CellphoneS AI Chat",
  description: "Trợ lý tư vấn sản phẩm CellphoneS",
};

export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <div className="ai-chat-page">{children}</div>;
}
