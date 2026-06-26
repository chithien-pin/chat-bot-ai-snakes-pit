#!/usr/bin/env python3
"""
Đồng bộ category attributes cho từng category_id trong menu_category_map.

- Throttle 3s/category (CATEGORY_ATTRIBUTES_FETCH_DELAY_SEC)
- Chạy ngay: python category_attributes_sync.py --run-now
- Daemon 0h: python category_attributes_sync.py --daemon
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta

from cps_bot.cps.cps_category_filter import build_category_attributes_map

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _seconds_until_next_midnight() -> float:
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max((tomorrow - now).total_seconds(), 1.0)


async def run_sync_once() -> dict:
    logger.info("Bắt đầu đồng bộ category attributes...")
    result = await build_category_attributes_map()
    logger.info("Hoàn tất: %d category có attributes", result.get("category_count", 0))
    return result


async def daemon_loop() -> None:
    await run_sync_once()
    while True:
        wait_sec = _seconds_until_next_midnight()
        next_run = datetime.now() + timedelta(seconds=wait_sec)
        logger.info(
            "Lần sync attributes tiếp theo lúc %s (%.0fs)",
            next_run.strftime("%Y-%m-%d %H:%M:%S"),
            wait_sec,
        )
        await asyncio.sleep(wait_sec)
        await run_sync_once()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Đồng bộ category attributes map")
    parser.add_argument("--run-now", action="store_true", help="Chạy sync một lần rồi thoát")
    parser.add_argument("--daemon", action="store_true", help="Chạy ngay + lặp 0:00 mỗi ngày")
    args = parser.parse_args(argv)

    if args.daemon:
        asyncio.run(daemon_loop())
        return 0
    if args.run_now or len(sys.argv) == 1:
        asyncio.run(run_sync_once())
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
