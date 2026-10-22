"""Run fixed library baselines and save per-instance records."""

import argparse
import json
from pathlib import Path

from tnlab.baselines import run_baseline
from tnlab.instances import load_cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", default="develop.json", choices=("develop.json", "holdout.json"))
    parser.add_argument("--repeats", type=int, default=32)
    args = parser.parse_args()
    records = [run_baseline(case, method, args.repeats)
               for case in load_cases(args.set)
               for method in ("greedy", "random-greedy", "simulated-annealing")]
    target = Path(__file__).parent / "results" / f"baselines_{args.set}"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    for record in records:
        print(record["case"], record["method"], record["cost"],
              record["peak_elements"], f'{record["search_seconds"]:.4f}s')
    print("saved", target)


if __name__ == "__main__":
    main()
