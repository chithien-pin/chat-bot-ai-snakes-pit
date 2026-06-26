"""Unit tests — chạy: ./scripts/run_tests.sh hoặc PYTHONPATH=. python tests/test_*.py"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
