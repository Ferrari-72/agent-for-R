"""Hash the rules and execution code used by formal comparison."""

from hashlib import sha256
from pathlib import Path
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "config.yaml", "requirements.lock", "Dockerfile.runner",
    "prompts/diff_user.txt", "prompts/framework_concepts.md",
    "notes/iteration_audit_2026-10-22.md",
    "notes/evolution_research_workflow.md",
    "notes/experiment_registration_template.md",
    "candidate_runner.py", "candidate_worker.py", "baseline_runner.py",
    "baseline_worker.py", "tnlab/runner_protocol.py", "openevolve_evaluator.py",
    "../openevolve/openevolve/process_parallel.py",
    "final_evaluation.py", "tnlab/scoring.py", "tnlab/baselines.py",
    "tnlab/comparison.py", "tnlab/execution.py", "tnlab/resource_limits.py",
    "tnlab/instances.py", "prepare_benchmark.py", "run_experiment.py",
    "tnlab/experience.py",
    "run_baselines.py",
    "tnlab/freeze.py", "run.ps1", "setup.ps1",
    "../openevolve/openevolve/utils/request_budget.py",
)
IMAGE_FILES = (
    "Dockerfile.runner", "requirements.lock", "candidate_runner.py",
    "candidate_worker.py", "baseline_runner.py", "baseline_worker.py",
)


def frozen_file_hashes():
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in FILES}


def snapshot_frozen_sources(output):
    """Save exact rule and runner source bytes with each formal run."""
    output = Path(output)
    hashes = frozen_file_hashes()
    target = output / "frozen_sources"
    for name in FILES:
        source = ROOT / name
        relative = Path(name)
        if relative.parts[0] == "..":
            relative = Path(*relative.parts[1:])
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (output / "frozen_source_manifest.json").write_text(
        json.dumps(hashes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashes


def archive_runner_image(output, image_id, source_hash):
    """Export and checksum the exact runner image used by a formal run."""
    output = Path(output)
    archive = output / "runner-image.tar"
    subprocess.run(["docker", "save", "--output", str(archive), image_id], check=True)
    digest = _file_sha256(archive)
    manifest = {
        "image_id": image_id,
        "source_sha256": source_hash,
        "requirements_sha256": sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
        "archive": archive.name,
        "archive_sha256": digest,
    }
    (output / "runner_image_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def verify_runner_image_archive(run_dir, expected_image_id, expected_source_hash):
    """Reject missing, altered, or mismatched runner image archives."""
    run_dir = Path(run_dir)
    manifest_path = run_dir / "runner_image_manifest.json"
    if not manifest_path.is_file():
        raise ValueError("runner image archive manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive = run_dir / manifest.get("archive", "")
    if not archive.is_file() or _file_sha256(archive) != manifest.get(
            "archive_sha256"):
        raise ValueError("runner image archive is missing or has changed")
    if manifest.get("image_id") != expected_image_id:
        raise ValueError("runner image archive ID differs from development freeze")
    if manifest.get("source_sha256") != expected_source_hash:
        raise ValueError("runner image source hash differs from development freeze")
    requirements_hash = sha256((ROOT / "requirements.lock").read_bytes()).hexdigest()
    if manifest.get("requirements_sha256") != requirements_hash:
        raise ValueError("runner image dependency lock differs from current source")
    return manifest


def _file_sha256(path):
    """Hash large image archives without loading them into host memory."""
    digest = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def image_source_hash():
    names = (*IMAGE_FILES, *(f"tnlab/{file.name}" for file in
                             sorted((ROOT / "tnlab").glob("*.py"))))
    digest = sha256()
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((ROOT / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
