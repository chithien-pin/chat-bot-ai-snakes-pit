#!/usr/bin/env bash
# Xóa toàn bộ context/lịch sử chat bot + restart service (nếu chạy Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Xóa sessions SQLite (local)..."
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -c "
from cps_bot.core.session_store import clear_all_bot_state
from config import USER_NAMES_CACHE_PATH
from pathlib import Path
import json

counts = clear_all_bot_state()
print('Đã xóa:', counts)

cache = Path(USER_NAMES_CACHE_PATH)
if cache.is_file():
    cache.write_text('{}', encoding='utf-8')
    print('Đã reset user_names cache:', cache)
"
else
  python3 -c "
from cps_bot.core.session_store import clear_all_bot_state
counts = clear_all_bot_state()
print('Đã xóa:', counts)
"
fi

if command -v docker >/dev/null 2>&1 && docker compose ps -q lark telegram api 2>/dev/null | grep -q .; then
  echo "==> Restart bot containers (xóa RAM session)..."
  docker compose restart lark telegram api 2>/dev/null || docker compose --profile bots restart lark telegram api
  echo "==> Xóa sessions trong volume Docker (nếu có)..."
  docker compose exec -T lark python -c "
from cps_bot.core.session_store import clear_all_bot_state
print('Container:', clear_all_bot_state())
" 2>/dev/null || true
fi

echo "✅ Xong — mọi phiên chat cũ đã bị xóa. Hội thoại mới bắt đầu từ đầu."
