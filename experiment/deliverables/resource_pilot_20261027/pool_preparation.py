"""Public fixture pool generation and tests; only callable inside Linux."""
from __future__ import annotations
import copy


def prepare(spec, call, digest):
    fixtures, cells, attempts = [], [], []
    for family, names in (("circuit", ("qubits", "depth")), ("lattice", ("rows", "cols"))):
        for cell in spec[family + "_cells"]:
            shape = [cell[k] for k in names]
            name = family + "_" + "x".join(map(str, shape))
            count_before = len(fixtures)
            for attempt in range(spec["attempt_limit_per_cell"]):
                response = call({"mode": "draw", "family": family, "shape": shape,
                                 "attempt": attempt, "previous": [f["case"] for f in fixtures]},
                                spec["equivalence_wall_seconds_per_draw"])
                attempts.append({"cell": name, "attempt": attempt, "response": response})
                if response["status"] != "ok":
                    raise RuntimeError("pool generation worker failed/timeout; stop")
                result = response["result"]
                if result["status"] == "unknown":
                    raise RuntimeError("equivalence unresolved; stop without replacement")
                if result["status"] == "accepted":
                    fixtures.append({"case_id": f"{name}_attempt_{attempt}", "family": family,
                        "shape": shape, "attempt": attempt, "case": result["case"],
                        "metadata": result["metadata"], "validation": result["validation"],
                        "structure_sha256": digest(result["case"]), "public_engineering_exposure": True})
                    if len(fixtures) - count_before == cell["wanted"]:
                        break
            count = len(fixtures) - count_before
            cells.append({"cell": name, "accepted": count, "wanted": cell["wanted"],
                          "attempts": attempt + 1, "complete": count == cell["wanted"]})
            if count != cell["wanted"]:
                raise RuntimeError("fixed pool cell incomplete; stop without solvers")
    assert len(fixtures) == 12
    return fixtures, cells, attempts


def validate_pool(fixtures, spec):
    from tnlab.structure_equivalence import compare_structures
    checks = []
    pairs = 0
    for i, fixture in enumerate(fixtures):
        case = fixture["case"]
        rename = {x: f"renamed_{j}" for j, x in enumerate(reversed(sorted(case["sizes"])))}
        variant = {"inputs": [[rename[x] for x in reversed(term)] for term in reversed(case["inputs"])],
                   "output": [rename[x] for x in case["output"]],
                   "sizes": {rename[x]: d for x, d in case["sizes"].items()}}
        assert compare_structures(case, variant, spec["equivalence_search_state_limit"])["outcome"] == "equivalent"
        for previous in fixtures[:i]:
            assert compare_structures(case, previous["case"], spec["equivalence_search_state_limit"])["outcome"] == "disjoint"
            pairs += 1
    checks.append({"check": "bounded_equivalence_and_relabeling", "status": "passed",
                   "detail": {"pairwise_disjoint": pairs, "relabel_reorder_equivalent": len(fixtures)}})
    base = {"inputs": [["a", "b"], ["b", "c"]], "output": ["a", "c"],
            "sizes": {"a": 2, "b": 3, "c": 4}}
    assert compare_structures(base, base, 0)["outcome"] == "unknown"
    changed = copy.deepcopy(base)
    changed["sizes"]["b"] = 5
    assert compare_structures(base, changed, 10000)["outcome"] == "disjoint"
    checks.append({"check": "equivalence_unknown_and_dimension_contract", "status": "passed"})
    return checks
