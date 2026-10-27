"""Host metadata/staging only. Topology, tests, solvers and scoring run in Linux."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

HERE = Path(__file__).resolve().parent
EXPERIMENT = HERE.parents[1]
IMAGE = "sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3"
IMAGE_SOURCE = "008592ed6a4dc8291f5de6f7719799bfe839b0758170bfbc7f8aac494979c763"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def main():
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], timeout=30))[0]
    if image["Id"] != IMAGE or image["Os"] != "linux":
        raise RuntimeError("exact existing pinned Linux image required")
    if (image["Config"]["Labels"] or {}).get("org.tnlab.benchmark-source-sha256") != IMAGE_SOURCE:
        raise RuntimeError("image source identity differs")
    run_id = "resource_pilot_20261027_" + uuid.uuid4().hex
    out = EXPERIMENT / "results" / run_id
    stage = EXPERIMENT / ".tmp" / run_id / "caller"
    stage.mkdir(parents=True, exist_ok=False)
    out.mkdir(parents=True, exist_ok=False)
    sources = {name: HERE / name for name in ("pilot.py", "topology.py", "resource_spec.json", "pool_preparation.py", "solver_worker.py")}
    sources.update({
        "engineering_topology.py": HERE.parent / "engineering_pilot_20261027" / "topology.py",
        "heuristics.py": HERE.parent / "teacher_review_20261027" / "heuristics.py",
        "prototype_validate.py": HERE.parent / "teacher_review_20261027" / "validate.py",
        "run_resource_pilot.py": HERE / "run_resource_pilot.py",
    })
    for name, source in sources.items():
        shutil.copyfile(source, stage / name)
    source_hashes = {name: digest(stage / name) for name in sources}
    save(stage / "source_hashes.json", source_hashes)
    source_manifest_hash = digest(stage / "source_hashes.json")
    save(out / "host_manifest.json", {"run_id": run_id, "image_id": IMAGE,
         "image_source_sha256": IMAGE_SOURCE, "source_hashes": source_hashes,
         "source_manifest_sha256": source_manifest_hash,
         "sources": {name: str(source) for name, source in sources.items()}})
    environment = dict(os.environ)
    environment["MSYS_NO_PATHCONV"] = "1"
    base = ["docker", "run", "--rm", "--network=none", "--read-only", "--user", "65534:65534",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64",
            "--cpus=1", "--memory=2g", "--memory-swap=2g",
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONHASHSEED=0",
            "-e", "OPENBLAS_NUM_THREADS=1", "-e", "OMP_NUM_THREADS=1",
            "-e", "MKL_NUM_THREADS=1", "-e", "RAYON_NUM_THREADS=1",
            "-e", "RESOURCE_PILOT_RESULTS=/evidence",
            "-e", "RESOURCE_PILOT_RUN_ID=" + run_id,
            "--mount", f"type=bind,src={stage},dst=/caller,readonly",
            "--mount", f"type=bind,src={out},dst=/evidence",
            "--workdir", "/tmp"]

    def invoke(mode, timeout):
        container = "tnlab-resource-" + mode + "-" + uuid.uuid4().hex[:16]
        command = base + ["--name", container, IMAGE, "python", "-I", "-B", "/caller/pilot.py", "--" + mode]
        save(out / (mode + "_invocation.json"), {"command": command, "timeout_seconds": timeout})
        try:
            process = subprocess.run(command, capture_output=True, timeout=timeout, env=environment)
            stdout, stderr, returncode, timed_out = process.stdout, process.stderr, process.returncode, False
        except subprocess.TimeoutExpired as exc:
            stdout, stderr, returncode, timed_out = exc.stdout or b"", exc.stderr or b"", 124, True
            cleaned = subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30, env=environment)
            save(out / (mode + "_timeout_cleanup.json"), {"returncode": cleaned.returncode,
                 "stdout": cleaned.stdout.decode(errors="replace"), "stderr": cleaned.stderr.decode(errors="replace")})
        (out / (mode + "_stdout.log")).write_bytes(stdout)
        (out / (mode + "_stderr.log")).write_bytes(stderr)
        save(out / (mode + "_process.json"), {"returncode": returncode, "timed_out": timed_out})
        if returncode:
            raise RuntimeError(f"{mode} failed; evidence retained at {out}: {stderr.decode(errors='replace')[-2000:]}")
        return json.loads(stdout)

    prepared = invoke("prepare", 300)
    if prepared["status"] != "prepared" or prepared["cases"] != 12:
        raise RuntimeError("Linux preparation did not produce the complete 12-case pool")
    pool_bytes = (out / "fixture_pool.json").read_bytes()
    pool_file_hash = hashlib.sha256(pool_bytes).hexdigest()
    save(out / "pool_frozen_before_solvers.json", {"pool_sha256": prepared["pool_sha256"],
         "pool_file_sha256": pool_file_hash, "case_count": prepared["cases"],
         "preparation_completed_before_solver_launch": True})
    print(json.dumps({"phase": "pool_prepared", "cases": 12, "pool_sha256": prepared["pool_sha256"],
                      "output": str(out)}), flush=True)
    invoke("run", 2000)
    if digest(out / "fixture_pool.json") != pool_file_hash:
        raise RuntimeError("public pool file changed after solver execution")
    if any(digest(stage / name) != expected for name, expected in source_hashes.items()):
        raise RuntimeError("staged sources changed during run")
    if digest(stage / "source_hashes.json") != source_manifest_hash:
        raise RuntimeError("staged source manifest changed")
    report = json.loads((out / "summary.json").read_bytes())
    if report["source_hashes"] != source_hashes:
        raise RuntimeError("Linux source manifest differs")
    report["evidence_directory"] = str(out)
    report["image"] = {"id": IMAGE, "source_sha256": IMAGE_SOURCE}
    report["pool"]["file_sha256_before_solvers"] = pool_file_hash
    report["pool"]["file_sha256_after_solvers"] = digest(out / "fixture_pool.json")
    save(out / "summary.json", report)
    save(HERE / "summary.json", report)
    shutil.copyfile(out / "fixture_pool.json", HERE / "fixture_pool.json")
    print(json.dumps({"phase": "completed", "output": str(out), "status": report["status"],
                      "cases": len(report["fixtures"]), "rows": len(report["rows"]),
                      "successes": sum(x["status"] == "success" for x in report["rows"]),
                      "aggregates": report["aggregates"]}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
