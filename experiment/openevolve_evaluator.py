"""Independent path validation and scoring for OpenEvolve candidates."""

import json
import math
import subprocess
import sys
from pathlib import Path

from openevolve.evaluation_result import EvaluationResult
from tnlab.baselines import find_path
from tnlab.instances import load_cases
from tnlab.scoring import score_path

ROOT = Path(__file__).resolve().parent
CASE_TIMEOUT_SECONDS = 10
MAX_PEAK_ELEMENTS = 2**20
FAILURE_SCORE = -10.0


def evaluate_case(program_path, case):
    try:
        process = subprocess.run(
            [sys.executable, str(ROOT / "candidate_runner.py"), str(program_path)],
            input=json.dumps(case), text=True, capture_output=True,
            timeout=CASE_TIMEOUT_SECONDS, cwd=ROOT, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"case": case["name"], "error": "timeout"}
    if process.returncode:
        return {"case": case["name"], "error": "candidate error",
                "detail": process.stderr[-1000:]}
    try:
        answer = json.loads(process.stdout)
        result = score_path(case, answer["path"])
        if result.peak_elements > MAX_PEAK_ELEMENTS:
            raise ValueError("peak tensor exceeds the element limit")
        return {"case": case["name"], "path": answer["path"],
                "cost": result.cost, "peak_elements": result.peak_elements,
                "search_seconds": answer["seconds"]}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return {"case": case["name"], "error": str(exc)}


def evaluate_set(program_path, set_name="develop.json"):
    records = []
    log_ratios = []
    for case in load_cases(set_name):
        record = evaluate_case(program_path, case)
        greedy_path, _ = find_path(case)
        greedy_cost = score_path(case, greedy_path).cost
        record["greedy_cost"] = greedy_cost
        if "cost" in record:
            log_ratios.append(math.log(record["cost"] / greedy_cost))
        records.append(record)
    failures = len(records) - len(log_ratios)
    combined_score = (FAILURE_SCORE if failures
                      else -sum(log_ratios) / len(records))
    return EvaluationResult(
        metrics={"combined_score": combined_score, "valid_cases": float(len(log_ratios)),
                 "failure_count": float(failures)},
        artifacts={"case_results.json": json.dumps(records, ensure_ascii=False, indent=2)},
    )


def evaluate(program_path):
    """OpenEvolve only receives development-set feedback."""
    return evaluate_set(program_path, "develop.json")


if __name__ == "__main__":
    result = evaluate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "initial_program.py")
    print(json.dumps({"metrics": result.metrics,
                      "cases": json.loads(result.artifacts["case_results.json"])},
                     ensure_ascii=False, indent=2))
