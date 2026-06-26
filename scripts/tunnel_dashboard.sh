#!/usr/bin/env bash
# Public dashboard qua internet (link ngrok) — không cần domain.
# Yêu cầu: dashboard đang chạy trên :3000 (Next.js) + :8080 (API).
#
# Cài ngrok (1 lần): https://ngrok.com/download
# Đăng ký free + lấy authtoken: https://dashboard.ngrok.com/get-started/your-authtoken
#
# Cấu hình authtoken (chọn 1 cách):
#   ngrok config add-authtoken <token>
#   hoặc thêm NGROK_AUTHTOKEN=<token> vào .env gốc
#
# Cấu hình mật khẩu dashboard trong .env và bot-dashboard/.env.local trước khi share link.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DASHBOARD_TUNNEL_PORT:-3000}"

# Load NGROK_AUTHTOKEN from root .env if present
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source <(grep -E '^(NGROK_AUTHTOKEN|DASHBOARD_PASSWORD)=' "$ROOT/.env" | sed 's/\r$//')
  set +a
fi

echo "→ Ngrok tunnel tới http://127.0.0.1:${PORT}"
if [[ -n "${DASHBOARD_PASSWORD:-}" ]]; then
  echo "→ Dashboard có mật khẩu — người mở link sẽ vào /login"
else
  echo "⚠ Chưa đặt DASHBOARD_PASSWORD trong .env — ai có link đều vào được"
fi
echo ""

if ! command -v ngrok >/dev/null 2>&1; then
  echo "Chưa có ngrok. Tải: https://ngrok.com/download"
  exit 1
fi

has_ngrok_config() {
  [[ -f "$HOME/.config/ngrok/ngrok.yml" ]] && grep -q 'authtoken' "$HOME/.config/ngrok/ngrok.yml" 2>/dev/null
}

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "$NGROK_AUTHTOKEN"
elif ! has_ngrok_config; then
  echo "❌ Ngrok chưa có authtoken (ERR_NGROK_4018)"
  echo ""
  echo "Làm 1 trong 2 cách:"
  echo "  1) Chạy một lần:"
  echo "     ngrok config add-authtoken <token>"
  echo ""
  echo "  2) Thêm vào .env rồi chạy lại script:"
  echo "     NGROK_AUTHTOKEN=<token>"
  echo ""
  echo "Lấy token free tại: https://dashboard.ngrok.com/get-started/your-authtoken"
  exit 1
fi

exec ngrok http "$PORT" --log=stdout
