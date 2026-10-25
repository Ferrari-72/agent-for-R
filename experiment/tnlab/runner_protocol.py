"""Measure an algorithm worker from a separate trusted process."""

import json
import os
import signal
import subprocess
import sys
from time import perf_counter


def _stop_process_tree(process):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, timeout=5, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_worker(worker, request, extra_args=(), timeout=10):
    """Run a worker with one trusted wall-clock boundary."""
    started = perf_counter()
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {
        "start_new_session": True}
    process = subprocess.Popen(
        [sys.executable, "-I", str(worker), *map(str, extra_args)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
             "MKL_NUM_THREADS": "1"},
        **options,
    )
    try:
        stdout, stderr = process.communicate(json.dumps(request).encode("utf-8"),
                                             timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _stop_process_tree(process)
        raise RuntimeError(
            f"TN_ERROR:TIMEOUT candidate search exceeded {timeout:g} seconds"
        ) from exc
    seconds = perf_counter() - started
    stdout = stdout.decode("utf-8", errors="replace")
    stderr = stderr.decode("utf-8", errors="replace")
    if process.returncode:
        if process.returncode in (137, -9) or "MemoryError" in stderr:
            raise RuntimeError("TN_ERROR:RESOURCE_LIMIT memory limit exceeded")
        raise RuntimeError(stderr[-1000:] or f"algorithm exited {process.returncode}")
    answer = json.loads(stdout)
    if not isinstance(answer, dict):
        raise ValueError("worker response must be an object")
    function_seconds = answer.pop("search_seconds", None)
    return {**answer, "function_seconds": function_seconds,
            "search_seconds": seconds}
