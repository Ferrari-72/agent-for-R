"""Fresh Linux worker for topology, path search, and independent scoring."""
from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/")
SPEC = json.loads((HERE / "resource_spec.json").read_bytes())


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def execute(request):
    mode = request["mode"]
    rss_entry = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()
    if mode == "draw":
        generator = load("topology")
        family, shape = request["family"], request["shape"]
        case, metadata = getattr(generator, family)(*shape, request["attempt"])
        result = {"status": "rejected", "metadata": metadata}
        if case is not None:
            validation = generator.validate(case, family, shape, metadata)
            from tnlab.structure_equivalence import compare_structures
            comparisons = []
            status = "accepted"
            for previous in request["previous"]:
                comparison = compare_structures(case, previous, SPEC["equivalence_search_state_limit"])
                comparisons.append(comparison)
                if comparison["outcome"] != "disjoint":
                    status = comparison["outcome"]
                    break
            result = {"status": status, "case": case, "metadata": metadata,
                      "validation": validation, "comparisons": comparisons}
    elif mode == "solve":
        case, solver = request["case"], request["solver"]
        if solver in SPEC["candidate_routes"]:
            route = SPEC["candidate_routes"][solver]
            candidate = load("heuristics")
            inputs = [frozenset(term) for term in case["inputs"]]
            output, sizes = frozenset(case["output"]), dict(case["sizes"])
            before = copy.deepcopy((inputs, output, sizes))
            import random
            global_random_before = random.getstate()
            kwargs = {"seed": SPEC["candidate_seed"], **route["parameters"]}
            diagnostics = {}
            if solver == "teacher.beam":
                kwargs["diagnostics"] = diagnostics
            algorithm_start = time.perf_counter()
            path = getattr(candidate, route["function"])(inputs, output, sizes, **kwargs)
            algorithm_seconds = time.perf_counter() - algorithm_start
            assert before == (inputs, output, sizes), "candidate mutated input"
            assert random.getstate() == global_random_before, "candidate mutated global random state"
            answer = {"path": path, "diagnostics": diagnostics,
                      "randomness_control": "caller seed 0, two fresh-process path checks"}
        else:
            from tnlab.benchmark_solvers import solve
            config = next(x for x in SPEC["baseline_solvers"] if x["solver_id"] == solver)
            seed = None if solver == "omeco" else request["repeat"]
            algorithm_start = time.perf_counter()
            answer = solve(case, config, seed)
            algorithm_seconds = time.perf_counter() - algorithm_start
        result = {"answer": answer, "algorithm_wall_seconds": algorithm_seconds}
    elif mode == "score":
        # Each returned path is checked by the existing cotengra scorer AND own_score.
        from tnlab.scoring import score_path, validate_path
        case, path = request["case"], request["path"]
        path = validate_path(case, path)
        score_start = time.perf_counter()
        trusted = score_path(case, path)
        own = load("prototype_validate").own_score(case, path)
        assert own == (trusted.cost, trusted.peak_elements), "independent score mismatch"
        result = {"cost": trusted.cost, "peak_elements": trusted.peak_elements,
                  "score_wall_seconds": time.perf_counter() - score_start,
                  "score_checks": ["tnlab.scoring.score_path (cotengra)", "prototype_validate.own_score"]}
    elif mode == "selftest":
        from tnlab.scoring import score_path
        oracle = load("prototype_validate")
        expected = {"pair_open": (24, 12), "closed_pair": (2, 2), "scalars": (1, 1),
                    "outer_product": (6, 6), "local_reduction": (6, 6)}
        checked = 0
        for case in oracle.fixtures():
            if case["id"] not in expected:
                continue
            path = [(0, 1)]
            trusted = score_path(case, path)
            assert oracle.own_score(case, path) == expected[case["id"]]
            assert (trusted.cost, trusted.peak_elements) == expected[case["id"]]
            oracle.numerical_check(case, path)
            checked += 1
        base = oracle.fixtures()[0]
        for bad in ([], [(0, 0)], [(True, 1)], [(0, 2)]):
            for scorer in (oracle.own_score, score_path):
                try:
                    scorer(base, bad)
                except ValueError:
                    continue
                raise AssertionError("scorer accepted invalid path")
        from tnlab.omeco_adapter import _configuration
        config = _configuration(next(s["parameters"] for s in SPEC["baseline_solvers"] if s["solver_id"] == "omeco"))
        assert config["settings"]["ntrials"] == 10 and config["settings"]["niters"] == 50
        assert len(config["settings"]["betas"]) == 300
        result = {"checks": [
            {"check": "hand_calculated_independent_scores_and_numerical_oracle", "status": "passed", "detail": {"cases": checked}},
            {"check": "invalid_path_rejection", "status": "passed", "detail": {"paths": 4, "scorers": 2}},
            {"check": "omeco_explicit_adapter_defaults", "status": "passed", "detail": config}
        ]}
    else:
        raise ValueError("unsupported worker mode")
    result.update(worker_wall_seconds=time.perf_counter() - started,
                  max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  rss_entry_kib=rss_entry,
                  process_cpu_seconds=time.process_time())
    return result


if __name__ == "__main__":
    try:
        result = execute(json.load(sys.stdin))
        print(json.dumps(result, sort_keys=True, allow_nan=False))
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({"worker_error": {"type": type(exc).__name__, "message": str(exc),
                                          "code": getattr(exc, "code", None)},
                          "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}, sort_keys=True))
        raise SystemExit(1)
