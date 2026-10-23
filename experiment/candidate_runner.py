"""Trusted container parent: time a candidate in a separate Python process."""

import json
import sys
from pathlib import Path

from tnlab.resource_limits import limit_address_space
from tnlab.runner_protocol import run_worker


def main():
    limit_address_space()
    candidate = Path(sys.argv[1]).resolve()
    case = json.load(sys.stdin)
    worker = Path(__file__).with_name("candidate_worker.py")
    answer = run_worker(worker, case, (candidate,))
    print(json.dumps(answer, allow_nan=False))


if __name__ == "__main__":
    main()
