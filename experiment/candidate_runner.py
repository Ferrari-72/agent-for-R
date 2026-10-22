"""Run one candidate and emit one machine-readable result."""

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from time import perf_counter


def main():
    candidate = Path(sys.argv[1]).resolve()
    case = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("tn_candidate", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate cannot be imported")
    module = importlib.util.module_from_spec(spec)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        spec.loader.exec_module(module)
        start = perf_counter()
        path = module.find_path(case["inputs"], case["output"], case["sizes"], seed=0)
        seconds = perf_counter() - start
    print(json.dumps({"path": path, "seconds": seconds,
                      "stdout": output.getvalue()[-1000:]}, allow_nan=False))


if __name__ == "__main__":
    main()
