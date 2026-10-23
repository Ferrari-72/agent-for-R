"""Recompute saved path costs and summary ratios without executing a candidate."""

import argparse
import hashlib
import json
import math
from math import prod
from pathlib import Path

from tnlab.scoring import score_path

ROOT = Path(__file__).resolve().parent


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _equal(actual, expected, label):
    if not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(f"{label}: {actual} differs from saved {expected}")


def _direct_cost_peak(case, path):
    """Count pair costs directly from live index sets, without cotengra."""
    sizes = case["sizes"]
    active = [set(tensor) for tensor in case["inputs"]]
    peak = max(prod(sizes[index] for index in tensor) for tensor in active)
    cost = 0
    for left, right in path:
        union = active[left] | active[right]
        cost += prod(sizes[index] for index in union)
        remaining = [tensor for i, tensor in enumerate(active) if i not in (left, right)]
        keep = set(case["output"]).union(*remaining)
        result = union & keep
        peak = max(peak, prod(sizes[index] for index in result))
        active = [*remaining, result]
    return cost, peak


def verify(run_dir):
    run_dir = Path(run_dir)
    development = json.loads((run_dir / "development_report.json").read_text(encoding="utf-8"))
    final = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    code = run_dir / "best_recheck.py"
    expected_code = development["environment"]["best_code_sha256"]
    if _sha(code) != expected_code or final["program_sha256"] != expected_code:
        raise ValueError("candidate code hash differs between saved artifacts")
    data_dir = run_dir / "frozen_data"
    if not (data_dir / "manifest_v2.json").exists():
        data_dir = ROOT / "data"
    manifest = json.loads((data_dir / "manifest_v2.json").read_text(encoding="utf-8"))
    if manifest != final["benchmark_manifest"]:
        raise ValueError("saved benchmark manifest differs from final report")
    checked = 0
    for set_name, group in final["results"].items():
        source = data_dir / set_name
        if _sha(source) != manifest[set_name]["sha256"]:
            raise ValueError(f"benchmark hash differs: {set_name}")
        cases = json.loads(source.read_text(encoding="utf-8"))
        if len(cases) != len(group["cases"]):
            raise ValueError(f"case count differs: {set_name}")
        trial_ratios = []
        trials = 0
        for case, row in zip(cases, group["cases"]):
            if case["name"] != row["case"]:
                raise ValueError(f"case order differs: {set_name}")
            for item in [*row["baselines"].values(), *row["candidate"].values()]:
                trials += 1
                if "cost" not in item:
                    continue
                score = score_path(case, item["path"])
                if score.cost != item["cost"] or score.peak_elements != item["peak_elements"]:
                    raise ValueError(f"saved path cost or peak differs: {case['name']}")
                direct_cost, direct_peak = _direct_cost_peak(case, item["path"])
                if (direct_cost, direct_peak) != (item["cost"], item["peak_elements"]):
                    raise ValueError(f"independent count differs: {case['name']}")
                if score.peak_elements > 2**20 or not 0 <= item["search_seconds"] <= 10:
                    raise ValueError(f"saved path exceeds resource contract: {case['name']}")
                checked += 1
            baseline_costs = [item["cost"] for item in row["baselines"].values()
                              if "cost" in item]
            best = min(baseline_costs)
            if best != row["best_baseline_cost"]:
                raise ValueError(f"best baseline differs: {case['name']}")
            greedy = row["baselines"]["greedy"]["cost"]
            for item in row["candidate"].values():
                if "cost" in item:
                    ratio = item["cost"] / best
                    _equal(ratio, item["ratio_to_best_baseline"], case["name"])
                    _equal(item["cost"] / greedy, item["ratio_to_greedy"], case["name"])
                    trial_ratios.append(ratio)
        summary = group["summary"]
        expected_trials = len(cases) * len(group["cases"][0]["candidate"])
        if summary["trials"] != expected_trials or summary["valid_trials"] != len(trial_ratios):
            raise ValueError(f"trial counts differ: {set_name}")
        _equal(1 - len(trial_ratios) / expected_trials, summary["failure_rate"], set_name)
        if len(trial_ratios) == expected_trials:
            _equal(math.exp(sum(map(math.log, trial_ratios)) / len(trial_ratios)),
                   summary["geometric_ratio_to_best_baseline"], set_name)
        elif summary["geometric_ratio_to_best_baseline"] is not None:
            raise ValueError(f"failed trials must not have a full geometric ratio: {set_name}")
    return {"verified_paths": checked, "candidate_sha256": expected_code,
            "data_source": str(data_dir),
            "scope": "saved paths, independent costs, peaks, ratios, and summaries; no candidate rerun"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = verify(args.run_dir)
    target = args.run_dir / "independent_recheck.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
