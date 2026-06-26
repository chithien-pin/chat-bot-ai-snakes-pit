#!/bin/sh
set -e

cd /app
export PYTHONPATH=/app
export PYTHONUNBUFFERED=1

# Đảm bảo thư mục state + file log có thể ghi
mkdir -p /app/var
touch /app/var/metrics.log 2>/dev/null || true

case "${1:-dashboard}" in
  dashboard|api)
    exec python dashboard_api.py
    ;;
  telegram|bot)
    exec python bot.py
    ;;
  lark)
    exec python lark_bot.py
    ;;
  menu-sync)
    shift
    exec python menu_category_sync.py --daemon "$@"
    ;;
  category-sync)
    shift
    exec python category_attributes_sync.py --daemon "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
