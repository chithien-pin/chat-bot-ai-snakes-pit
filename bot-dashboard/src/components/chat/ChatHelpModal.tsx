"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";

type ExampleItem = {
  label: string;
  bad?: string;
  good: string;
};

const SECTIONS: {
  title: string;
  intro?: string;
  bullets?: string[];
  examples?: ExampleItem[];
}[] = [
  {
    title: "1. Ghi rõ sản phẩm bạn cần",
    intro: "Bot tra cứu trên cellphones.com.vn — càng cụ thể, kết quả càng chính xác.",
    bullets: [
      "Nêu hãng + model + dung lượng + màu (nếu có).",
      "Ví dụ: iPhone 17 Pro Max 256GB Titan Tự Nhiên.",
      "Tránh câu quá chung: “điện thoại nào ngon” (trừ khi bạn muốn gợi ý theo ngân sách).",
    ],
    examples: [
      {
        label: "Giá sản phẩm",
        bad: "ip 17 pro max giá sao",
        good: "Giá iPhone 17 Pro Max 256GB hôm nay?",
      },
    ],
  },
  {
    title: "2. Hỏi tiếp trong cùng cuộc hội thoại",
    intro: "Sau câu đầu, bạn có thể hỏi ngắn — bot nhớ sản phẩm đang thảo luận.",
    bullets: [
      "“Còn hàng shop không?” · “Giá Smember bao nhiêu?” · “Trả góp được không?”",
      "“Còn màu nào khác?” · “Có khuyến mãi gì không?”",
      "Dùng các chip gợi ý phía trên ô nhập để điền sẵn câu hỏi.",
    ],
  },
  {
    title: "3. Tồn cửa hàng",
    bullets: [
      "Ghi rõ sản phẩm + khu vực: quận, tỉnh/thành hoặc địa chỉ gần bạn.",
      "Ví dụ: Shop quận 1 còn iPhone 16 Pro 256GB màu Titan không?",
      "Bot có thể hỏi lại tỉnh/thành nếu cần — trả lời để tra tồn chính xác hơn.",
    ],
  },
  {
    title: "4. Trả góp & thanh toán",
    bullets: [
      "Nêu sản phẩm + hình thức: CTTC (Home Credit, MCredit…), thẻ tín dụng, Kredivo/Fundiin.",
      "Với thẻ: thêm ngân hàng + kỳ hạn + loại thẻ (Visa/Master/JCB).",
      "Ví dụ: Trả góp Techcombank iPhone 17 256GB 6 tháng thẻ Visa.",
    ],
  },
  {
    title: "5. So sánh & tư vấn chọn mua",
    bullets: [
      "So sánh 2 sản phẩm: “So sánh iPhone 17 Pro Max và Galaxy S26 Ultra”.",
      "Theo ngân sách: “Laptop gaming dưới 20 triệu” · “Điện thoại tầm 10 triệu”.",
      "Theo danh mục + giá: “iPhone dưới 20 triệu”.",
    ],
  },
  {
    title: "6. Những điều nên tránh",
    bullets: [
      "Câu ngoài phạm vi CellphoneS (thời tiết, viết code, tin tức chung…).",
      "Đổi sang sản phẩm hoàn toàn khác giữa chừng mà không nêu tên mới.",
      "Chỉ gõ “giá sao” khi chưa hỏi sản phẩm nào trong phiên chat.",
    ],
  },
];

type Props = {
  open: boolean;
  onClose: () => void;
  onTryExample?: (prompt: string) => void;
};

export function ChatHelpModal({ open, onClose, onTryExample }: Props) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="chat-help-backdrop"
      role="presentation"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="chat-help-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="chat-help-title"
      >
        <div className="chat-help-header">
          <div>
            <h2 id="chat-help-title" className="chat-help-title">
              Hướng dẫn chat với CellphoneS AI
            </h2>
            <p className="chat-help-subtitle">
              Cách đặt câu hỏi để bot tìm đúng sản phẩm và trả lời chính xác nhất.
            </p>
          </div>
          <button
            type="button"
            className="chat-help-close"
            onClick={onClose}
            aria-label="Đóng hướng dẫn"
          >
            <X size={20} />
          </button>
        </div>

        <div className="chat-help-body">
          {SECTIONS.map((section) => (
            <section key={section.title} className="chat-help-section">
              <h3 className="chat-help-section-title">{section.title}</h3>
              {section.intro && <p className="chat-help-text">{section.intro}</p>}
              {section.bullets && (
                <ul className="chat-help-list">
                  {section.bullets.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
              {section.examples?.map((ex) => (
                <div key={ex.label} className="chat-help-example">
                  <div className="chat-help-example-label">{ex.label}</div>
                  {ex.bad && (
                    <div className="chat-help-example-row chat-help-example-bad">
                      <span className="chat-help-tag chat-help-tag-bad">Tránh</span>
                      <span>{ex.bad}</span>
                    </div>
                  )}
                  <div className="chat-help-example-row chat-help-example-good">
                    <span className="chat-help-tag chat-help-tag-good">Nên</span>
                    <span>{ex.good}</span>
                    {onTryExample && (
                      <button
                        type="button"
                        className="chat-help-try-btn"
                        onClick={() => {
                          onTryExample(ex.good);
                          onClose();
                        }}
                      >
                        Dùng mẫu
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </section>
          ))}

          <div className="chat-help-note">
            Giá, khuyến mãi và tồn kho lấy từ dữ liệu CellphoneS tại thời điểm tra cứu.
            Vui lòng xác nhận lại trên{" "}
            <a href="https://cellphones.com.vn" target="_blank" rel="noopener noreferrer">
              cellphones.com.vn
            </a>{" "}
            trước khi quyết định mua.
          </div>
        </div>

        <div className="chat-help-footer">
          <button type="button" className="chat-help-primary-btn" onClick={onClose}>
            Đã hiểu
          </button>
        </div>
      </div>
    </div>
  );
}
