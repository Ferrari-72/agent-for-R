"""Linux-only pool preparation, isolated solver calls, and resource summary.

Run --prepare before --run. Neither phase imports provider or study admission code.
"""
from __future__ import annotations
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/")
SPEC = json.loads((HERE / "resource_spec.json").read_bytes())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    if sys.platform != "linux" or sys.argv[1:] not in (["--prepare"], ["--run"]):
        raise RuntimeError("Linux only; select exactly --prepare or --run")
    phase = sys.argv[1][2:]
    out = Path(os.environ["RESOURCE_PILOT_RESULTS"])
    source_hashes = json.loads((HERE / "source_hashes.json").read_bytes())
    for name, expected in source_hashes.items():
        assert hashlib.sha256((HERE / name).read_bytes()).hexdigest() == expected, name
    raw = out / (phase + "_workers")
    raw.mkdir(exist_ok=False)
    calls = []
    start_all = time.perf_counter()

    def call(request, timeout):
        number = len(calls)
        prefix = raw / f"{number:04d}_{request['mode']}"
        save(prefix.with_suffix(".request.json"), request)
        command = [sys.executable, "-s", "-B", str(HERE / "solver_worker.py")]
        start = time.perf_counter()
        try:
            process = subprocess.run(command, input=canonical(request), capture_output=True,
                                     timeout=timeout, env=dict(os.environ))
            stdout, stderr, returncode = process.stdout, process.stderr, process.returncode
            try:
                result = json.loads(stdout)
            except (ValueError, UnicodeDecodeError):
                result = None
            response = {"status": "ok" if returncode == 0 and isinstance(result, dict) else "process_error",
                        "result": result, "returncode": returncode}
            if response["status"] != "ok":
                response["error"] = {"type": "worker_failure", "returncode": returncode,
                                     "worker_error": (result or {}).get("worker_error") if isinstance(result, dict) else None}
        except subprocess.TimeoutExpired as exc:
            stdout, stderr = exc.stdout or b"", exc.stderr or b""
            response = {"status": "timeout", "result": None, "returncode": None,
                        "error": {"type": "wall_timeout", "budget_seconds": timeout}}
        response["process_wall_seconds"] = time.perf_counter() - start
        response["stderr"] = stderr.decode("utf-8", errors="replace")[-6000:]
        response["evidence_prefix"] = str(prefix.relative_to(out))
        prefix.with_suffix(".stdout.log").write_bytes(stdout)
        prefix.with_suffix(".stderr.log").write_bytes(stderr)
        save(prefix.with_suffix(".response.json"), response)
        calls.append({"number": number, "mode": request["mode"], "status": response["status"],
                      "process_wall_seconds": response["process_wall_seconds"],
                      "evidence_prefix": response["evidence_prefix"]})
        with (out / (phase + "_calls.jsonl")).open("a", encoding="utf-8") as log:
            log.write(json.dumps(calls[-1], sort_keys=True) + "\n")
        return response

    if phase == "prepare":
        helper = load("pool_preparation")
        fixtures, cells, attempts = helper.prepare(SPEC, call, digest)
        pool_tests = helper.validate_pool(fixtures, SPEC)
        # Recreate every accepted draw in a fresh process before solver exposure.
        for fixture in fixtures:
            response = call({"mode": "draw", "family": fixture["family"], "shape": fixture["shape"],
                             "attempt": fixture["attempt"], "previous": []},
                            SPEC["equivalence_wall_seconds_per_draw"])
            assert response["status"] == "ok", "generation repeat failed"
            assert response["result"]["case"] == fixture["case"]
            assert response["result"]["metadata"] == fixture["metadata"]
        pool_tests.append({"check": "fresh_process_generation_reproduction", "status": "passed",
                           "detail": {"reproductions": len(fixtures)}})
        score_test = call({"mode": "selftest"}, SPEC["score_wall_seconds"])
        assert score_test["status"] == "ok", "independent scorer selftest failed"
        pool_tests.extend(score_test["result"]["checks"])
        pool_hash = digest(fixtures)
        save(out / "fixture_pool.json", fixtures)
        save(out / "preparation.json", {"schema_version": 1, "status": "prepared", "fixtures": fixtures,
             "cells": cells, "attempts": attempts, "pool_sha256": pool_hash,
             "spec_sha256": digest(SPEC), "source_hashes": source_hashes,
             "pool_fixed_before_solver": True, "pool_tests": pool_tests, "calls": calls,
             "preparation_wall_seconds": time.perf_counter() - start_all})
        print(json.dumps({"status": "prepared", "cases": len(fixtures), "pool_sha256": pool_hash}))
        return 0

    prepared = json.loads((out / "preparation.json").read_bytes())
    fixtures = prepared["fixtures"]
    assert prepared["source_hashes"] == source_hashes
    assert prepared["spec_sha256"] == digest(SPEC)
    assert prepared["pool_sha256"] == digest(fixtures)
    assert json.loads((out / "fixture_pool.json").read_bytes()) == fixtures
    pool_hash = digest(fixtures)
    routes = SPEC["candidate_routes"]
    solvers = [*routes, *(item["solver_id"] for item in SPEC["baseline_solvers"])]
    rows = []
    for fixture in fixtures:
        for solver in solvers:
            for repeat in range(SPEC["repeats"]):
                is_candidate = solver in routes
                requested_seed = SPEC["candidate_seed"] if is_candidate else (None if solver == "omeco" else repeat)
                request = {"mode": "solve", "case": fixture["case"], "solver": solver, "repeat": repeat,
                           "case_id": fixture["case_id"]}
                execution = call(request, SPEC["solver_wall_seconds"])
                row = {"case_id": fixture["case_id"], "solver": solver,
                       "solver_kind": "candidate" if is_candidate else "baseline", "repeat": repeat,
                       "trial_seed_label": repeat, "requested_seed": requested_seed,
                       "status": "solver_" + execution["status"], "cost": None, "peak_elements": None,
                       "algorithm_wall_seconds": None, "process_wall_seconds": execution["process_wall_seconds"],
                       "max_rss_kib": None, "rss_entry_kib": None, "score_wall_seconds": None,
                       "score_process_wall_seconds": None, "score_max_rss_kib": None,
                       "score_checks": [], "path": None, "path_sha256": None,
                       "diagnostics": None, "randomness_control": None, "error": None,
                       "solver_evidence_prefix": execution["evidence_prefix"], "score_evidence_prefix": None}
                if execution["status"] != "ok":
                    row["error"] = {"stage": "solver", **execution.get("error", {}), "stderr": execution["stderr"]}
                    if isinstance(execution.get("result"), dict):
                        row["max_rss_kib"] = execution["result"].get("max_rss_kib")
                else:
                    result = execution["result"]
                    answer = result["answer"]
                    row.update(algorithm_wall_seconds=result["algorithm_wall_seconds"],
                               max_rss_kib=result["max_rss_kib"], rss_entry_kib=result["rss_entry_kib"],
                               diagnostics=answer.get("diagnostics"), randomness_control=answer.get("randomness_control"),
                               path=answer["path"], path_sha256=digest(answer["path"]))
                    scored = call({"mode": "score", "case": fixture["case"], "path": answer["path"],
                                   "case_id": fixture["case_id"], "solver": solver, "repeat": repeat},
                                  SPEC["score_wall_seconds"])
                    row["score_process_wall_seconds"] = scored["process_wall_seconds"]
                    row["score_evidence_prefix"] = scored["evidence_prefix"]
                    if scored["status"] != "ok":
                        row["status"] = "score_" + scored["status"]
                        row["error"] = {"stage": "score", **scored.get("error", {}), "stderr": scored["stderr"]}
                    else:
                        score = scored["result"]
                        row.update(status="success", cost=score["cost"], peak_elements=score["peak_elements"],
                                   score_wall_seconds=score["score_wall_seconds"],
                                   score_max_rss_kib=score["max_rss_kib"], score_checks=score["score_checks"])
                rows.append(row)
                with (out / "rows.jsonl").open("a", encoding="utf-8") as log:
                    log.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")

    candidate_repeats = []
    for fixture in fixtures:
        for solver in routes:
            pair = [r for r in rows if r["case_id"] == fixture["case_id"] and r["solver"] == solver]
            verified = len(pair) == 2 and all(r["status"] == "success" for r in pair)
            equal = verified and pair[0]["path"] == pair[1]["path"]
            candidate_repeats.append({"case_id": fixture["case_id"], "solver": solver,
                "status": "equal" if equal else ("different" if verified else "unverified_due_to_failure"),
                "path_sha256": pair[0]["path_sha256"] if equal else None})
    expected = {(f["case_id"], s, r) for f in fixtures for s in solvers for r in range(SPEC["repeats"])}
    identities = [(r["case_id"], r["solver"], r["repeat"]) for r in rows]
    assert len(set(identities)) == len(identities) and set(identities) == expected
    assert len(fixtures) == 12 and len(rows) == 168
    assert digest(fixtures) == pool_hash
    assert json.loads((out / "fixture_pool.json").read_bytes()) == fixtures
    for row in rows:
        if row["status"] == "success":
            assert all(type(row[k]) in (int, float) and math.isfinite(row[k]) for k in
                       ("cost", "peak_elements", "algorithm_wall_seconds", "process_wall_seconds", "max_rss_kib"))
            assert len(row["score_checks"]) == 2
    checks = prepared["pool_tests"] + [
        {"check": "fixed_pool_before_solvers", "status": "passed", "detail": {"cases": 12, "sha256": pool_hash}},
        {"check": "pool_unchanged_after_solvers", "status": "passed", "detail": {"sha256": digest(fixtures)}},
        {"check": "full_unique_row_denominator", "status": "passed", "detail": {"rows": len(rows), "expected": len(expected)}},
        {"check": "successful_paths_independent_scores", "status": "passed",
         "detail": {"validated": sum(r["status"] == "success" for r in rows), "denominator": len(rows)}},
        {"check": "candidate_repeat_paths", "status": "passed" if all(r["status"] == "equal" for r in candidate_repeats) else "failed",
         "detail": {"equal": sum(r["status"] == "equal" for r in candidate_repeats), "expected": len(candidate_repeats)}}]
    aggregates = []
    for solver in solvers:
        subset = [r for r in rows if r["solver"] == solver]
        good = [r for r in subset if r["status"] == "success"]
        maxima = {"max_" + field: max((r[field] for r in subset if r[field] is not None), default=None)
                  for field in ("algorithm_wall_seconds", "process_wall_seconds", "score_wall_seconds",
                                "score_process_wall_seconds", "rss_kib", "peak_elements") if field != "rss_kib"}
        aggregates.append({"solver": solver, "expected_rows": len(subset), "successes": len(good),
            "failures": len(subset) - len(good), "success_rate": len(good) / len(subset),
            "median_algorithm_wall_seconds": statistics.median(r["algorithm_wall_seconds"] for r in good) if good else None,
            "max_rss_kib": max((r["max_rss_kib"] for r in subset if r["max_rss_kib"] is not None), default=None),
            "candidate_repeat_equal": sum(r["solver"] == solver and r["status"] == "equal" for r in candidate_repeats) if solver in routes else None,
            **maxima})
    pure_paths = ("benchmark_solvers.py", "omeco_adapter.py", "scoring.py", "structure_equivalence.py")
    runtime_hashes = {"/tnlab/" + name: hashlib.sha256((Path("/tnlab") / name).read_bytes()).hexdigest()
                      for name in pure_paths}
    successes = sum(r["status"] == "success" for r in rows)
    report = {"schema_version": 1, "run_id": os.environ["RESOURCE_PILOT_RUN_ID"],
        "status": "passed" if successes == len(rows) and all(c["status"] == "passed" for c in checks) else "completed_with_failures",
        "scope": "public-engineering-resource-pretrial", "design": "DECOUPLED",
        "source_hashes": source_hashes, "runtime_source_hashes": runtime_hashes,
        "parameters": SPEC, "spec_sha256": digest(SPEC), "python_version": sys.version,
        "dependency_versions": {name: importlib.metadata.version(name) for name in ("cotengra", "opt_einsum", "omeco")},
        "limits": {"cpus": 1, "memory_bytes": 2147483648, "memory_plus_swap_bytes": 2147483648,
                   "pids": 64, "network": "none", "read_only": True, "uid": 65534,
                   "solver_wall_seconds": SPEC["solver_wall_seconds"], "score_wall_seconds": SPEC["score_wall_seconds"]},
        "pool": {"before_sha256": pool_hash, "after_sha256": digest(fixtures),
                 "cells": prepared["cells"], "attempts": prepared["attempts"]},
        "fixtures": fixtures, "rows": rows, "candidate_repeat_checks": candidate_repeats,
        "aggregates": aggregates, "checks": checks, "subprocesses": calls,
        "preparation_wall_seconds": prepared["preparation_wall_seconds"],
        "solver_phase_wall_seconds": time.perf_counter() - start_all,
        "model_requests": 0, "formal_research_data_accessed": False, "unseen_claim": False,
        "limitations": [
            "Fixed exposed public engineering pool; no formal study, held-out, final or transfer data, or unseen-performance claim.",
            "Pure equivalence policy tensor-index-incidence-v1 colors ordered output positions and omits tensor semantic roles; no novelty claim.",
            "One host and one sequential 1-CPU/2-GiB container; timings are descriptive, not portable resource guarantees.",
            "ru_maxrss is process high-water RSS, can inherit a pre-exec high-water floor, and includes runtime/imports; entry RSS is recorded.",
            "Algorithm wall measures teacher function or benchmark_solvers.solve wrapper; baseline adapter/import/validation overhead can remain inside it.",
            "OMECO receives seed=None; baseline repeat labels do not establish reproducibility or independent random draws.",
            "Teacher repeat equality is required only for these fixed routes/cases; hash seed remains pinned at 0.",
            "Timeout/error rows stay in all denominators; hard-killed workers have null internal wall/RSS when unavailable.",
            "Tensor cost and peak are symbolic element counts, not allocated contraction memory; no numerical large tensor contraction was run.",
            "Shared resource container bounds trusted sequential local workers; it is not a separate per-worker container sandbox."]}
    save(out / "summary.json", report)
    print(json.dumps({"status": report["status"], "cases": len(fixtures), "rows": len(rows),
                      "successes": successes, "pool_sha256": pool_hash, "aggregates": aggregates}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
