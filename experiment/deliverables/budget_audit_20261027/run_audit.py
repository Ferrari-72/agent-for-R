"""Windows orchestrator; stages public bytes and executes only in existing Linux image."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

HERE = Path(__file__).resolve().parent
EXP = HERE.parents[1]
ROOT = HERE.parents[2]
IMAGE = "sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3"
PUBLIC = ROOT / "experiment/deliverables/patch_compatibility_20261027"
TEACHER = ROOT / "experiment/deliverables/teacher_review_20261027"
RESULTS = EXP / ".tmp/results/budget_audit_20261027"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="run synthetic test-only contracts")
    parser.add_argument("--identity", type=Path, help="explicit nonsecret identity JSON")
    parser.add_argument("--receipt", type=Path, help="complete external exact-count receipt")
    parser.add_argument("--adapter", type=Path, help="caller-selected exact local tokenizer adapter")
    parser.add_argument("--artifact", type=Path, help="exact tokenizer artifact (no downloads)")
    args = parser.parse_args()
    measured = bool(args.receipt or args.adapter or args.artifact or args.identity)
    if measured and (not args.identity or bool(args.receipt) == bool(args.adapter)
                     or bool(args.adapter) != bool(args.artifact) or args.test):
        parser.error("use --identity with either --receipt OR --adapter plus --artifact; separate from --test")
    # Caller must stage explicitly approved nonsecret inputs inside the allowed task areas.
    for path in (args.identity, args.receipt, args.adapter, args.artifact):
        if path and not (path.resolve().is_relative_to(HERE)
                         or path.resolve().is_relative_to(RESULTS)):
            parser.error("explicit nonsecret audit inputs must be inside this pack or its .tmp/results folder")
    image = json.loads(subprocess.check_output(["docker", "image", "inspect", IMAGE], timeout=30))[0]
    if image["Id"] != IMAGE or image["Os"] != "linux":
        raise RuntimeError("exact existing pinned Linux image required; no pulls/builds")
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / ("run_" + uuid.uuid4().hex)
    stage = out / "caller"
    stage.mkdir(parents=True)
    files = {
        "audit.py": HERE / "audit.py",
        "test_audit.py": HERE / "test_audit.py",
        "patch_summary.json": PUBLIC / "patch_compatibility_summary.json",
        "heuristics.py": TEACHER / "heuristics.py",
        "export_candidates.py": TEACHER / "export_candidates.py",
        # Public implementation text only; never imported/executed or used to read config.
        "public_run_experiment.txt": ROOT / "experiment/run_experiment.py",
    }
    for name, source in files.items():
        shutil.copyfile(source, stage / name)
    (stage / "options.json").write_text(json.dumps({"mode": "receipt" if args.receipt else
        "local" if args.adapter else "unmeasured"}, separators=(",", ":")) + "\n", encoding="utf-8")
    if measured:
        shutil.copyfile(args.identity, stage / "identity.json")
    if args.receipt:
        shutil.copyfile(args.receipt, stage / "receipt.json")
    if args.adapter:
        shutil.copyfile(args.adapter, stage / "adapter.py")
        shutil.copyfile(args.artifact, stage / "tokenizer.artifact")
    env = dict(os.environ)
    env["MSYS_NO_PATHCONV"] = "1"
    command = ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only", "--user", "65534:65534",
               "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=64", "--cpus=1",
               "--memory=2g", "--memory-swap=2g", "-e", "PYTHONDONTWRITEBYTECODE=1",
               "--mount", f"type=bind,src={stage},dst=/audit,readonly", IMAGE,
               "python", "-I", "-B", "/audit/test_audit.py" if args.test else "/audit/audit.py"]
    staged_hashes = {p.name: sha(p) for p in stage.iterdir()}
    (out / "invocation.json").write_text(json.dumps({"command": command, "image": IMAGE,
        "sources": staged_hashes, "launcher_sha256": sha(HERE / "run_audit.py"),
        "model_requests": 0}, indent=2) + "\n")
    proc = subprocess.run(command, capture_output=True, timeout=600, env=env)
    (out / "stdout.log").write_bytes(proc.stdout)
    (out / "stderr.log").write_bytes(proc.stderr)
    (out / "process.json").write_text(json.dumps({"returncode": proc.returncode}, indent=2) + "\n")
    if proc.returncode:
        raise RuntimeError(f"Linux audit failed; see {out}")
    after = {p.name: sha(p) for p in stage.iterdir()}
    if after != staged_hashes:
        raise RuntimeError(f"staged audit inputs changed; see {out}")
    if args.test:
        print(json.dumps({"tests": "passed", "output": str(out), "model_requests": 0}, indent=2))
        return
    report = json.loads(proc.stdout)
    if report.get("source_sha256") != staged_hashes:
        raise RuntimeError(f"Linux/source identity mismatch; see {out}")
    report["image_id"] = IMAGE
    report["execution_limits"] = {"cpus": 1, "memory_bytes": 2 * 1024**3,
        "memory_plus_swap_bytes": 2 * 1024**3, "pids": 64, "network": "none",
        "read_only": True, "uid": 65534}
    report["resource_preparation_status"] = "pinned_offline_audit_ran_successfully; not solver workload calibration"
    report["launcher_sha256"] = sha(HERE / "run_audit.py")
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    (out / "budget_audit_summary.json").write_text(serialized)
    (HERE / "budget_audit_summary.json").write_text(serialized)
    print(json.dumps({"status": report["status"], "summary": str(out / "budget_audit_summary.json"),
                      "responses": len(report["responses"]), "model_requests": 0,
                      "cap_assessments": report["cap_assessments"]}, indent=2))


if __name__ == "__main__":
    main()
