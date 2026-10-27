"""Synthetic-only independent checks. Run through run_validation.py in Linux.

No project data, model, provider, budget ledger or numerical tensor library is
used. Candidate workers are fresh isolated Python processes. cotengra is imported
only by the supervisor for an independent symbolic score.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import importlib.util
import itertools
import json
import math
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTES = {
    "partition": "recursive_hypergraph_partition",
    "tree": "tree_search_annealing",
    "beam": "budgeted_beam_search",
}


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixtures():
    definitions = [
        ("pair_open", [("a", "b"), ("b", "c")], ("a", "c")),
        ("closed_pair", [("a",), ("a",)], ()),
        ("scalars", [(), ()], ()),
        ("outer_product", [("a",), ("b",)], ("a", "b")),
        ("local_reduction", [("a", "s"), ("a", "b")], ("b",)),
        ("open_hyperedge", [("h", "a"), ("h", "b"), ("h", "c")],
         ("h", "a", "b", "c")),
        ("closed_hyperedge", [("h", "a"), ("h", "b"), ("h", "c")],
         ("a", "b", "c")),
        ("chain6", [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"),
                    ("e", "f"), ("f", "g")], ("a", "g")),
        ("cycle6", [("a", "b"), ("b", "c"), ("c", "d"), ("d", "e"),
                    ("e", "f"), ("f", "a")], ()),
        ("star6", [("x", "a", "b", "c", "d", "e"), ("a",), ("b",),
                   ("c",), ("d",), ("e",)], ("x",)),
        ("disconnected5", [("a", "b"), ("b", "c"), ("d", "e"), ("e",),
                           ("z",)], ("a", "c", "d", "z")),
        ("unit_dimensions", [("a", "b"), ("b", "c"), ("c",)], ("a",)),
        ("scalar_mixed", [(), ("a", "x"), ("x",), ()], ("a",)),
        ("asymmetric5", [("a", "b", "x"), ("a", "c"), ("b", "d"),
                         ("c", "d", "e"), ("e", "y")], ("x", "y")),
    ]
    cases = []
    for name, terms, output in definitions:
        labels = sorted({x for term in terms for x in term})
        sizes = {x: 2 + i % 2 for i, x in enumerate(labels)}
        if name == "pair_open":
            sizes = {"a": 2, "b": 3, "c": 4}
        if name == "unit_dimensions":
            sizes = {"a": 1, "b": 3, "c": 1}
        cases.append({"id": name, "inputs": [list(t) for t in terms],
                      "output": list(output), "sizes": sizes})
    return cases


def own_score(case, path):
    """Current-label simulation, independent of original-leaf/bitmask helpers."""
    if type(path) not in (list, tuple) or len(path) != len(case["inputs"]) - 1:
        raise ValueError("path must contain n-1 binary steps")
    raw = [set(term) for term in case["inputs"]]
    peak = max(math.prod(case["sizes"][x] for x in term) for term in raw)
    # Match the pinned evaluator's binary-tree objective: unary reductions are
    # represented as preprocessing and excluded from contraction_cost().
    counts = {x: sum(x in term for term in raw) for x in case["sizes"]}
    active = [{x for x in term if counts[x] > 1 or x in case["output"]}
              for term in raw]
    cost = 0
    for step in path:
        if (type(step) not in (list, tuple) or len(step) != 2
                or any(type(i) is not int for i in step)):
            raise ValueError("positions must be two integers")
        i, j = step
        if i == j or min(step) < 0 or max(step) >= len(active):
            raise ValueError("invalid current operand position")
        union = active[i] | active[j]
        outside = set(case["output"])
        for k, term in enumerate(active):
            if k not in (i, j):
                outside.update(term)
        result = union & outside
        cost += math.prod(case["sizes"][x] for x in union)
        peak = max(peak, math.prod(case["sizes"][x] for x in result))
        for k in sorted((i, j), reverse=True):
            active.pop(k)
        active.append(result)
    if active != [set(case["output"])]:
        raise ValueError("incomplete output")
    return cost, peak


def contract(operands, output, sizes):
    """Slow integer einsum oracle with no candidate or cotengra utilities."""
    labels = sorted({x for term, _ in operands for x in term})
    answer = {ix: 0 for ix in itertools.product(*(range(sizes[x]) for x in output))}
    for values in itertools.product(*(range(sizes[x]) for x in labels)):
        assignment = dict(zip(labels, values))
        value = math.prod(table[tuple(assignment[x] for x in term)]
                          for term, table in operands)
        answer[tuple(assignment[x] for x in output)] += value
    return answer


def numerical_check(case, path):
    sizes = {x: min(value, 2) for x, value in case["sizes"].items()}
    operands = []
    for i, term in enumerate(case["inputs"]):
        table = {ix: ((sum(ix) + i) % 5) - 2
                 for ix in itertools.product(*(range(sizes[x]) for x in term))}
        operands.append((list(term), table))
    expected = contract(operands, case["output"], sizes)
    active = operands.copy()
    for i, j in path:
        outside = set(case["output"])
        for k, (term, _) in enumerate(active):
            if k not in (i, j):
                outside.update(term)
        output = sorted((set(active[i][0]) | set(active[j][0])) & outside)
        result = (output, contract([active[i], active[j]], output, sizes))
        for k in sorted((i, j), reverse=True):
            active.pop(k)
        active.append(result)
    final = contract(active, case["output"], sizes)
    if final != expected:
        raise AssertionError("pairwise numerical result differs from direct integer einsum")


def all_paths(count):
    if count == 1:
        yield []
        return
    for i in range(count):
        for j in range(i + 1, count):
            for rest in all_paths(count - 1):
                yield [(i, j)] + rest


def worker(request):
    started = time.perf_counter()
    candidate = load(request.get("module", "heuristics"))
    inputs = [frozenset(x) for x in request["case"]["inputs"]]
    output = frozenset(request["case"]["output"])
    sizes = dict(request["case"]["sizes"])
    before = copy.deepcopy((inputs, output, sizes))
    rng_before = random.getstate()
    method = getattr(candidate, request.get("function", ROUTES[request["route"]]))
    path = method(inputs, output, sizes, seed=request["seed"], **request.get("kwargs", {}))
    if before != (inputs, output, sizes):
        raise AssertionError("candidate mutated input")
    if random.getstate() != rng_before:
        raise AssertionError("candidate mutated global random state")
    return {"path": path, "candidate_wall_seconds": time.perf_counter() - started}


def main():
    import cotengra as ctg

    candidate = load("heuristics")
    exporter = load("export_candidates")
    exported = exporter.export((HERE / "heuristics.py").read_text(encoding="utf-8"))
    checks = []
    observations = []
    errors = []
    executions = 0

    def check(name, action):
        try:
            detail = action()
            checks.append({"name": name, "status": "passed", "detail": detail})
        except Exception as exc:
            errors.append({"check": name, "type": type(exc).__name__, "error": str(exc)[:2000]})
            checks.append({"name": name, "status": "failed"})

    def independent(case, path):
        cost, peak = own_score(case, path)
        tree = ctg.ContractionTree.from_path(case["inputs"], case["output"], case["sizes"],
                                            path=path, check=True, autocomplete=False)
        trusted_cost = int(tree.contraction_cost())
        trusted_peak = max(int(tree.max_size()),
                           max(math.prod(case["sizes"][x] for x in term)
                               for term in case["inputs"]))
        if (cost, peak) != (trusted_cost, trusted_peak):
            raise AssertionError(f"oracle {(cost, peak)} != cotengra {(trusted_cost, trusted_peak)}")
        active = list(range(len(case["inputs"])))
        for i, j in path:
            joined = (active[i], active[j])
            for k in sorted((i, j), reverse=True):
                active.pop(k)
            active.append(joined)
        internal = candidate.Problem(case["inputs"], case["output"], case["sizes"]).tree_stats(active[0])
        if internal != (cost, peak):
            raise AssertionError(f"candidate internal {internal} != independent {(cost, peak)}")
        return {"cost": cost, "peak_elements": peak}

    def run(case, route, seed, repeat, **options):
        nonlocal executions
        executions += 1
        request = {"case": case, "route": route, "seed": seed, **options}
        environment = dict(__import__("os").environ)
        environment["PYTHONHASHSEED"] = str(17 + repeat * 100)
        started = time.perf_counter()
        done = subprocess.run([sys.executable, "-I", "-B", str(HERE / "validate.py"), "--worker"],
                              input=json.dumps(request).encode(), capture_output=True,
                              timeout=10, env=environment)
        if done.returncode:
            raise RuntimeError(f"worker exit {done.returncode}: {done.stderr.decode(errors='replace')[:1500]}")
        result = json.loads(done.stdout)
        result["process_wall_seconds"] = time.perf_counter() - started
        result["score"] = independent(case, result["path"])
        return result

    cases = fixtures()
    for case in cases:
        for route in ROUTES:
            for seed in (0, 1, 7):
                def action(case=case, route=route, seed=seed):
                    first = run(case, route, seed, 0)
                    second = run(case, route, seed, 1)
                    if first["path"] != second["path"]:
                        raise AssertionError("fresh-process paths differ")
                    numerical_check(case, first["path"])
                    observations.append({"case": case["id"], "route": route, "seed": seed,
                                         "path": first["path"], "repeats_identical": True,
                                         "score": first["score"],
                                         "candidate_wall_seconds": [first["candidate_wall_seconds"],
                                                                    second["candidate_wall_seconds"]]})
                    return first["score"]
                check(f"fresh/{case['id']}/{route}/{seed}", action)

    def hand_calculated():
        expected = {"pair_open": (24, 12), "closed_pair": (2, 2),
                    "scalars": (1, 1), "outer_product": (6, 6),
                    "local_reduction": (6, 6)}
        for case in cases:
            if case["id"] in expected:
                assert own_score(case, [(0, 1)]) == expected[case["id"]]
        return expected
    check("hand-calculated-five-cases", hand_calculated)

    def exact_oracle():
        comparisons = 0
        enumerated = 0
        for case in cases:
            if len(case["inputs"]) > 5:
                continue
            frontier = []
            for path in all_paths(len(case["inputs"])):
                frontier.append(own_score(case, path))
                enumerated += 1
            for limit in (None, 1, 12, 64):
                rank = lambda stats: (max(0, stats[1] - limit) if limit is not None else 0,
                                      stats[0], stats[1])
                path = candidate.recursive_hypergraph_partition(
                    case["inputs"], case["output"], case["sizes"], cutoff=6, peak_limit=limit)
                assert rank(own_score(case, path)) == min(map(rank, frontier))
                comparisons += 1
        return {"comparisons": comparisons, "enumerated_paths": enumerated}
    check("tiny-partition-optimum-versus-full-path-enumeration", exact_oracle)

    def metamorphic():
        tested = 0
        for case in cases:
            labels = sorted(case["sizes"])
            rename = {x: f"long_label_{len(labels)-i:03d}" for i, x in enumerate(labels)}
            renamed = {"inputs": [[rename[x] for x in term] for term in case["inputs"]],
                       "output": [rename[x] for x in case["output"]],
                       "sizes": {rename[x]: value for x, value in case["sizes"].items()}}
            reordered = {**case, "inputs": list(reversed(case["inputs"]))}
            for route, name in ROUTES.items():
                method = getattr(candidate, name)
                for variant in (renamed, reordered):
                    path = method(variant["inputs"], variant["output"], variant["sizes"], seed=7)
                    independent(variant, path)
                    numerical_check(variant, path)
                    tested += 1
        return {"variants": tested, "policy": "validity and score agreement; no invariance claim for input ordering"}
    check("renamed-labels-and-reversed-inputs", metamorphic)

    def budgets():
        checked = 0
        for case in cases:
            baseline = candidate.tree_search_annealing(case["inputs"], case["output"], case["sizes"], steps=0)
            initial = own_score(case, baseline)
            for limit in (None, 1, 12):
                rank = lambda stats: (max(0, stats[1] - limit) if limit is not None else 0,
                                      stats[0], stats[1])
                for budget in (0, 1, 7, 256):
                    diagnostics = {}
                    path = candidate.budgeted_beam_search(
                        case["inputs"], case["output"], case["sizes"],
                        max_expansions=budget, peak_limit=limit, diagnostics=diagnostics)
                    score = own_score(case, path)
                    assert diagnostics["expansions"] <= budget
                    if budget >= len(case["inputs"]) - 1:
                        assert diagnostics["complete_states"] > 0
                    assert diagnostics["used_initial_incumbent"] == (rank(score) == rank(initial))
                    assert rank(score) <= rank(initial)
                    assert score == (diagnostics["cost"], diagnostics["peak_elements"])
                    independent(case, path)
                    checked += 1
                path = candidate.tree_search_annealing(
                    case["inputs"], case["output"], case["sizes"], peak_limit=limit)
                assert rank(own_score(case, path)) <= rank(initial)
        return {"beam_budget_limit_combinations": checked,
                "infeasible_limits": "valid path retained; external evaluator must reject cap breaches"}
    check("budget-exhaustion-and-best-incumbent", budgets)

    def export_contract():
        import ast
        verified = []
        for route, source in exported.items():
            nodes = ast.parse(source).body
            entries = [n for n in nodes if isinstance(n, ast.FunctionDef) and n.name == "find_path"]
            assert len(entries) == 1
            assert [arg.arg for arg in entries[0].args.args] == ["inputs", "output", "sizes", "seed"]
            namespace = {"__name__": f"export_{route}"}
            exec(compile(source, f"export_{route}.py", "exec"), namespace)
            for case in cases:
                path = namespace["find_path"](case["inputs"], case["output"], case["sizes"])
                reference = getattr(candidate, ROUTES[route])(case["inputs"], case["output"], case["sizes"])
                assert path == reference
                independent(case, path)
            verified.append(route)
        return {"standalone_routes": verified, "production_patch_guard_exercised": False}
    check("standalone-candidate-export-contract", export_contract)

    def reject_invalid():
        invalid = [({"width": 0}, "beam"), ({"max_expansions": -1}, "beam"),
                   ({"steps": -1}, "tree"), ({"temperature": float("nan")}, "tree"),
                   ({"cutoff": 7}, "partition"), ({"seed": True}, "partition"),
                   ({"peak_limit": 0}, "partition")]
        case = cases[0]
        for kwargs, route in invalid:
            try:
                getattr(candidate, ROUTES[route])(case["inputs"], case["output"], case["sizes"], **kwargs)
            except ValueError:
                continue
            raise AssertionError(f"accepted invalid parameters: {kwargs}")
        for bad in ([], [(0, 0)], [(True, 1)], [(0, 2)]):
            try:
                own_score(case, bad)
            except ValueError:
                continue
            raise AssertionError("oracle accepted malformed path")
        for terms, output, sizes in [([["a", "a"], ["a"]], [], {"a": 2}),
                                      ([["a"], ["a"]], [], {"a": True}),
                                      ([["a"]], [], {"a": 2})]:
            try:
                candidate.Problem(terms, output, sizes)
            except ValueError:
                continue
            raise AssertionError("accepted unsupported problem")
        return {"invalid_parameter_cases": len(invalid), "invalid_paths": 4,
                "invalid_problems": 3}
    check("invalid-input-and-parameter-rejection", reject_invalid)

    def engineering_sizes():
        records = []
        for n in (32, 128, 256):
            terms = [[f"edge_{i}", f"edge_{i+1}"] for i in range(n)]
            case = {"inputs": terms, "output": ["edge_0", f"edge_{n}"],
                    "sizes": {f"edge_{i}": 2 for i in range(n + 1)}}
            for route in ROUTES:
                record = run(case, route, 0, 0)
                records.append({"n": n, "route": route, **record})
        return records
    check("larger-public-chain-engineering-only", engineering_sizes)

    report = {
        "schema_version": 1,
        "scope": "handwritten-synthetic-prototype-engineering-validation",
        "status": "passed" if not errors else "failed",
        "platform": sys.platform,
        "python_version": sys.version,
        "dependencies": {name: importlib.metadata.version(name) for name in ("cotengra", "opt_einsum")},
        "case_count": len(cases), "algorithm_seeds": [0, 1, 7],
        "fresh_process_executions": executions,
        "fresh_process_repeat_pairs": len(observations),
        "checks_passed": sum(row["status"] == "passed" for row in checks),
        "checks_total": len(checks), "checks": checks, "errors": errors,
        "observations": observations,
        "source_sha256": {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                          for name in ("heuristics.py", "validate.py", "export_candidates.py")},
        "candidate_export_sha256": {name: hashlib.sha256(source.encode()).hexdigest()
                                    for name, source in exported.items()},
        "model_requests": 0, "research_data_accessed": False,
        "limitations": ["Engineering fixtures are not study datasets or performance benchmarks.",
                        "Repeat checks do not prove determinism for every input or environment.",
                        "Larger chains do not establish quantum-circuit resource feasibility.",
                        "Beam may use its balanced fallback before any complete searched state.",
                        "Peak limits rank candidates; infeasibility is reported by the external evaluator.",
                        "No production prompt/patch validation or tokenizer feasibility is claimed."],
    }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    if "--worker" in sys.argv:
        try:
            print(json.dumps(worker(json.load(sys.stdin)), sort_keys=True))
        except Exception as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            raise SystemExit(1)
    else:
        raise SystemExit(main())
