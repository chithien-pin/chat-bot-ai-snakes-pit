#!/usr/bin/env python3
"""
Đánh giá chất lượng câu trả lời chatbot — golden set + LLM-as-judge.

Chạy thủ công (cần API CPS + LLM):
  python -m tests.eval.run_eval
  python -m tests.eval.run_eval --limit 5 --scenario price
  python -m tests.eval.run_eval --skip-judge   # chỉ chạy pipeline, không gọi judge
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.jsonl"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"

JUDGE_PROMPT = """Bạn là giám khảo chất lượng chatbot tư vấn CellphoneS.

Câu hỏi khách: {question}
Ngữ cảnh (nếu có): {context}
Các ý BẮT BUỘC phải có trong câu trả lời đúng (expected_facts — mỗi ý có thể dùng từ đồng nghĩa):
{expected_facts}

Câu trả lời bot:
{answer}

Chấm theo rubric:
1. coverage: bot có đề cập đủ các expected_facts (cho phép đồng nghĩa)?
2. hallucination: bot có bịa số liệu/giá/tên SP không có trong câu hỏi hợp lý?
3. clarity: câu trả lời rõ ràng, phù hợp tư vấn bán hàng?

Trả JSON thuần (không markdown):
{{"score": 1-5, "coverage_ok": true/false, "hallucination_risk": "low|medium|high", "explanation": "..."}}
"""


@dataclass
class EvalCase:
    id: str
    scenario: str
    question: str
    context: str = ""
    expected_facts: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    case: EvalCase
    reply: str
    status: str
    score: float | None = None
    coverage_ok: bool | None = None
    hallucination_risk: str = ""
    explanation: str = ""
    latency_ms: int = 0
    error: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            cases.append(
                EvalCase(
                    id=str(raw.get("id") or ""),
                    scenario=str(raw.get("scenario") or "unknown"),
                    question=str(raw.get("question") or ""),
                    context=str(raw.get("context") or ""),
                    expected_facts=list(raw.get("expected_facts") or []),
                )
            )
    return cases


def _parse_judge_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None


def judge_answer(case: EvalCase, answer: str) -> dict[str, Any]:
    from cps_bot.llm.gemini_client import _generate_with_fallback

    facts = "\n".join(f"- {f}" for f in case.expected_facts) or "- (không có)"
    prompt = JUDGE_PROMPT.format(
        question=case.question,
        context=case.context or "(không có)",
        expected_facts=facts,
        answer=answer[:4000],
    )
    raw = _generate_with_fallback(prompt)
    parsed = _parse_judge_json(raw or "")
    if not parsed:
        return {
            "score": None,
            "coverage_ok": None,
            "hallucination_risk": "unknown",
            "explanation": f"Judge parse failed: {(raw or '')[:200]}",
        }
    return {
        "score": parsed.get("score"),
        "coverage_ok": parsed.get("coverage_ok"),
        "hallucination_risk": str(parsed.get("hallucination_risk") or "unknown"),
        "explanation": str(parsed.get("explanation") or ""),
    }


async def run_case(case: EvalCase, *, skip_judge: bool = False) -> EvalResult:
    from cps_bot.core.chat_pipeline import process_chat_message
    from cps_bot.core.conversation import append_turn, get_session
    from cps_bot.core.chat_pipeline import get_web_session_store, web_chat_id

    session_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"
    store = get_web_session_store()
    chat_id = web_chat_id(session_id)
    user_id = "eval-runner"

    if case.context:
        session = get_session(store, chat_id, user_id)
        product_name = ""
        keywords = ""
        for line in case.context.splitlines():
            if line.startswith("Sản phẩm đang thảo luận:"):
                product_name = line.split(":", 1)[1].strip()
            elif line.startswith("Từ khóa tìm gần nhất:"):
                keywords = line.split(":", 1)[1].strip()
        append_turn(
            session,
            user="(eval setup)",
            assistant="(eval setup)",
            keywords=keywords,
            product_name=product_name,
        )

    started = time.perf_counter()
    try:
        result = await process_chat_message(
            case.question,
            session_id=session_id,
            user_id=user_id,
            user_name="eval",
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        return EvalResult(
            case=case,
            reply="",
            status="error",
            error=str(exc)[:300],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    eval_result = EvalResult(
        case=case,
        reply=result.reply,
        status=result.status,
        latency_ms=latency_ms,
        metrics=dict(result.metrics or {}),
    )

    if skip_judge or not result.reply:
        return eval_result

    judge = judge_answer(case, result.reply)
    score = judge.get("score")
    eval_result.score = float(score) if score is not None else None
    eval_result.coverage_ok = judge.get("coverage_ok")
    eval_result.hallucination_risk = str(judge.get("hallucination_risk") or "")
    eval_result.explanation = str(judge.get("explanation") or "")
    return eval_result


def build_report(results: list[EvalResult]) -> dict[str, Any]:
    by_scenario: dict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_scenario[r.case.scenario].append(r)

    scenario_stats: dict[str, Any] = {}
    for scenario, items in by_scenario.items():
        scores = [i.score for i in items if i.score is not None]
        scenario_stats[scenario] = {
            "count": len(items),
            "avg_score": round(sum(scores) / len(scores), 2) if scores else None,
            "success_rate": round(
                sum(1 for i in items if i.status == "success") / len(items),
                2,
            ),
            "coverage_rate": round(
                sum(1 for i in items if i.coverage_ok is True)
                / max(sum(1 for i in items if i.coverage_ok is not None), 1),
                2,
            ),
            "avg_latency_ms": round(
                sum(i.latency_ms for i in items) / len(items),
            ),
            "price_mismatch_count": sum(
                1 for i in items if i.metrics.get("price_mismatch_detected")
            ),
        }

    all_scores = [r.score for r in results if r.score is not None]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "avg_score": round(sum(all_scores) / len(all_scores), 2) if all_scores else None,
        "scenario_stats": scenario_stats,
        "results": [
            {
                "id": r.case.id,
                "scenario": r.case.scenario,
                "question": r.case.question,
                "status": r.status,
                "score": r.score,
                "coverage_ok": r.coverage_ok,
                "hallucination_risk": r.hallucination_risk,
                "explanation": r.explanation,
                "latency_ms": r.latency_ms,
                "price_mismatch_detected": r.metrics.get("price_mismatch_detected"),
                "reply_preview": (r.reply or "")[:500],
                "error": r.error,
            }
            for r in results
        ],
    }


def write_report(report: dict[str, Any], *, prefix: str = "eval") -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = REPORTS_DIR / f"{prefix}_{ts}.json"
    csv_path = REPORTS_DIR / f"{prefix}_{ts}.csv"

    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "id",
                "scenario",
                "question",
                "status",
                "score",
                "coverage_ok",
                "hallucination_risk",
                "latency_ms",
                "price_mismatch_detected",
                "explanation",
            ],
        )
        writer.writeheader()
        for row in report.get("results") or []:
            writer.writerow(
                {
                    "id": row.get("id"),
                    "scenario": row.get("scenario"),
                    "question": row.get("question"),
                    "status": row.get("status"),
                    "score": row.get("score"),
                    "coverage_ok": row.get("coverage_ok"),
                    "hallucination_risk": row.get("hallucination_risk"),
                    "latency_ms": row.get("latency_ms"),
                    "price_mismatch_detected": row.get("price_mismatch_detected"),
                    "explanation": row.get("explanation"),
                }
            )

    return json_path, csv_path


async def main_async(args: argparse.Namespace) -> int:
    cases = load_golden_set()
    if args.scenario:
        cases = [c for c in cases if c.scenario == args.scenario]
    if args.limit:
        cases = cases[: args.limit]

    if not cases:
        print("Không có case nào để chạy.", file=sys.stderr)
        return 1

    print(f"Chạy eval: {len(cases)} case(s)...")
    results: list[EvalResult] = []
    for idx, case in enumerate(cases, start=1):
        print(f"[{idx}/{len(cases)}] {case.id} ({case.scenario}): {case.question[:60]}...")
        result = await run_case(case, skip_judge=args.skip_judge)
        results.append(result)
        score_txt = f" score={result.score}" if result.score is not None else ""
        print(f"  → status={result.status}{score_txt} latency={result.latency_ms}ms")

    report = build_report(results)
    json_path, csv_path = write_report(report)
    print(f"\nBáo cáo JSON: {json_path}")
    print(f"Báo cáo CSV:  {csv_path}")
    if report.get("avg_score") is not None:
        print(f"Điểm trung bình: {report['avg_score']}/5")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Eval chatbot với golden set")
    parser.add_argument("--limit", type=int, default=0, help="Giới hạn số case")
    parser.add_argument("--scenario", type=str, default="", help="Lọc theo scenario")
    parser.add_argument(
        "--skip-judge",
        action="store_true",
        help="Chỉ chạy pipeline, không gọi LLM judge",
    )
    args = parser.parse_args()
    if args.limit == 0:
        args.limit = 0
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
