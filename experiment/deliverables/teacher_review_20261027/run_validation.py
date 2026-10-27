"""Host-only staging and Docker orchestration for the teacher-review pack.

Run: python -I -B experiment/deliverables/teacher_review_20261027/run_validation.py
All algorithm execution and independent scoring take place inside Linux Docker.
A new evidence directory is retained on every attempt, including failures.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
IMAGE = "sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3"
IMAGE_SOURCE = "008592ed6a4dc8291f5de6f7719799bfe839b0758170bfbc7f8aac494979c763"
SOURCES = ("heuristics.py", "validate.py", "export_candidates.py")


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], timeout=30))[0]
    if image["Id"] != IMAGE or image["Os"] != "linux":
        raise RuntimeError("expected the exact existing Linux image; no build or pull is attempted")
    labels = image["Config"]["Labels"] or {}
    if labels.get("org.tnlab.benchmark-source-sha256") != IMAGE_SOURCE:
        raise RuntimeError("image source identity differs")
    out = EXPERIMENT / "results" / ("teacher_review_validation_" + uuid.uuid4().hex)
    caller = out / "caller"
    caller.mkdir(parents=True, exist_ok=False)
    for name in SOURCES + ("run_validation.py",):
        shutil.copyfile(HERE / name, caller / name)
    before = {name: digest(caller / name) for name in SOURCES}
    container = "tnlab-teacher-review-" + uuid.uuid4().hex[:16]
    command = [
        "docker", "run", "--rm", "--name", container,
        "--network=none", "--read-only", "--user", "65534:65534",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--cpus=1", "--memory=2g", "--memory-swap=2g",
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "OPENBLAS_NUM_THREADS=1",
        "-e", "OMP_NUM_THREADS=1", "-e", "RAYON_NUM_THREADS=1",
        "--mount", f"type=bind,src={caller},dst=/caller,readonly",
        IMAGE, "python", "-I", "-B", "/caller/validate.py",
    ]
    save_json(out / "invocation.json", {"command": command, "timeout_seconds": 600,
                                       "source_sha256": before, "image_id": IMAGE})
    environment = dict(os.environ)
    environment["MSYS_NO_PATHCONV"] = "1"
    timed_out = False
    try:
        result = subprocess.run(command, capture_output=True, timeout=600, env=environment)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout, stderr, returncode = exc.stdout or b"", exc.stderr or b"", 124
        cleanup = subprocess.run(["docker", "rm", "-f", container], capture_output=True,
                                 timeout=30, env=environment)
        save_json(out / "timeout_cleanup.json", {"returncode": cleanup.returncode,
                                                 "stdout": cleanup.stdout.decode(errors="replace"),
                                                 "stderr": cleanup.stderr.decode(errors="replace")})
    (out / "stdout.log").write_bytes(stdout)
    (out / "stderr.log").write_bytes(stderr)
    save_json(out / "process.json", {"returncode": returncode, "timed_out": timed_out})
    try:
        report = json.loads(stdout)
    except (ValueError, TypeError):
        print(json.dumps({"output": str(out), "status": "driver_failed", "returncode": returncode,
                          "stderr": stderr.decode(errors="replace")[-3000:]}))
        return 1
    after = {name: digest(caller / name) for name in SOURCES}
    if report.get("source_sha256") != before or before != after:
        raise RuntimeError(f"staged source identity mismatch; evidence retained at {out}")
    report.update({
        "image_id": IMAGE,
        "image_embedded_source_hash": IMAGE_SOURCE,
        "staging": "read-only caller mount; staged prototypes are not embedded image source",
        "launcher_sha256": digest(caller / "run_validation.py"),
        "container_limits": {"cpus": 1, "memory_bytes": 2 * 1024**3,
                             "memory_plus_swap_bytes": 2 * 1024**3, "pids": 64,
                             "network": "none", "read_only": True, "uid": 65534},
        "returncode": returncode,
    })
    save_json(out / "completion.json", report)
    if returncode == 0 and report.get("status") == "passed":
        save_json(HERE / "validation_summary.json", report)
    print(json.dumps({"output": str(out), "status": report.get("status"),
                      "checks_passed": report.get("checks_passed"),
                      "checks_total": report.get("checks_total"),
                      "executions": report.get("fresh_process_executions"),
                      "errors": report.get("errors"), "returncode": returncode}, ensure_ascii=True))
    return 0 if returncode == 0 and report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
