"""
CPS Bot — tư vấn sản phẩm CellphoneS (Telegram, Lark, LLM).

Cấu trúc:
  cps_bot/cps/       — API GraphQL Cellphones, scraper
  cps_bot/browse/    — category, budget, fast reply
  cps_bot/llm/       — Gemini / DeepSeek / BytePlus, intent
  cps_bot/core/      — session, conversation, metrics
  cps_bot/feedback/  — đánh giá user + training loop
  cps_bot/lark/      — Lark WS patch
  cps_bot/sync/      — đồng bộ menu / attribute maps
  cps_bot/apps/      — entry implementations
  dashboard/         — dashboard readers + static UI
  tests/             — unit tests
"""

__version__ = "1.0.0"
