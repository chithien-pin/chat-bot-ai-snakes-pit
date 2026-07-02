# Eval pipeline — golden set + LLM-as-judge

Đánh giá chất lượng câu trả lời chatbot CellphoneS bằng bộ case cố định.

## Yêu cầu

- File `.env` với API key LLM và kết nối CPS (giống khi chạy bot).
- **Không** chạy trong CI mặc định (tốn phí API + gọi mạng thật).

## Chạy

```bash
# Toàn bộ golden set (~40 case) + LLM judge
python -m tests.eval.run_eval

# Thử nhanh 5 case
python -m tests.eval.run_eval --limit 5

# Chỉ nhóm giá
python -m tests.eval.run_eval --scenario price --limit 10

# Chỉ chạy pipeline, không gọi judge (tiết kiệm token)
python -m tests.eval.run_eval --limit 5 --skip-judge
```

## Golden set

File: `tests/eval/golden_set.jsonl`

Mỗi dòng JSON:

| Trường | Mô tả |
|--------|--------|
| `id` | Mã case |
| `scenario` | Nhóm kịch bản (price, installment, follow_up, ...) |
| `question` | Câu hỏi khách |
| `context` | Ngữ cảnh session (tuỳ chọn, multi-turn) |
| `expected_facts` | Các ý bắt buộc phải có trong câu trả lời đúng |

## Báo cáo

Output trong `tests/eval/reports/`:

- `eval_<timestamp>.json` — chi tiết từng case + thống kê theo scenario
- `eval_<timestamp>.csv` — bảng tóm tắt để xem trong spreadsheet

Các metric bổ sung từ pipeline (Phase 1–4):

- `price_mismatch_detected` — answer guard phát hiện số tiền lạ
- `latency_shop_stock_ms` / `latency_enrich_ms` — thời gian song song hoá
- `low_confidence_route` — query router không chắc

## Thêm case mới

1. Thêm dòng vào `golden_set.jsonl`
2. Chạy lại eval và so sánh `avg_score` / `scenario_stats` trước-sau thay đổi code
