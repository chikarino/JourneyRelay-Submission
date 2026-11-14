"""Evaluate the real AI engines against the golden extraction cases.

Examples:
  .venv/bin/python scripts/eval_ai.py --engine local
  .venv/bin/python scripts/eval_ai.py --engine api
  .venv/bin/python scripts/eval_ai.py --engine local --limit 5
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402
from backend.analysis import booking_context, system_prompt  # noqa: E402
from backend.engines import OpenAICompatEngine, OllamaEngine  # noqa: E402
from backend.eval_cases import EVAL_CASES  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return ordered[index]


def eval_context(conn: sqlite3.Connection) -> dict | None:
    """The seeded CXDEMO1 booking, so evaluation matches the live path."""
    conn.row_factory = sqlite3.Row  # booking_row() calls dict(row) on query rows
    from backend.seed import load_demo_data
    load_demo_data(conn, "fresh")
    return booking_context(conn, "CXDEMO1")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("local", "api"), default="local")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--min-exact", type=float, default=0.85)
    parser.add_argument("--max-errors", type=int, default=1)
    args = parser.parse_args()

    cases = list(EVAL_CASES[: args.limit] if args.limit else EVAL_CASES)
    if not cases:
        print("No evaluation cases selected.")
        return 1

    engine = OllamaEngine() if args.engine == "local" else OpenAICompatEngine()
    context = eval_context(sqlite3.connect(":memory:"))
    prompt = system_prompt(context)

    exact = 0
    unseen = unseen_exact = 0
    true_positive = false_positive = false_negative = 0
    latencies: list[int] = []
    sources: Counter[str] = Counter()
    failures: list[str] = []
    errors: list[str] = []
    referral_ok = 0
    referral_failures: list[str] = []

    print(f"Evaluating {len(cases)} cases with engine={engine.name} ({engine.model_label()})")
    for case in cases:
        result = engine.analyse(case.text, context)
        predicted = {need.key for need in result.needs}
        sources[result.source] += 1
        latencies.append(result.latency_ms)
        if result.status == "error":
            errors.append(f"{case.id}:{result.error_code}")
            print(f"  [ERROR] {case.id} -> {result.error_code}")
            continue

        tp = len(predicted & case.expected)
        fp = len(predicted - case.expected)
        fn = len(case.expected - predicted)
        true_positive += tp
        false_positive += fp
        false_negative += fn

        # Referrals are scored on their own: they point the passenger to Customer Care, not to staff.
        if set(result.referrals) == case.referrals:
            referral_ok += 1
        else:
            referral_failures.append(case.id)
            print(f"  [REFERRAL] {case.id} expected={sorted(case.referrals) or '(none)'} "
                  f"got={sorted(result.referrals) or '(none)'}")

        ok = predicted == case.expected
        exact += ok
        if case.text not in prompt:
            unseen += 1
            unseen_exact += ok
        if not ok:
            failures.append(case.id)
            print(f"  [FAIL] {case.id}")
            print(f"         expected={sorted(case.expected) or '(none)'}")
            print(f"         got={sorted(predicted) or '(none)'} source={result.source}")

    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 1.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    exact_rate = exact / len(cases)

    print()
    print(f"Exact set match : {exact}/{len(cases)} ({exact_rate:.1%})")
    if unseen:
        print(f"  unseen only   : {unseen_exact}/{unseen} ({unseen_exact / unseen:.1%}), "
              f"excluding {len(cases) - unseen} prompt examples")
    print(f"Precision       : {precision:.1%}")
    print(f"Recall          : {recall:.1%}")
    print(f"F1              : {f1:.1%}")
    print(f"Referral match  : {referral_ok}/{len(cases)}")
    print(f"Latency p50/p95 : {percentile(latencies, 0.50)} / {percentile(latencies, 0.95)} ms")
    print(f"Sources         : {dict(sources)}")
    if failures:
        print(f"Failed cases    : {', '.join(failures)}")
    if referral_failures:
        print(f"Referral misses : {', '.join(referral_failures)}")
    if errors:
        print(f"Engine errors   : {', '.join(errors)}")

    if len(errors) > args.max_errors:
        print(f"ERROR: {len(errors)} engine errors (maximum allowed: {args.max_errors}).")
        return 1
    if exact_rate < args.min_exact:
        print(f"ERROR: exact match {exact_rate:.1%} is below {args.min_exact:.1%}.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
