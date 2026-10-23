"""Run one fixed baseline behind the shared timing boundary."""

import json
import sys
from pathlib import Path
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tnlab.resource_limits import limit_address_space


def main():
    limit_address_space()
    request = json.load(sys.stdin)
    from tnlab.baselines import find_path
    started = perf_counter_ns()
    path, _ = find_path(request["case"], request["method"])
    seconds = (perf_counter_ns() - started) / 1_000_000_000
    print(json.dumps({"path": path, "search_seconds": seconds}, allow_nan=False))


if __name__ == "__main__":
    main()
