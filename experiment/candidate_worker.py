"""Untrusted child: import one candidate and return only its path."""

import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from time import perf_counter_ns

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tnlab.resource_limits import limit_address_space


def _invoke(find_path, case, clock=perf_counter_ns):
    """Time only the trusted call boundary, after candidate import completed."""
    started = clock()
    path = find_path(case["inputs"], case["output"], case["sizes"],
                     seed=case.get("candidate_seed", 0))
    return path, (clock() - started) / 1_000_000_000


def main():
    limit_address_space()
    candidate = Path(sys.argv[1]).resolve()
    case = json.load(sys.stdin)
    spec = importlib.util.spec_from_file_location("tn_candidate", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate cannot be imported")
    module = importlib.util.module_from_spec(spec)
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        spec.loader.exec_module(module)
        path, search_seconds = _invoke(module.find_path, case)
    print(json.dumps({"path": path, "stdout": output.getvalue()[-1000:],
                      "search_seconds": search_seconds}, allow_nan=False))


if __name__ == "__main__":
    main()
