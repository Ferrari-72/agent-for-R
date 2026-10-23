"""Trusted container parent for a fixed baseline algorithm."""

import json
import sys
from pathlib import Path

from tnlab.resource_limits import limit_address_space
from tnlab.runner_protocol import run_worker


def main():
    limit_address_space()
    request = json.load(sys.stdin)
    worker = Path(__file__).with_name("baseline_worker.py")
    print(json.dumps(run_worker(worker, request), allow_nan=False))


if __name__ == "__main__":
    main()
