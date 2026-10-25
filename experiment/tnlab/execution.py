"""Run untrusted path finders without mounting benchmark data or credentials."""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "tnlab-runner:py313-v1"


class ResourceLimitError(RuntimeError):
    """The restricted container stopped an algorithm at its memory ceiling."""


def _container_command(entrypoint, candidate=None, cidfile=None):
    command = [
        "docker", "run", "--rm", "-i", "--network", "none", "--read-only",
        "--env", "PYTHONHASHSEED=0", "--env", "PYTHONUTF8=1",
        "--user", "65534:65534", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "64",
        "--memory", "512m", "--cpus", "1", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
    ]
    if cidfile is not None:
        command += ["--cidfile", str(cidfile)]
    if candidate is not None:
        command += ["--mount", f"type=bind,src={candidate},dst=/candidate.py,readonly"]
    command += [IMAGE, "python", "-B", entrypoint]
    if candidate is not None:
        command.append("/candidate.py")
    return command


def _run_container(entrypoint, request, timeout, program_path=None):
    start = perf_counter()
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        directory = Path(directory)
        candidate = None
        if program_path is not None:
            candidate = directory / "candidate.py"
            candidate.write_bytes(Path(program_path).read_bytes())
        cidfile = directory / "container.cid"
        command = _container_command(entrypoint, candidate, cidfile)
        try:
            result = subprocess.run(command, input=json.dumps(request), text=True,
                                    capture_output=True, timeout=timeout + 5)
        except subprocess.TimeoutExpired:
            if cidfile.exists():
                subprocess.run(["docker", "rm", "-f", cidfile.read_text().strip()],
                               capture_output=True, timeout=5)
            raise
    if result.returncode:
        if "TN_ERROR:TIMEOUT" in result.stderr:
            raise subprocess.TimeoutExpired(command, timeout)
        if "TN_ERROR:RESOURCE_LIMIT" in result.stderr or result.returncode == 137:
            raise ResourceLimitError("candidate exceeded the container memory limit")
        raise RuntimeError(result.stderr[-1000:] or f"runner exited {result.returncode}")
    return json.loads(result.stdout), perf_counter() - start


def run_candidate(program_path, case, timeout=10):
    """Return the runner response and measured wall time.

    TN_EXECUTION_MODE=local is reserved for local tests. Formal runs require Docker.
    """
    mode = os.environ.get("TN_EXECUTION_MODE", "container")
    if mode not in ("container", "local"):
        raise ValueError(f"unknown execution mode: {mode}")
    start = perf_counter()
    if mode == "local":
        import sys
        command = [sys.executable, str(ROOT / "candidate_runner.py"), str(program_path)]
        result = subprocess.run(command, input=json.dumps(case), text=True,
                                capture_output=True, timeout=timeout, cwd=ROOT)
    else:
        return _run_container("/runner.py", case, timeout, program_path)
    wall_seconds = perf_counter() - start
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:] or f"runner exited {result.returncode}")
    return json.loads(result.stdout), wall_seconds


def run_baseline(case, method, timeout=10):
    """Use the same resource limits as candidate search in formal runs."""
    mode = os.environ.get("TN_EXECUTION_MODE", "container")
    if mode == "local":
        import sys
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = "0"
        start = perf_counter()
        result = subprocess.run(
            [sys.executable, str(ROOT / "baseline_worker.py")],
            input=json.dumps({"case": case, "method": method}),
            text=True, capture_output=True, timeout=timeout + 5,
            cwd=ROOT, env=env,
        )
        wall = perf_counter() - start
        if result.returncode:
            raise RuntimeError(result.stderr[-1000:] or f"baseline worker exited {result.returncode}")
        return json.loads(result.stdout), wall
    if mode != "container":
        raise ValueError(f"unknown execution mode: {mode}")
    return _run_container("/baseline_runner.py", {"case": case, "method": method}, timeout)
