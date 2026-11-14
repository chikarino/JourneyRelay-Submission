"""Evaluate the guided chat's first-turn recommendations against the golden cases.

The chat offers options for the passenger to pick (REDESIGN.md §5.6), so this
asks a different question from eval_ai.py: after the passenger's first message,
does every need they actually stated appear among the recommendations?

Examples:
  .venv/bin/python scripts/eval_chat.py --engine api
  .venv/bin/python scripts/eval_chat.py --engine local --limit 5
  .venv/bin/python scripts/eval_chat.py --engine api --family-transfer
  .venv/bin/python scripts/eval_chat.py --engine api --removed-needs
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402
from backend.analysis import AnalysisError  # noqa: E402
from backend.conversation import ChatIn, _repeats_question, run_conversation  # noqa: E402
from backend.engines import OpenAICompatEngine, OllamaEngine  # noqa: E402
from backend.eval_cases import EVAL_CASES  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "scripts"))
from eval_ai import eval_context, percentile  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

# Cases where the passenger says they need nothing: any recommendation is noise.
DECLINED = {"no_need", "all_negated", "diagnosis_only_no_functional_need"}
# Written updates are the wrong offer for difficulty seeing.
VISION = {"low_vision_guide", "cannot_find_gate"}


def evaluate_family_transfer(engine, context: dict) -> int:
    opening = {"role": "user", "content":
               "我個仔三歲，人多會突然跑開。我陪住佢，佢平時肯坐車仔。"
               "香港轉機嗰陣，可唔可以有人帶我哋去下一個閘口？"}
    first = run_conversation(engine, ChatIn(messages=[opening]), context)
    first_ids = {f"{item['code']}:{item['scope']}" for item in first["recommendations"]}
    first_ok = first_ids == {"GUIDE:transfer"} and not first["question"]
    print(f"  [{'PASS' if first_ok else 'FAIL'}] initial guidance: {sorted(first_ids)}")
    old_opening = {**opening, "content": opening["content"].replace(
        "人多會突然跑開。", "人多會突然跑開，一緊張又會企定唔肯行。")}
    old_reply = run_conversation(engine, ChatIn(messages=[old_opening]), context)
    old_ids = {f"{item['code']}:{item['scope']}" for item in old_reply["recommendations"]}
    old_ok = old_ids == {"GUIDE:transfer"} and not old_reply["question"]
    print(f"  [{'PASS' if old_ok else 'FAIL'}] initial guidance with occasional stops: {sorted(old_ids)}")
    follow_up = {"role": "assistant", "content": " ".join(filter(None, [first["message"], first["question"]]))}
    cases = (
        ("guided walk will not work", "但係佢一見到陌生人帶路就會抗拒，企定唔肯行，我驚佢行唔到去閘口。",
         {"WHEELCHAIR:transfer"}, {"GUIDE"}),
        ("wheelchair declined", "唔使輪椅。只要我拖住佢行，有人喺前面指路就得。", {"GUIDE:transfer"}, {"WHEELCHAIR"}),
    )
    failed = not (first_ok and old_ok)
    for label, text, expected, excluded in cases:
        body = ChatIn(messages=[opening, follow_up, {"role": "user", "content": text}])
        reply = run_conversation(engine, body, context)
        ids = {f"{item['code']}:{item['scope']}" for item in reply["recommendations"]}
        codes = {item["code"] for item in reply["recommendations"]}
        passed = expected <= ids and not (excluded & codes)
        if label == "guided walk will not work":
            passed = passed and ids == expected and not reply["question"] and not reply["quick_replies"]
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}: {sorted(ids)}")
        failed |= not passed

    update = {"role": "user", "content":
              "輪椅照舊。職員幫我個仔之前，麻煩先同我講會點做，等我同意先接觸佢。"}
    reply = run_conversation(engine, ChatIn(messages=[update]),
                              {**context, "active_needs": ["WHEELCHAIR:transfer"]})
    ids = {f"{item['code']}:{item['scope']}" for item in reply["recommendations"]}
    passed = ids == {"ASK_BEFORE_TOUCH:transfer"} and not reply["question"]
    print(f"  [{'PASS' if passed else 'FAIL'}] keep wheelchair and add contact preference: {sorted(ids)}")
    failed |= not passed

    gate_request = {"role": "user", "content":
                    "我個仔三歲，喺人多嘅地方會突然跑開。我想知去登機閘口嗰段路，有冇人可以幫手？"}
    initial = run_conversation(engine, ChatIn(messages=[gate_request]), context)
    codes = {item["code"] for item in initial["recommendations"]}
    passed = "GUIDE" in codes and "WHEELCHAIR" not in codes
    print(f"  [{'PASS' if passed else 'FAIL'}] help reaching the gate: {sorted(codes)}")
    failed |= not passed

    previous_turn = "明白你想有人喺去閘口途中幫手。\n\n小朋友可唔可以自己行完整段路，你喺旁邊拖住佢？"
    history = [gate_request, {"role": "assistant", "content": previous_turn},
               {"role": "user", "content": "他對陌生人可能會強烈抗拒"}]
    corrected = run_conversation(engine, ChatIn(messages=history), context)
    passed = (bool(corrected["question"])
              and not _repeats_question(corrected["question"], previous_turn)
              and all(item["code"] != "WHEELCHAIR" for item in corrected["recommendations"]))
    print(f"  [{'PASS' if passed else 'FAIL'}] response to unfamiliar staff: "
          f"{corrected['question'] or '(no question)'}")
    failed |= not passed
    return int(failed)


def language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    return "en" if letters and sum(c.isascii() for c in letters) / len(letters) > 0.8 else "zh"


def evaluate_removed_needs(engine, context: dict) -> int:
    """Replay last-trip removals with renewed requests, unrelated replies and refusals."""
    dismissed = ["QUIET_WAIT:full", "SEAT_ADJACENT:full"]
    cases = (
        ("zh seating", "座位安排", "您希望怎樣安排座位？", "與照顧者坐在一起",
         {"SEAT_ADJACENT:full"}),
        ("en seating", "Seating arrangements", "What seating help would you like?",
         "Sit with my caregiver", {"SEAT_ADJACENT:full"}),
        ("zh quiet waiting", "等候時人太多", "甚麼安排會有幫助？", "我想要安靜候機",
         {"QUIET_WAIT:full"}),
        ("en quiet waiting", "Waiting is crowded", "What would help?",
         "I need a quiet waiting area", {"QUIET_WAIT:full"}),
        ("unrelated reply", "I need a quiet waiting area and seats together with my caregiver.",
         "You could request a quiet waiting area and adjacent seats.",
         "I also need written updates instead of announcements.", {"TEXT_INFO:full"}),
        ("explicit refusal", "我想要安靜候機，同照顧者坐一齊。", "您可以申請這兩項協助。",
         "唔需要安靜候機，亦唔使同照顧者坐一齊，今次唔使任何協助。", set()),
    )
    failed = 0
    for label, opening, question, latest, expected in cases:
        body = ChatIn(messages=[{"role": "user", "content": opening},
                                {"role": "assistant", "content": question},
                                {"role": "user", "content": latest}],
                      selected=[], dismissed=dismissed, lang=language(latest))
        try:
            reply = run_conversation(engine, body, context)
            keys = {f"{n['code']}:{n['scope']}" for n in reply["recommendations"]}
            passed = keys == expected and not reply["referrals"]
            print(f"  [{'PASS' if passed else 'FAIL'}] {label}: expected={sorted(expected)} got={sorted(keys)}", flush=True)
            failed += not passed
        except AnalysisError as exc:
            print(f"  [ERROR] {label} -> {exc.code}", flush=True)
            failed += 1
    return int(bool(failed))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=("local", "api"), default="api")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--family-transfer", action="store_true", help="Check family transfer guidance and follow-up questions")
    parser.add_argument("--removed-needs", action="store_true", help="Check renewed requests after removing last-trip needs")
    args = parser.parse_args()

    cases = list(EVAL_CASES[: args.limit] if args.limit else EVAL_CASES)
    engine = OllamaEngine() if args.engine == "local" else OpenAICompatEngine()
    context = eval_context(sqlite3.connect(":memory:"))
    if args.removed_needs:
        return evaluate_removed_needs(engine, context)
    if args.family_transfer:
        context["party"] = "+ 2 名兒童"
        try:
            return evaluate_family_transfer(engine, context)
        except AnalysisError as exc:
            print(f"  [ERROR] family transfer -> {exc.code}")
            return 1

    stated = covered = covered_exact = 0
    need_total = need_found = 0
    referral_ok = 0
    noisy: list[str] = []
    vision_text: list[str] = []
    misses: list[str] = []
    errors: list[str] = []
    latencies: list[int] = []

    print(f"Evaluating first-turn recommendations on {len(cases)} cases with engine={engine.name} "
          f"({engine.model_label()})")
    for case in cases:
        body = ChatIn(messages=[{"role": "user", "content": case.text}], lang=language(case.text))
        started = time.monotonic()
        try:
            reply = run_conversation(engine, body, context)
        except AnalysisError as exc:
            errors.append(f"{case.id}:{exc.code}")
            print(f"  [ERROR] {case.id} -> {exc.code}")
            continue
        latencies.append(int((time.monotonic() - started) * 1000))

        keys = {f"{r['code']}:{r['scope']}" for r in reply["recommendations"]}
        codes = {r["code"] for r in reply["recommendations"]}
        expected_codes = {key.split(":")[0] for key in case.expected}
        referrals = {r["code"] for r in reply["referrals"]}
        referral_ok += referrals == case.referrals

        if case.expected:
            stated += 1
            need_total += len(expected_codes)
            need_found += len(expected_codes & codes)
            covered += expected_codes <= codes
            covered_exact += case.expected <= keys
            if not expected_codes <= codes:
                misses.append(case.id)
                print(f"  [MISS] {case.id} expected={sorted(case.expected)} got={sorted(keys) or '(none)'}")
        if case.id in DECLINED and keys:
            noisy.append(case.id)
            print(f"  [NOISE] {case.id} got={sorted(keys)}")
        if case.id in VISION and "TEXT_INFO" in codes:
            vision_text.append(case.id)
            print(f"  [VISION] {case.id} recommended written updates")
        if referrals != case.referrals:
            print(f"  [REFERRAL] {case.id} expected={sorted(case.referrals) or '(none)'} "
                  f"got={sorted(referrals) or '(none)'}")

    print()
    print(f"Stated needs all recommended : {covered}/{stated} cases "
          f"({covered_exact}/{stated} with the exact scope)")
    print(f"Stated needs recommended     : {need_found}/{need_total}")
    print(f"Referrals exactly right      : {referral_ok}/{len(cases)}")
    print(f"Recommended after 'no need'  : {len(noisy)}/{len(DECLINED & {c.id for c in cases})}")
    print(f"Written updates for vision   : {len(vision_text)}/{len(VISION & {c.id for c in cases})}")
    print(f"Latency per turn p50/p95     : {percentile(latencies, 0.50)} / {percentile(latencies, 0.95)} ms")
    if misses:
        print(f"Missed cases                 : {', '.join(misses)}")
    if errors:
        print(f"Engine errors                : {', '.join(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
