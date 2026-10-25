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
    "notes/experiment_registration_template.md",
    "candidate_runner.py", "candidate_worker.py", "baseline_runner.py",
    "baseline_worker.py", "tnlab/runner_protocol.py", "openevolve_evaluator.py",
    "calibrate_api.py",
    "initial_program.py", "probe_api.py",
    "../openevolve/openevolve/process_parallel.py",
    "../openevolve/openevolve/config.py",
    "../openevolve/openevolve/controller.py",
    "../openevolve/openevolve/database.py",
    "../openevolve/openevolve/selection.py",
    "../openevolve/openevolve/evaluator.py",
    "../openevolve/openevolve/population.py",
    "../openevolve/openevolve/prompt/sampler.py",
    "../openevolve/openevolve/prompt/templates.py",
    "../openevolve/openevolve/llm/ensemble.py",
    "../openevolve/openevolve/llm/openai.py",
    "../openevolve/openevolve/utils/code_utils.py",
    "../openevolve/openevolve/api.py",
    "final_evaluation.py", "select_discovery.py", "tnlab/scoring.py", "tnlab/baselines.py",
    "tnlab/comparison.py", "tnlab/execution.py", "tnlab/resource_limits.py",
    "tnlab/instances.py", "prepare_benchmark.py", "run_experiment.py",
    "tnlab/experience.py", "tnlab/prompt_policy.py",
    "../openevolve/openevolve/prompts/defaults/diff_user.txt",
    "../openevolve/openevolve/prompts/defaults/evolution_history.txt",
    "../openevolve/openevolve/prompts/defaults/previous_attempt.txt",
    "../openevolve/openevolve/prompts/defaults/top_program.txt",
    "../openevolve/openevolve/prompts/defaults/inspirations_section.txt",
    "../openevolve/openevolve/prompts/defaults/inspiration_program.txt",
    "../openevolve/openevolve/prompts/defaults/system_message.txt",
    "../openevolve/openevolve/prompts/defaults/user_message_with_changes_description.txt",
    "../openevolve/openevolve/prompts/defaults/full_rewrite_user.txt",
    "../openevolve/openevolve/prompts/defaults/evaluation.txt",
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


def snapshot_frozen_data(output, develop_set="develop_v2.json"):
    """Save development and held-out benchmark bytes with each formal run."""
    output = Path(output)
    target = output / "frozen_data"
    target.mkdir(parents=True, exist_ok=True)
    names = ("manifest_v2.json", develop_set, "manifest_v3.json",
             "final_v3.json", "transfer_v3.json")
    for name in names:
        shutil.copyfile(ROOT / "data" / name, target / name)
    return names


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
