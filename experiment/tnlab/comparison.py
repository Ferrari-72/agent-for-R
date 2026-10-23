"""Re-evaluate a frozen program and fixed baselines under one resource policy."""

import math
from pathlib import Path

from .execution import run_baseline, run_candidate
from .scoring import score_path

METHODS = ("greedy", "random-greedy", "simulated-annealing")
SEEDS = (0, 1, 2)
TIME_LIMIT = 10
PEAK_LIMIT = 2**20


def _checked(case, answer):
    seconds = float(answer["search_seconds"])
    if not math.isfinite(seconds) or not 0 <= seconds <= TIME_LIMIT:
        raise ValueError("search time limit exceeded")
    score = score_path(case, answer["path"])
    if score.peak_elements > PEAK_LIMIT:
        raise ValueError("peak element limit exceeded")
    return {"path": answer["path"], "cost": score.cost,
            "peak_elements": score.peak_elements, "search_seconds": seconds,
            "function_seconds_untrusted": answer.get("function_seconds")}


def compare_case(program: Path, case: dict):
    baselines = {}
    for method in METHODS:
        try:
            answer, wall = run_baseline(case, method, TIME_LIMIT)
            baselines[method] = {**_checked(case, answer), "wall_seconds": wall}
        except Exception as exc:
            baselines[method] = {"error": str(exc)[-500:]}
    valid = [item["cost"] for item in baselines.values() if "cost" in item]
    if not valid or "cost" not in baselines["greedy"]:
        raise RuntimeError(f"benchmark has no feasible reference: {case['name']}")
    best_cost = min(valid)
    candidate = {}
    for seed in SEEDS:
        try:
            answer, wall = run_candidate(program, {**case, "candidate_seed": seed}, TIME_LIMIT)
            candidate[str(seed)] = {**_checked(case, answer), "wall_seconds": wall}
            candidate[str(seed)]["ratio_to_best_baseline"] = (
                candidate[str(seed)]["cost"] / best_cost)
            candidate[str(seed)]["ratio_to_greedy"] = (
                candidate[str(seed)]["cost"] / baselines["greedy"]["cost"])
        except Exception as exc:
            candidate[str(seed)] = {"error": str(exc)[-500:]}
    return {"case": case["name"], "baselines": baselines,
            "best_baseline_cost": best_cost, "candidate": candidate}


def summarize(records):
    results = [item for case in records for item in case["candidate"].values()]
    valid = [item for item in results if "cost" in item]
    ratios = [item["ratio_to_best_baseline"] for item in valid]
    return {"trials": len(results), "valid_trials": len(valid),
            "failure_rate": 1 - len(valid) / len(results),
            "geometric_ratio_to_best_baseline": (
                math.exp(sum(map(math.log, ratios)) / len(ratios))
                if len(valid) == len(results) else None)}
