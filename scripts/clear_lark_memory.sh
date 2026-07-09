#!/usr/bin/env bash
# Xóa toàn bộ context Lark in-memory + SQLite, rồi restart container lark.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="
from cps_bot.core.session_store import clear_all_bot_state
counts = clear_all_bot_state()
print('SQLite cleared:', counts)
"

echo "==> Xóa sessions SQLite..."
if [[ -x .venv/bin/python ]]; then
  PYTHONPATH=. .venv/bin/python -c "$PY"
else
  PYTHONPATH=. python3 -c "$PY"
fi

if command -v docker >/dev/null 2>&1; then
  if docker compose ps -q lark 2>/dev/null | grep -q .; then
    echo "==> Reset RAM trong container lark + restart..."
    docker compose exec -T lark python -c "
from cps_bot.core.session_store import clear_all_bot_state
from cps_bot.apps.lark import reset_lark_memory
print('DB:', clear_all_bot_state())
print('RAM:', reset_lark_memory())
" 2>/dev/null || true
    docker compose restart lark
    echo "✅ Lark memory đã xóa (SQLite + RAM)."
    exit 0
  fi
fi

echo "⚠️  Container lark không chạy — chỉ xóa SQLite local."
echo "   Restart lark thủ công: docker compose restart lark"
