"""Independent path validation and scoring for OpenEvolve candidates."""

import ast
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

from openevolve.evaluation_result import EvaluationResult
from tnlab.baselines import find_path
from tnlab.instances import load_cases
from tnlab.scoring import score_path
from tnlab.execution import ResourceLimitError, run_candidate
from tnlab.experience import classify_failure

ROOT = Path(__file__).resolve().parent
CASE_TIMEOUT_SECONDS = 10
MAX_PEAK_ELEMENTS = 2**20
FAILURE_SCORE = -10.0
REPRODUCIBILITY_REPEATS = 3
PREFLIGHT_CASE = {"name": "preflight_chain", "inputs": [["a", "b"], ["b", "c"], ["c", "d"]],
                  "output": ["a", "d"], "sizes": {"a": 2, "b": 3, "c": 4, "d": 5}}


def evaluate_case(program_path, case):
    try:
        answer, wall_seconds = run_candidate(program_path, case, CASE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        message = "timeout"
        return {"case": case["name"], "error": message, "error_code": "timeout",
                "failure_class": classify_failure("timeout", message)}
    except ResourceLimitError:
        message = "memory limit exceeded"
        return {"case": case["name"], "error": message,
                "error_code": "resource_limit",
                "failure_class": classify_failure("resource_limit", message)}
    except Exception as exc:
        message = str(exc)[-1000:]
        return {"case": case["name"], "error": "candidate error",
                "error_code": "execution_error", "detail": message,
                "failure_class": classify_failure("execution_error", message)}
    try:
        seconds = float(answer["search_seconds"])
        if not math.isfinite(seconds) or seconds < 0 or seconds > CASE_TIMEOUT_SECONDS:
            raise ValueError("candidate search exceeded the time limit")
        result = score_path(case, answer["path"])
        if result.peak_elements > MAX_PEAK_ELEMENTS:
            raise ValueError("peak tensor exceeds the element limit")
        for repeat in range(1, REPRODUCIBILITY_REPEATS):
            repeated_answer, _ = run_candidate(program_path, case, CASE_TIMEOUT_SECONDS)
            if repeated_answer.get("path") != answer["path"]:
                raise ValueError(
                    f"candidate is nondeterministic on repeat {repeat + 1}; "
                    "the same instance and seed produced a different path"
                )
        return {"case": case["name"], "path": answer["path"],
                "cost": result.cost, "peak_elements": result.peak_elements,
                "search_seconds": seconds,
                "function_seconds_untrusted": answer.get("function_seconds"),
                "wall_seconds": wall_seconds,
                "reproducibility_repeats": REPRODUCIBILITY_REPEATS}
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        message = str(exc)
        return {"case": case["name"], "error": message,
                "error_code": "invalid_path",
                "failure_class": classify_failure("invalid_path", message)}


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
    stages = []
    started = perf_counter()
    try:
        code = Path(program_path).read_text(encoding="utf-8")
        syntax = ast.parse(code)
        if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name == "find_path" for node in syntax.body):
            raise ValueError("find_path function is missing")
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        record = {"case": "preflight", "error": str(exc),
                  "error_code": "syntax_or_interface",
                  "failure_class": classify_failure("syntax_or_interface", str(exc))}
        stages.append({"stage": "syntax_and_interface", "status": "failed",
                       "error_code": record["error_code"],
                       "seconds": perf_counter() - started})
        return EvaluationResult(
            metrics={"combined_score": FAILURE_SCORE, "valid_cases": 0.0,
                     "failure_count": 1.0},
            artifacts={"case_results.json": json.dumps([record]),
                       "pipeline_stages.json": json.dumps(stages)},
        )
    stages.append({"stage": "syntax_and_interface", "status": "passed",
                   "seconds": perf_counter() - started})
    started = perf_counter()
    preflight = evaluate_case(program_path, PREFLIGHT_CASE)
    stages.append({"stage": "small_network", "status": "failed" if "error" in preflight else "passed",
                   "error_code": preflight.get("error_code"),
                   "seconds": perf_counter() - started})
    if "error" in preflight:
        return EvaluationResult(
            metrics={"combined_score": FAILURE_SCORE, "valid_cases": 0.0,
                     "failure_count": 1.0},
            artifacts={"case_results.json": json.dumps([preflight]),
                       "pipeline_stages.json": json.dumps(stages)},
        )
    started = perf_counter()
    result = evaluate_set(program_path, os.environ.get("TN_DEVELOP_SET", "develop_v2.json"))
    stages.append({"stage": "development_set",
                   "status": "failed" if result.metrics["failure_count"] else "passed",
                   "error_code": "case_failure" if result.metrics["failure_count"] else None,
                   "seconds": perf_counter() - started})
    result.artifacts["pipeline_stages.json"] = json.dumps(stages)
    return result


if __name__ == "__main__":
    result = evaluate(sys.argv[1] if len(sys.argv) > 1 else ROOT / "initial_program.py")
    print(json.dumps({"metrics": result.metrics,
                      "cases": json.loads(result.artifacts["case_results.json"])},
                     ensure_ascii=False, indent=2))
