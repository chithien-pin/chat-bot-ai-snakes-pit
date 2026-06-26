#!/usr/bin/env bash
# Restart bot + dashboard chạy local (không Docker).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -x .venv/bin/python ]]; then
  echo "❌ Chưa có .venv"
  exit 1
fi

stop_pid() {
  local pattern="$1"
  local pids
  pids=$(pgrep -f "$pattern" || true)
  if [[ -n "$pids" ]]; then
    echo "→ Dừng: $pattern ($pids)"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

stop_pid "python lark_bot.py"
stop_pid "python dashboard_api.py"

mkdir -p "$(dirname "$ROOT/metrics.log")"
touch "$ROOT/metrics.log"

nohup .venv/bin/python dashboard_api.py >>"$ROOT/var/dashboard_api.log" 2>&1 &
echo "→ dashboard_api PID $!"

nohup .venv/bin/python lark_bot.py >>"$ROOT/var/lark_bot.log" 2>&1 &
echo "→ lark_bot PID $!"

sleep 1
pgrep -af "python (lark_bot|dashboard_api)" || true
echo "✓ Đã restart — gửi lại câu hỏi trên Lark rồi mở Pipeline tin mới nhất."
