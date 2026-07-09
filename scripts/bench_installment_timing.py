#!/usr/bin/env python3
"""
Benchmark latency trả góp — so sánh có/không INSTALLMENT_CHANNEL_PREVIEW.

Chạy trong container hoặc venv có httpx:
  PYTHONPATH=. python3 scripts/bench_installment_timing.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# Tắt preview qua env trước khi import module
os.environ.setdefault("INSTALLMENT_CHANNEL_PREVIEW", "1")

PRODUCT_ID = int(os.getenv("BENCH_PRODUCT_ID", "109159"))
QUESTION = os.getenv(
    "BENCH_INSTALLMENT_QUESTION",
    "Trả góp Galaxy A17 5G ưu đãi nhất",
)


async def _run_once(*, preview: bool) -> dict[str, float | str | int]:
    os.environ["INSTALLMENT_CHANNEL_PREVIEW"] = "1" if preview else "0"

    import importlib

    import config

    importlib.reload(config)

    import cps_bot.cps.cps_installment as inst_mod

    importlib.reload(inst_mod)

    from cps_bot.browse.installment_reply import build_installment_reply
    from cps_bot.cps.cps_api import fetch_product_from_map

    t0 = time.perf_counter()
    detail = await fetch_product_from_map("Galaxy A17 5G")
    fetch_product_ms = int((time.perf_counter() - t0) * 1000)
    if not detail:
        detail = {
            "product_id": PRODUCT_ID,
            "name": "Samsung Galaxy A17 5G 8GB 128GB",
            "price": "5.990.000₫",
            "price_value": 5990000,
        }

    t1 = time.perf_counter()
    ctx = await inst_mod.fetch_installment_context(
        detail,
        user_question=QUESTION,
    )
    fetch_installment_ms = int((time.perf_counter() - t1) * 1000)

    t2 = time.perf_counter()
    payload = {
        "primary_product": {
            "product_id": detail.get("product_id"),
            "name": detail.get("name"),
            "price": detail.get("price"),
            "url": detail.get("url") or "",
        },
        "installment": ctx,
    }
    answer = build_installment_reply(QUESTION, payload)
    template_ms = int((time.perf_counter() - t2) * 1000)

    card_terms = len((ctx.get("credit_card") or {}).get("zero_fee_by_term") or [])
    pay_providers = len((ctx.get("pay_later") or {}).get("details") or {})

    return {
        "preview": preview,
        "fetch_product_ms": fetch_product_ms,
        "fetch_installment_ms": fetch_installment_ms,
        "template_ms": template_ms,
        "total_ms": fetch_product_ms + fetch_installment_ms + template_ms,
        "card_term_rows": card_terms,
        "pay_later_providers": pay_providers,
        "answer_chars": len(answer),
        "answer_preview": answer[:500],
    }


async def main() -> None:
    print(f"Product: Galaxy A17 5G (id={PRODUCT_ID})")
    print(f"Question: {QUESTION!r}\n")

    results = []
    for preview in (False, True):
        label = "WITH channel preview (Mức 2)" if preview else "WITHOUT channel preview (CTTC only)"
        print(f"--- {label} ---")
        try:
            row = await _run_once(preview=preview)
            results.append(row)
            print(f"  fetch product:     {row['fetch_product_ms']} ms")
            print(f"  fetch installment: {row['fetch_installment_ms']} ms")
            print(f"  build template:    {row['template_ms']} ms")
            print(f"  TOTAL (no LLM):    {row['total_ms']} ms")
            print(f"  card term rows:    {row['card_term_rows']}")
            print(f"  pay later providers: {row['pay_later_providers']}")
            print(f"  answer length:     {row['answer_chars']} chars")
            print()
        except Exception as exc:
            print(f"  ERROR: {exc}\n", file=sys.stderr)
            return 1

    if len(results) == 2:
        delta = int(results[1]["fetch_installment_ms"]) - int(results[0]["fetch_installment_ms"])
        total_delta = int(results[1]["total_ms"]) - int(results[0]["total_ms"])
        print("--- So sánh ---")
        print(f"  Installment fetch thêm: +{delta} ms")
        print(f"  Tổng reply (no LLM) thêm: +{total_delta} ms")
        print()
        print("--- Mẫu reply Mức 2 (500 ký tự đầu) ---")
        print(results[1]["answer_preview"])
        print("...")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
