"""Linux-only topology and resource pilot; all fixtures are public engineering.

The parent constructs a finite fixture pool before any solver is run. Workers
have separate generation/equivalence, candidate, and independent-scoring modes.
No production research admission flags, data files or provider code are touched.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROUTES = {"partition": "recursive_hypergraph_partition", "tree": "tree_search_annealing",
          "beam": "budgeted_beam_search"}


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def equivalence():
    sys.path.insert(0, "/")
    from tnlab.structure_equivalence import compare_structures
    return compare_structures


def worker(request):
    mode = request["mode"]
    started = time.perf_counter()
    if mode == "draw":
        generator = load("topology")
        family, shape, attempt = request["family"], request["shape"], request["attempt"]
        case, meta = getattr(generator, family)(*shape, attempt)
        result = {"case": case, "metadata": meta, "comparisons": []}
        if case is None:
            result["status"] = "structural_rejection"
        else:
            result["validation"] = generator.validate(case, family, shape, meta)
            compare = equivalence()
            result["status"] = "accepted"
            for previous in request["previous"]:
                relation = compare(case, previous, max_search_states=request["max_search_states"])
                result["comparisons"].append(relation)
                if relation["outcome"] != "disjoint":
                    result["status"] = ("duplicate" if relation["outcome"] == "equivalent"
                                        else "unknown_comparison")
                    break
    elif mode == "compare":
        result = equivalence()(request["left"], request["right"],
                               max_search_states=request["max_search_states"])
    elif mode == "candidate":
        candidate = load("heuristics")
        case = request["case"]
        inputs = [frozenset(x) for x in case["inputs"]]
        output, sizes = frozenset(case["output"]), dict(case["sizes"])
        before = copy.deepcopy((inputs, output, sizes))
        kwargs = {"seed": request["seed"]}
        diagnostics = {}
        if request["route"] == "beam":
            kwargs["diagnostics"] = diagnostics
        path = getattr(candidate, ROUTES[request["route"]])(inputs, output, sizes, **kwargs)
        assert before == (inputs, output, sizes), "candidate mutated input"
        result = {"path": path, "diagnostics": diagnostics}
    elif mode == "score":
        import cotengra as ctg
        oracle = load("prototype_validate")
        case, path = request["case"], request["path"]
        cost, peak = oracle.own_score(case, path)
        tree = ctg.ContractionTree.from_path(case["inputs"], case["output"], case["sizes"],
                                            path=path, check=True, autocomplete=False)
        trusted = (int(tree.contraction_cost()),
                   max(int(tree.max_size()),
                       max(math.prod(case["sizes"][x] for x in term) for term in case["inputs"])))
        assert (cost, peak) == trusted, "independent score mismatch"
        numerical = False
        if len(case["sizes"]) <= 18:
            oracle.numerical_check(case, path)
            numerical = True
        result = {"cost": cost, "peak_elements": peak, "numerical_oracle_checked": numerical}
    else:
        raise ValueError("unsupported worker mode")
    result.update(wall_seconds=time.perf_counter() - started,
                  process_cpu_seconds=time.process_time(),
                  peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return result


def main():
    import importlib.metadata
    spec = json.loads((HERE / "pilot_spec.json").read_bytes())
    source_names = ("topology.py", "pilot.py", "pilot_spec.json", "heuristics.py", "prototype_validate.py")
    source_hashes = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                     for name in source_names}
    comparison_module = Path("/tnlab/structure_equivalence.py")
    all_calls = []
    errors = []
    checks = []
    attempts = []
    accepted = []
    cells = []

    def call(request, timeout):
        start = time.perf_counter()
        environment = dict(os.environ)
        try:
            done = subprocess.run([sys.executable, "-I", "-B", str(HERE / "pilot.py"), "--worker"],
                                  input=canonical_bytes(request), capture_output=True,
                                  timeout=timeout, env=environment)
            if done.returncode:
                response = {"status": "process_error", "returncode": done.returncode,
                            "stderr": done.stderr.decode(errors="replace")[:2000]}
            else:
                response = {"status": "ok", "result": json.loads(done.stdout)}
        except subprocess.TimeoutExpired as exc:
            response = {"status": "timeout", "stderr": (exc.stderr or b"").decode(errors="replace")[:2000]}
        response["process_wall_seconds"] = time.perf_counter() - start
        all_calls.append({"mode": request["mode"], "status": response["status"],
                          "process_wall_seconds": response["process_wall_seconds"]})
        return response

    def check(name, action):
        try:
            checks.append({"name": name, "status": "passed", "detail": action()})
        except Exception as exc:
            checks.append({"name": name, "status": "failed"})
            errors.append({"check": name, "type": type(exc).__name__, "message": str(exc)[:2000]})

    def require(response):
        if response["status"] != "ok":
            raise AssertionError(response)
        return response["result"]

    for family, items in (("circuit", spec["circuit_cells"]), ("lattice", spec["lattice_cells"])):
        for cell in items:
            shape = [cell[k] for k in (("qubits", "depth") if family == "circuit" else ("rows", "cols"))]
            name = family + "_" + "x".join(map(str, shape))
            count_before = len(accepted)
            cell_attempts = []
            for attempt in range(spec["attempt_limit_per_cell"]):
                request = {"mode": "draw", "family": family, "shape": shape, "attempt": attempt,
                           "previous": [item["case"] for item in accepted],
                           "max_search_states": spec["equivalence_search_state_limit"]}
                response = call(request, spec["equivalence_wall_seconds_per_draw"])
                row = {"cell": name, "attempt": attempt, "response": response}
                attempts.append(row)
                cell_attempts.append(row)
                if response["status"] != "ok":
                    errors.append({"check": "generation/" + name,
                                   "message": "draw process failed or comparison timed out"})
                    break
                result = response["result"]
                if result["status"] == "unknown_comparison":
                    errors.append({"check": "generation/" + name,
                                   "message": "equivalence unresolved; stop without replacements"})
                    break
                if result["status"] == "accepted":
                    accepted.append({"id": name + "_attempt_" + str(attempt),
                                     "family": family, "shape": shape, "attempt": attempt,
                                     "case": result["case"], "metadata": result["metadata"],
                                     "validation": result["validation"],
                                     "structure_sha256": digest(result["case"]),
                                     "public_engineering_exposure": True})
                    if len(accepted) - count_before == cell["wanted"]:
                        break
            count = len(accepted) - count_before
            complete = count == cell["wanted"]
            cells.append({"cell": name, "accepted": count, "wanted": cell["wanted"],
                          "attempts": len(cell_attempts), "complete": complete})
            if not complete:
                errors.append({"check": "generation/" + name, "message": "incomplete engineering cell"})

    pool_digest_before_solver = digest(accepted)
    def finite_pool():
        assert all(c["complete"] for c in cells), "one or more engineering cells incomplete"
        return {"cells": len(cells), "cases": len(accepted), "complete": True}
    check("finite-structure-only-pool", finite_pool)

    def generation_repeat():
        for case in accepted:
            response = require(call({"mode": "draw", "family": case["family"],
                                     "shape": case["shape"], "attempt": case["attempt"],
                                     "previous": [], "max_search_states": 10000}, 5))
            assert response["case"] == case["case"]
            assert response["metadata"] == case["metadata"]
        return {"fresh_process_reproductions": len(accepted)}
    check("generator-byte-and-order-reproduction", generation_repeat)

    def equivalence_checks():
        covered = []
        for fixture in accepted:
            case = fixture["case"]
            rename = {x: "renamed_" + str(i) for i, x in enumerate(reversed(sorted(case["sizes"])))}
            variant = {"inputs": [[rename[x] for x in reversed(term)] for term in reversed(case["inputs"])],
                       "output": [rename[x] for x in case["output"]],
                       "sizes": {rename[x]: d for x, d in case["sizes"].items()}}
            relation = require(call({"mode": "compare", "left": case, "right": variant,
                                     "max_search_states": 10000}, 5))
            assert relation["outcome"] == "equivalent", relation
            covered.append(fixture["id"])
        base = {"inputs": [["a", "b"], ["b", "c"]], "output": ["a", "c"],
                "sizes": {"a": 2, "b": 3, "c": 4}}
        changed_dimension = copy.deepcopy(base)
        changed_dimension["sizes"]["b"] = 5
        changed_output = copy.deepcopy(base)
        changed_output["output"] = ["c", "a"]
        outcomes = []
        for changed in (changed_dimension, changed_output):
            relation = require(call({"mode": "compare", "left": base, "right": changed,
                                     "max_search_states": 10000}, 5))
            assert relation["outcome"] == "disjoint", relation
            outcomes.append(relation["outcome"])
        unknown = require(call({"mode": "compare", "left": base, "right": base,
                               "max_search_states": 0}, 5))
        assert unknown["outcome"] == "unknown", unknown
        return {"relabel_and_reorder_cases": len(covered), "dimension_and_output_order": outcomes,
                "zero_budget": unknown["outcome"],
                "policy_limitation": "output positions are colors; output-permuted equivalent-cost tasks can be called disjoint"}
    check("bounded-ordered-output-equivalence-contract", equivalence_checks)

    def topology_variation():
        records = []
        for cell in cells:
            rows = [x for x in accepted if x["id"].startswith(cell["cell"] + "_attempt_")]
            raw = {x["structure_sha256"] for x in rows}
            assert len(raw) == len(rows) and len(rows) >= 2
            metadata = {digest(x["metadata"]) for x in rows}
            assert len(metadata) == len(rows)
            records.append({"cell": cell["cell"], "distinct_graphs_under_pinned_policy": len(rows)})
        return records
    check("topology-changes-with-draw-not-tensor-values", topology_variation)

    slots = []
    for case in accepted:
        for route in ROUTES:
            def run_slot(case=case, route=route):
                repeats = []
                for repeat in range(spec["candidate_repeats"]):
                    execution = call({"mode": "candidate", "route": route, "case": case["case"],
                                      "seed": spec["candidate_algorithm_seed"]}, spec["solver_wall_seconds"])
                    item = {"execution": execution, "evaluation": None}
                    repeats.append(item)
                    if execution["status"] != "ok":
                        continue
                    item["evaluation"] = call({"mode": "score", "case": case["case"],
                                               "path": execution["result"]["path"]},
                                              spec["evaluator_wall_seconds"])
                row = {"case_id": case["id"], "route": route, "repeats": repeats}
                slots.append(row)
                if not all(item["execution"]["status"] == "ok" and item["evaluation"] is not None
                           and item["evaluation"]["status"] == "ok" for item in repeats):
                    row["status"] = "execution_or_evaluation_failure"
                    raise AssertionError("slot execution failure; full repeats retained")
                paths = [item["execution"]["result"]["path"] for item in repeats]
                if any(path != paths[0] for path in paths[1:]):
                    row["status"] = "nonrepeatable"
                    raise AssertionError("paths differ between fresh repeats")
                scores = [item["evaluation"]["result"] for item in repeats]
                if any(item["peak_elements"] > spec["peak_element_limit"] for item in scores):
                    row["status"] = "peak_cap_breach"
                    raise AssertionError("peak element cap breached")
                row["status"] = "ok"
                row["path_sha256"] = digest(paths[0])
                return {"cost": scores[0]["cost"], "peak_elements": scores[0]["peak_elements"]}
            check("resource/" + case["id"] + "/" + route, run_slot)

    assert digest(accepted) == pool_digest_before_solver, "pool changed after solver outcomes"
    route_summary = {}
    for route in ROUTES:
        rows = [row for row in slots if row["route"] == route]
        executions = [item["execution"]["result"] for row in rows for item in row["repeats"]
                      if item["execution"]["status"] == "ok"]
        evaluated = [item["evaluation"]["result"] for row in rows for item in row["repeats"]
                     if item["evaluation"] and item["evaluation"]["status"] == "ok"]
        route_summary[route] = {"slots": len(rows), "ok_slots": sum(row["status"] == "ok" for row in rows),
                                "candidate_executions": len(executions),
                                "max_candidate_wall_seconds": max((x["wall_seconds"] for x in executions), default=None),
                                "max_peak_rss_kib": max((x["peak_rss_kib"] for x in executions), default=None),
                                "max_peak_elements": max((x["peak_elements"] for x in evaluated), default=None),
                                "numeric_oracle_evaluations": sum(x["numerical_oracle_checked"] for x in evaluated),
                                "beam_used_initial_incumbent_executions": sum(
                                    bool(x["diagnostics"].get("used_initial_incumbent")) for x in executions)
                                    if route == "beam" else None}
    report = {"schema_version": 1, "purpose": spec["purpose"],
              "status": "passed" if not errors else "failed", "spec_sha256": digest(spec),
              "source_sha256": source_hashes, "python_version": sys.version,
              "dependency_versions": {x: importlib.metadata.version(x) for x in ("cotengra", "opt_einsum")},
              "equivalence_policy": "tensor-index-incidence-v1",
              "equivalence_source_sha256": hashlib.sha256(comparison_module.read_bytes()).hexdigest(),
              "equivalence_outputs": "position-preserving; does not certify uniqueness under output permutations",
              "fixture_pool_sha256_before_solver": pool_digest_before_solver,
              "case_count": len(accepted), "cells": cells, "attempts": attempts, "fixtures": accepted,
              "checks": checks, "checks_passed": sum(x["status"] == "passed" for x in checks),
              "checks_total": len(checks), "errors": errors, "slots": slots,
              "route_summary": route_summary, "subprocesses": all_calls,
              "model_requests": 0, "historical_corpus_accessed": False,
              "formal_research_data_accessed": False, "unseen_claim": False,
              "limitations": ["Small public engineering fixtures are exposed and cannot be relabeled as unseen tests.",
                              "No formal size-depth cells, study split or historical corpus was materialized.",
                              "Pinned equivalence colors output positions and omits tensor semantic roles.",
                              "This pilot cannot establish structural novelty or independent exposure eligibility.",
                              "One shared 1-CPU 2-GiB container bounds trusted sequential subprocesses, not arbitrary code.",
                              "No four-baseline comparison, provider call, tokenizer measurement or pricing is included."]}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    if "--worker" in sys.argv:
        print(json.dumps(worker(json.load(sys.stdin)), sort_keys=True))
    else:
        raise SystemExit(main())
