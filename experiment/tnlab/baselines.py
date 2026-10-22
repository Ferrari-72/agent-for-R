"""Library path finders; all paths are scored by tnlab.scoring."""

from time import perf_counter

import opt_einsum as oe
import cotengra as ctg

from .scoring import score_path


def find_path(case, method="greedy", repeats=32):
    inputs = [set(tensor) for tensor in case["inputs"]]
    output = set(case["output"])
    if method == "greedy":
        optimizer = oe.paths.greedy
    elif method == "random-greedy":
        optimizer = oe.RandomGreedy(max_repeats=repeats, parallel=False)
    elif method == "simulated-annealing":
        start = perf_counter()
        initial = oe.paths.greedy(inputs, output, case["sizes"])
        tree = ctg.ContractionTree.from_path(
            case["inputs"], case["output"], case["sizes"],
            path=initial, check=True, autocomplete=False,
        )
        refined = tree.simulated_anneal(seed=0, tsteps=20, numiter=20,
                                        minimize="flops")
        return tuple(tuple(step) for step in refined.get_path()), perf_counter() - start
    else:
        raise ValueError(f"unknown baseline: {method}")
    start = perf_counter()
    path = optimizer(inputs, output, case["sizes"])
    elapsed = perf_counter() - start
    return tuple(tuple(step) for step in path), elapsed


def run_baseline(case, method="greedy", repeats=32):
    path, seconds = find_path(case, method, repeats)
    result = score_path(case, path)
    return {"case": case["name"], "method": method, "path": path,
            "cost": result.cost, "peak_elements": result.peak_elements,
            "search_seconds": seconds}
