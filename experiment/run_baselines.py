"""Run fixed library baselines and save per-instance records."""

import argparse
import json
from pathlib import Path

from tnlab.baselines import run_baseline
from tnlab.instances import load_cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="develop_v2.json",
                        choices=("develop.json", "holdout.json", "develop_v2.json",
                                 "final_v2.json", "transfer_v2.json",
                                 "final_v3.json", "transfer_v3.json"))
    parser.add_argument("--repeats", type=int, default=32)
    parser.add_argument("--container", action="store_true",
                        help="run algorithms in the isolated Docker image")
    args = parser.parse_args()
    if args.container:
        import os
        os.environ["TN_EXECUTION_MODE"] = "container"
    records = []
    for case in load_cases(args.set):
        for method in ("greedy", "random-greedy", "simulated-annealing"):
            if args.container:
                from run_experiment import baseline_record
                records.append(baseline_record(case, method))
            else:
                records.append(run_baseline(case, method, args.repeats))
    target = Path(__file__).parent / "results" / f"baselines_{args.set}"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    for record in records:
        print(record["case"], record["method"], record["cost"],
              record["peak_elements"], f'{record["search_seconds"]:.4f}s')
    print("saved", target)


if __name__ == "__main__":
    main()
