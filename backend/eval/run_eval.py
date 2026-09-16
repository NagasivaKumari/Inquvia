"""Evaluate per-task accuracy of the AI evidence checks against labeled cases.

Run from backend/:  python -m eval.run_eval   (or:  python eval\\run_eval.py)

Cases live in cases.jsonl (JSON per line). Each case calls the real production
function for its task and compares the returned JSON to `gold`:

    {"task": "verify", "claim": "...", "evidence": [...], "reasoning": "...",
     "gold": {"verified": true, "confidence_score": 0.9}, "tol": {"confidence_score": 0.15}}

The seed cases make the harness runnable now; replace them with your own
labeled ground truth to get a number you can trust. To raise accuracy, tune
config.MODEL_TASKS primaries and rerun.
"""
import asyncio
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

CASES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cases.jsonl")

DEFAULT_NUM_TOL = 0.2  # confidence scores may be off by this much and still count


def _norm(x):
    if isinstance(x, str):
        return x.strip().lower()
    return x


def _match(got, want, tol):
    if isinstance(want, bool):
        return got is want
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        if not isinstance(got, (int, float)) or isinstance(got, bool):
            return False
        return abs(float(got) - float(want)) <= tol
    if isinstance(want, str):
        return _norm(got) == _norm(want)
    if isinstance(want, list):
        if not isinstance(got, list):
            return False
        if not want:
            return True
        exact = {_norm(x) for x in got if isinstance(x, str)} & {_norm(x) for x in want}
        if exact:
            return True
        texts = [str(x) for x in got]
        hits = sum(1 for wt in want if any(_norm(wt) in _norm(t) for t in texts))
        return hits / len(want) >= 0.5
    if isinstance(want, dict):
        return isinstance(got, dict) and all(
            _match(got.get(k), v, tol) for k, v in want.items()
        )
    return got == want


async def _run_one(case):
    task = case["task"]
    gold = case["gold"]
    tol_for = lambda k: case.get("tol", {}).get(
        k, DEFAULT_NUM_TOL if isinstance(gold.get(k), (int, float)) else 0.0
    )

    if task == "verify":
        from app.libraries.engines import ClaimVerificationGate
        result = await ClaimVerificationGate.verify(case["claim"], case["evidence"], case["reasoning"])
    elif task == "contradictions":
        from app.libraries.engines import ContradictionEngine
        result = await ContradictionEngine.find_contradictions(case["evidence"])
    elif task == "gaps":
        from app.libraries.engines import GapsEngine
        result = await GapsEngine.identify_gaps(case["objectives"], case["evidence"])
    elif task == "claim":
        from app.libraries.analyzers import _claim_analyzer
        inv = {"question": case["question"], "inputs": case.get("inputs", [])}
        result = await _claim_analyzer(inv, case.get("evidence", []))
    else:
        return None, [("__error__", False, None, f"unknown task {task}")]

    checks = []
    for key, want in gold.items():
        got = result.get(key) if isinstance(result, dict) else None
        checks.append((key, _match(got, want, tol_for(key)), got, want))
    return task, checks


def main():
    if not os.path.exists(CASES):
        print(f"no cases file: {CASES}")
        return 1
    if not os.getenv("GEMINI_API_KEY"):
        print("WARNING: GEMINI_API_KEY not set — falls back to configured providers and may be slow/empty.")

    cases = [json.loads(line) for line in open(CASES, encoding="utf-8") if line.strip()]
    by_task = defaultdict(list)
    for c in cases:
        by_task[c["task"]].append(c)

    if not cases:
        print("no cases")
        return 1

    totals = defaultdict(lambda: [0, 0])  # task -> [passed, total]
    any_error = False
    for task, group in sorted(by_task.items()):
        ok = 0
        for i, case in enumerate(group, 1):
            t, checks = asyncio.run(_run_one(case))
            passed = all(m for _, m, _, _ in checks)
            if passed:
                ok += 1
            else:
                print(f"[{task}] case {i} FAILED: " + "; ".join(
                    f"{k}(got={got!r} want={want!r})" if not m else f"{k} ok"
                    for k, m, got, want in checks))
                if "__error__" in [k for k, *_ in checks]:
                    any_error = True
        n = len(group)
        totals[task][0] += ok
        totals[task][1] += n
        print(f"{task}: {ok}/{n} = {ok / n:.1%}")

    all_ok = sum(v[0] for v in totals.values())
    all_n = sum(v[1] for v in totals.values())
    print(f"\nTOTAL: {all_ok}/{all_n} = {all_ok / all_n:.1%}")
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())