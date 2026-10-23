"""Measure an algorithm worker from a separate trusted process."""

import json
import os
import subprocess
import sys
from time import perf_counter


def run_worker(worker, request, extra_args=(), timeout=10):
    """Run a worker with one trusted wall-clock boundary."""
    started = perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, "-I", str(worker), *map(str, extra_args)],
            input=json.dumps(request).encode("utf-8"), capture_output=True,
            timeout=timeout,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                 "MKL_NUM_THREADS": "1"},
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"TN_ERROR:TIMEOUT candidate search exceeded {timeout:g} seconds"
        ) from exc
    seconds = perf_counter() - started
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode:
        if result.returncode in (137, -9) or "MemoryError" in stderr:
            raise RuntimeError("TN_ERROR:RESOURCE_LIMIT memory limit exceeded")
        raise RuntimeError(stderr[-1000:] or f"algorithm exited {result.returncode}")
    answer = json.loads(stdout)
    if not isinstance(answer, dict):
        raise ValueError("worker response must be an object")
    # The child can modify its own timer. Keep that value for diagnostics only.
    function_seconds = answer.pop("search_seconds", None)
    return {**answer, "function_seconds": function_seconds,
            "search_seconds": seconds}
