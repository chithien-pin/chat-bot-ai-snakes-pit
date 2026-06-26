#!/usr/bin/env bash
# Chạy toàn bộ unit test — bắt buộc pass trước khi deploy/update.
#
# Mặc định bỏ qua test cần gọi API (test_category_filter.py).
# Chạy cả integration: SKIP_INTEGRATION=0 ./scripts/run_tests.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ ! -x .venv/bin/python ]]; then
  echo "❌ Chưa có .venv — tạo virtualenv và cài requirements.txt trước."
  exit 1
fi

SKIP_INTEGRATION="${SKIP_INTEGRATION:-1}"
ran=0

echo "→ Chạy tests/ ..."
for test_file in tests/test_*.py; do
  base="$(basename "${test_file}")"
  if [[ "${SKIP_INTEGRATION}" == "1" && "${base}" == "test_category_filter.py" ]]; then
    echo "  ⊘ ${base} (integration — SKIP_INTEGRATION=0 để chạy)"
    continue
  fi
  echo "  • ${base}"
  .venv/bin/python "${test_file}"
  ran=$((ran + 1))
done
echo "✓ Tất cả test pass (${ran} files)"
