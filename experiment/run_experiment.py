"""Verify the initial solution, then run one OpenEvolve generation."""

import argparse
import json
import math
import os
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from openevolve.api import run_evolution
from openevolve.config import load_config
from openevolve.utils.request_budget import request_usage

from openevolve_evaluator import evaluate
from tnlab.baselines import run_baseline
from tnlab.execution import run_baseline as run_isolated_baseline
from tnlab.freeze import (archive_runner_image, frozen_file_hashes,
                          snapshot_frozen_data, snapshot_frozen_sources)
from tnlab.instances import load_cases
from tnlab.scoring import score_path
from tnlab.prompt_policy import prompt_policy_manifest, prompt_policy_sha256

ROOT = Path(__file__).resolve().parent


def baseline_record(case, method):
    answer, wall = run_isolated_baseline(case, method)
    seconds = float(answer["search_seconds"])
    if seconds > 10 or seconds < 0:
        raise RuntimeError(f"baseline exceeded search limit: {case['name']} {method}")
    score = score_path(case, answer["path"])
    if score.peak_elements > 2**20:
        raise RuntimeError(f"baseline exceeded peak limit: {case['name']} {method}")
    return {"case": case["name"], "method": method, "path": answer["path"],
            "cost": score.cost, "peak_elements": score.peak_elements,
            "search_seconds": seconds, "wall_seconds": wall}


def prepare_development_baselines(output, set_name):
    """Check benchmark feasibility before any model-generated candidate is evaluated."""
    records = [baseline_record(case, method)
               for case in load_cases(set_name)
               for method in ("greedy", "random-greedy", "simulated-annealing")]
    target = output / "development_baselines.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return records


def derive_iteration_statistics(rounds, request_usage_record=None):
    """Project distinct run counters from the raw per-iteration journal.

    A journal iteration is a scheduler/evidence unit.  A generation attempt is
    an iteration that reached the model stage; a completed evaluation is an
    evaluation_total stage, including failed evaluations.  A valid candidate
    has a completed evaluation with failure_count == 0, whether or not MAP-
    Elites later admits it.  Model HTTP requests come from the durable ledger,
    because retries and failed requests are not represented one-for-one by
    journal records.
    """
    def stage(item, name):
        return next((entry for entry in item.get("stages", [])
                     if entry.get("stage") == name), None)

    generation_attempts = sum(stage(item, "model_request") is not None for item in rounds)
    completed_evaluations = sum(stage(item, "evaluation_total") is not None for item in rounds)
    failed_evaluations = sum(
        (stage(item, "evaluation_total") or {}).get("status") == "failed"
        for item in rounds
    )
    valid_candidates = sum(
        isinstance(item.get("metrics"), dict)
        and item["metrics"].get("failure_count", 1) == 0
        and stage(item, "evaluation_total") is not None
        for item in rounds
    )
    admitted_candidates = sum(item.get("status") == "admitted" for item in rounds)
    rejected_candidates = sum(item.get("status") == "rejected" for item in rounds)
    statistics = {
        "journal_iterations": len(rounds),
        "generation_attempts": generation_attempts,
        "completed_evaluations": completed_evaluations,
        "failed_evaluations": failed_evaluations,
        "valid_candidates": valid_candidates,
        "admitted_candidates": admitted_candidates,
        "rejected_candidates": rejected_candidates,
        "model_requests": request_usage_record or {"total": 0, "by_kind": {}},
    }
    statistics["invariants"] = {
        "registered_iteration_limit": 15,
        "journal_iterations_equal_registered_limit":
            statistics["journal_iterations"] == 15,
        "model_requests_are_ledger_count": True,
        "generation_attempts_may_differ_from_journal_iterations": True,
        "valid_candidates_may_differ_from_generation_attempts": True,
        "completed_evaluations_may_differ_from_generation_attempts": True,
    }
    return statistics


def _write_prompt_policy_manifest(output):
    manifest = prompt_policy_manifest()
    payload = {"manifest": manifest, "sha256": prompt_policy_sha256(manifest)}
    (Path(output) / "prompt_policy_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    return payload


def _verify_prompt_policy_manifest(output):
    path = Path(output) / "prompt_policy_manifest.json"
    if not path.is_file():
        raise RuntimeError("run is missing its prompt policy manifest")
    saved = json.loads(path.read_text(encoding="utf-8"))
    current = prompt_policy_manifest()
    if saved.get("manifest") != current or saved.get("sha256") != prompt_policy_sha256(current):
        raise RuntimeError("current prompt policy differs from the frozen run")
    return saved


def _ensure_fake_runner_image(output):
    """Create explicit local-only runner identity evidence for the fake drill."""
    archive = Path(output) / "runner-image.tar"
    if not archive.exists():
        archive.write_bytes(b"fake-drill-runner-image-v1")
    archive_hash = sha256(archive.read_bytes()).hexdigest()
    source_hash = sha256(b"fake-drill-runner-source-v1").hexdigest()
    manifest = {
        "image_id": "fake-drill-image-v1",
        "source_sha256": source_hash,
        "requirements_sha256": sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
        "archive": archive.name,
        "archive_sha256": archive_hash,
    }
    (Path(output) / "runner_image_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _format_process_round(item):
    """Normalize one journal record for human-readable experiment review."""
    stages = item.get("stages") or []
    failed_stage = next((stage for stage in stages if stage.get("status") in
                         ("failed", "rejected")), None)
    change = item.get("change_summary") or {}
    metrics = item.get("metrics") or {}
    usage = item.get("token_usage") or {}
    return {
        "iteration": item.get("iteration"),
        "status": item.get("status", "unknown"),
        "parent_id": item.get("parent_id"),
        "program_id": item.get("program_id"),
        "changes_description": item.get("changes_description", ""),
        "change_summary": change,
        "source_diff": item.get("artifact_files", {}).get("source_diff"),
        "metrics": metrics,
        "parent_metrics": item.get("parent_metrics", {}),
        "failure": {
            "stage": failed_stage.get("stage") if failed_stage else None,
            "error_code": item.get("error_code") or (failed_stage or {}).get("error_code"),
            "reason": item.get("error"),
        },
        "stages": stages,
        "token_usage": usage,
        "prompt_metadata": item.get("prompt_metadata", {}),
        "artifact_files": item.get("artifact_files", {}),
    }


def _latest_checkpoint(run_dir):
    checkpoints = run_dir / "checkpoints"
    if not checkpoints.is_dir():
        return None
    available = []
    for path in checkpoints.glob("checkpoint_*"):
        try:
            iteration = int(path.name.removeprefix("checkpoint_"))
        except ValueError:
            continue
        if path.is_dir():
            available.append((iteration, path))
    return max(available, default=(None, None))[1]


def summarize_previous_run(run_dir):
    """Build a bounded human-audit summary from the latest completed records."""
    journal = run_dir / "iteration_journal.jsonl"
    rounds = []
    if journal.is_file():
        for line in journal.read_text(encoding="utf-8").splitlines():
            try:
                rounds.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    last = rounds[-5:]
    report_path = run_dir / "development_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    checkpoint = _latest_checkpoint(run_dir)
    summary = {
        "source_run": str(run_dir.resolve()),
        "research_id": (run_dir / "research_id.txt").read_text(encoding="utf-8").strip()
                       if (run_dir / "research_id.txt").is_file() else None,
        "termination_reason": report.get("search", {}).get("termination_reason"),
        "iterations_recorded": len(rounds),
        "latest_checkpoint": str(checkpoint.relative_to(run_dir)) if checkpoint else None,
        "recent_iterations": [_format_process_round(item) for item in last],
        "prompt_policy": "audit summary only; never appended to a fresh run prompt",
    }
    return summary


def attach_previous_run_summary(output):
    runs = [path for path in (ROOT / "results").glob("evolve_*")
            if path.is_dir() and path.resolve() != output.resolve()
            and (path / "iteration_journal.jsonl").is_file()]
    if not runs:
        return None
    previous = max(runs, key=lambda path: (path / "iteration_journal.jsonl").stat().st_mtime)
    summary = summarize_previous_run(previous)
    target = output / "previous_run_summary.json"
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return {"source_run": summary["source_run"],
            "sha256": sha256(target.read_bytes()).hexdigest()}


def write_process_summary(output, rounds, report):
    """Write an auditable process summary without replacing raw iteration evidence."""
    process = [_format_process_round(item) for item in rounds]
    (output / "process_summary.json").write_text(
        json.dumps(process, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Experiment Process", "", "This summary is derived from iteration_journal.jsonl.",
             "Raw prompts, model responses, and candidate files remain in each iteration artifact directory.", ""]
    for item in process:
        change = item["change_summary"]
        metrics = item["metrics"]
        usage = item["token_usage"]
        status = item["status"]
        lines.append(f"## Iteration {item['iteration']}: {status}")
        lines.append(f"- Parent: `{item['parent_id'] or 'none'}`; child: `{item['program_id'] or 'none'}`")
        if change:
            lines.append(
                f"- Source change: +{change.get('added_lines', 0)}/-{change.get('removed_lines', 0)} lines; "
                f"parent `{change['parent_sha256'][:12]}` -> child `{change['child_sha256'][:12]}`"
            )
        if item["changes_description"]:
            lines.append(f"- Claimed change: {item['changes_description']}")
        if item["stages"]:
            lines.append("- Stages: " + "; ".join(
                f"{stage.get('stage')}={stage.get('status')}"
                + (f" ({stage.get('seconds', 0.0):.3f}s)" if stage.get('seconds') is not None else "")
                for stage in item["stages"]))
        if metrics:
            lines.append(f"- Metrics: `{json.dumps(metrics, ensure_ascii=False, sort_keys=True)}`")
        if usage:
            lines.append(f"- Model usage: `{json.dumps(usage, ensure_ascii=False, sort_keys=True)}`")
        failure = item["failure"]
        if failure["reason"]:
            lines.append(f"- Failure: `{failure['error_code'] or 'unknown'}`: {failure['reason']}")
        if item["prompt_metadata"]:
            lines.append("- Prompt evidence: " + ", ".join(
                f"{name} sha256 `{data['sha256'][:12]}`, {data['characters']} chars"
                for name, data in item["prompt_metadata"].items()))
        if item["artifact_files"]:
            lines.append("- Artifacts: " + ", ".join(
                f"`{name}` -> `{path}`" for name, path in item["artifact_files"].items()))
        lines.append("")
    search = report.get("search", {})
    lines.extend([
        "## Run Totals", "",
        f"- Candidate attempts: {search.get('candidate_attempts', 0)}",
        f"- Valid candidates: {search.get('valid_candidates', 0)}",
        f"- Termination: {search.get('termination_reason', 'completed')}",
        f"- Tokens: `{json.dumps(search.get('tokens', {}), ensure_ascii=False, sort_keys=True)}`",
        "",
    ])
    (output / "experiment_process.md").write_text("\n".join(lines), encoding="utf-8")



def write_report(result, output, iterations_requested=None):
    trace = output / "evolution_trace.jsonl"
    journal = output / "iteration_journal.jsonl"
    if not journal.exists() or not journal.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"模型迭代缺少追踪记录；查看日志：{output / 'logs'}")
    rounds = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    saved_manifest = output / "frozen_source_manifest.json"
    if saved_manifest.exists() and json.loads(saved_manifest.read_text(encoding="utf-8")) != frozen_file_hashes():
        raise RuntimeError("evaluation code changed during the model run")
    if result.best_program is None:
        report = build_search_report(
            output, rounds, None, iterations_requested, trace_count=0,
            failure="no valid candidate was admitted",
        )
        (output / "development_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        write_process_summary(output, rounds, report)
        print("开发集报告：", output / "development_report.json")
        return report
    best_file = output / "best_recheck.py"
    best_file.write_text(result.best_code, encoding="utf-8")
    checked = evaluate(best_file)
    if abs(checked.metrics["combined_score"] - result.best_score) > 1e-9:
        raise RuntimeError("框架最佳分数与独立复核不一致")
    develop_name = os.environ.get("TN_DEVELOP_SET", "develop_v2.json")
    prepared = output / "development_baselines.json"
    baseline_records = (json.loads(prepared.read_text(encoding="utf-8"))
                        if prepared.exists() else
                        prepare_development_baselines(output, develop_name))
    case_results = json.loads(checked.artifacts["case_results.json"])
    reference_costs = {}
    for item in baseline_records:
        reference_costs[item["case"]] = min(
            item["cost"], reference_costs.get(item["case"], item["cost"]))
    strong_ratio = (math.exp(sum(math.log(item["cost"] / reference_costs[item["case"]])
                                 for item in case_results) / len(case_results))
                   if all("cost" in item for item in case_results) else None)
    report = build_search_report(
        output, rounds, {
            "metrics": checked.metrics, "cases": case_results,
            "geometric_ratio_to_best_baseline": strong_ratio,
        }, iterations_requested, trace_count=(
            len(trace.read_text(encoding="utf-8").splitlines()) if trace.exists() else 0),
        best_code_sha256=sha256(best_file.read_bytes()).hexdigest(),
        develop_set=develop_name, baseline_records=baseline_records,
    )
    report["environment"]["development_baselines_sha256"] = sha256(
        prepared.read_bytes()).hexdigest()
    (output / "development_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_process_summary(output, rounds, report)
    print("输出目录：", output)
    print("框架最佳分数：", result.best_score)
    print("独立复核：", json.dumps(checked.metrics, ensure_ascii=False))
    print("开发集报告：", output / "development_report.json")
    return report


def build_search_report(output, rounds, develop, iterations_requested,
                        trace_count, failure=None, best_code_sha256=None,
                        develop_set=None, baseline_records=None):
    valid = sum(bool(item.get("metrics")) and
                item["metrics"].get("failure_count") == 0 for item in rounds)
    request_start_id = int(os.environ.get("TN_RUN_REQUEST_START_ID", "0"))
    run_id = os.environ.get("TN_RUN_ID")
    if os.environ.get("TN_EXECUTION_MODE") == "container" and (
            not run_id or "TN_RUN_REQUEST_COUNT_BEFORE" not in os.environ):
        raise RuntimeError("formal report requires run_id and request count before probe")
    requests_added = request_usage(run_id=run_id) if run_id else request_usage(after_id=request_start_id)
    requests_after = request_usage()
    requests_before = int(os.environ.get(
        "TN_RUN_REQUEST_COUNT_BEFORE",
        str(requests_after["total"] - requests_added["total"])))
    other_requests = requests_after["total"] - requests_before - requests_added["total"]
    if other_requests < 0:
        raise RuntimeError("request counts are inconsistent with this run ID")
    image_manifest_path = output / "runner_image_manifest.json"
    image_manifest = (json.loads(image_manifest_path.read_text(encoding="utf-8"))
                      if image_manifest_path.exists() else {})
    if not (Path(output) / "prompt_policy_manifest.json").is_file():
        _write_prompt_policy_manifest(output)
    prompt_policy = _verify_prompt_policy_manifest(output)
    statistics = derive_iteration_statistics(rounds, requests_added)
    report = {"develop": develop, "baselines": ({develop_set: baseline_records}
              if develop_set and baseline_records is not None else {}),
              "search": {
                  "candidate_attempts": len(rounds), "valid_candidates": valid,
                  "valid_candidate_rate": valid / len(rounds) if rounds else None,
                  "iteration_statistics": statistics,
                  "tokens": {key: sum((item.get("token_usage") or {}).get(key, 0) or 0
                                       for item in rounds)
                             for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
                  "request_count_before": requests_before,
                  "request_count_after": requests_after["total"],
                  "requests_added_this_run": requests_added,
                  "requests_from_other_runs_during_window": other_requests,
                  "budget_db_cumulative_count": requests_after["total"],
                  "http_requests": requests_added,
                  "http_requests_budget_total": requests_after,
                  "request_start_id": request_start_id,
                  "run_id": run_id,
                  "research_id": os.environ.get("TN_RESEARCH_ID"),
                  "registration_sha256": (
                      sha256((output / "preregistration.md").read_bytes()).hexdigest()
                      if (output / "preregistration.md").is_file() else None),
                  "request_limit": os.environ.get("OPENEVOLVE_REQUEST_LIMIT"),
                  "prompt_policy_sha256": prompt_policy["sha256"],
                  "prompt_policy_manifest": "prompt_policy_manifest.json",
                  "previous_run_summary": (
                      "previous_run_summary.json"
                      if (output / "previous_run_summary.json").is_file() else None
                  ),
                  "previous_run_summary_sha256": (
                      sha256((output / "previous_run_summary.json").read_bytes()).hexdigest()
                      if (output / "previous_run_summary.json").is_file() else None
                  ),
              },
              "environment": {
                  "python": sys.version,
                  "versions": {name: version(name) for name in
                               ("cotengra", "opt_einsum", "quimb", "openevolve")},
                  "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
                  "config_sha256": sha256((ROOT / "config.yaml").read_bytes()).hexdigest(),
                  "requirements_sha256": sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
                  "benchmark_manifest_sha256": sha256((ROOT / "data" / "manifest_v2.json").read_bytes()).hexdigest(),
                  "heldout_manifest_sha256": sha256((ROOT / "data" / "manifest_v3.json").read_bytes()).hexdigest(),
                  "initial_program_sha256": sha256((ROOT / "initial_program.py").read_bytes()).hexdigest(),
                  "runner_image_id": image_manifest.get("image_id"),
                  "runner_image_source_sha256": image_manifest.get("source_sha256"),
                  "frozen_file_hashes": frozen_file_hashes(),
                  "best_code_sha256": best_code_sha256,
                  "develop_set": develop_set,
                  "model": os.environ.get("TN_MODEL", "deepseek-ai/DeepSeek-V3.2"),
                  "iterations_requested": iterations_requested,
                  "iterations_recorded": len(rounds),
                  "admitted_candidate_traces": trace_count,
                  "request_budget_db": os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB"),
                  "request_limit": os.environ.get("OPENEVOLVE_REQUEST_LIMIT"),
              }}
    if failure:
        report["search"]["termination_reason"] = failure
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument(
        "--resume-run",
        type=Path,
        help="resume an existing run directory from its newest checkpoint",
    )
    args = parser.parse_args()
    if args.iterations != 15:
        parser.error("formal discovery runs require exactly 15 iterations")
    initial = ROOT / "initial_program.py"
    before = evaluate(initial)
    print("初始程序：", json.dumps(before.metrics, ensure_ascii=False))
    if before.metrics["failure_count"]:
        raise RuntimeError("初始程序未通过评估")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("缺少 OPENAI_API_KEY；请运行 run.ps1 输入 SiliconFlow 密钥")
    registration = Path(os.environ.get("TN_REGISTRATION_FILE", ROOT / "notes" /
                                      "formal_registration_2026-10.md"))
    if not registration.is_file():
        raise RuntimeError(f"正式运行前必须完成研究登记：{registration}")
    if not os.environ.get("TN_RESEARCH_ID"):
        raise RuntimeError("正式运行必须设置 TN_RESEARCH_ID")

    checkpoint = None
    if args.resume_run:
        output = args.resume_run.resolve()
        if not output.is_dir():
            raise RuntimeError(f"resume run directory does not exist: {output}")
        checkpoint = _latest_checkpoint(output)
        if checkpoint is None:
            raise RuntimeError(f"resume run has no checkpoint: {output}")
        checkpoint_iteration = int(checkpoint.name.removeprefix("checkpoint_"))
        remaining_iterations = args.iterations - checkpoint_iteration
        if remaining_iterations <= 0:
            raise RuntimeError("resume run already reached its registered iteration limit")
        saved_registration = output / "preregistration.md"
        saved_research_id = output / "research_id.txt"
        if not saved_registration.is_file() or not saved_research_id.is_file():
            raise RuntimeError("resume run is missing its frozen registration identity")
        if saved_registration.read_bytes() != registration.read_bytes():
            raise RuntimeError("resume registration differs from the current registration")
        if saved_research_id.read_text(encoding="utf-8").strip() != os.environ["TN_RESEARCH_ID"]:
            raise RuntimeError("resume research ID differs from the current research ID")
        saved_run_id_path = output / "run_id.txt"
        if not saved_run_id_path.is_file():
            raise RuntimeError("resume run is missing its original run ID")
        original_run_id = saved_run_id_path.read_text(encoding="utf-8").strip()
        if not original_run_id:
            raise RuntimeError("resume run has an empty original run ID")
        os.environ["TN_RUN_ID"] = original_run_id
        saved_manifest_path = output / "frozen_source_manifest.json"
        if not saved_manifest_path.is_file():
            raise RuntimeError("resume run is missing its frozen source manifest")
        saved_manifest = json.loads(saved_manifest_path.read_text(encoding="utf-8"))
        if saved_manifest != frozen_file_hashes():
            raise RuntimeError("current source differs from the resumed run's frozen manifest")
        _verify_prompt_policy_manifest(output)
        initial_hash_path = output / "initial_program.sha256"
        current_initial_hash = sha256(initial.read_bytes()).hexdigest()
        if not initial_hash_path.is_file() or initial_hash_path.read_text(
                encoding="ascii").strip() != current_initial_hash:
            raise RuntimeError("initial program differs from the resumed run")
        os.environ["OPENEVOLVE_ITERATION_JOURNAL"] = str(output / "iteration_journal.jsonl")
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
        output = ROOT / "results" / f"evolve_{stamp}"
        snapshot_frozen_sources(output)
        _write_prompt_policy_manifest(output)
        registration_bytes = registration.read_bytes()
        (output / "preregistration.md").write_bytes(registration_bytes)
        (output / "preregistration.sha256").write_text(
            sha256(registration_bytes).hexdigest() + "\n", encoding="ascii")
        (output / "research_id.txt").write_text(
            os.environ["TN_RESEARCH_ID"] + "\n", encoding="utf-8")
        (output / "initial_program.sha256").write_text(
            sha256(initial.read_bytes()).hexdigest() + "\n", encoding="ascii")
        if os.environ.get("TN_RUN_ID"):
            (output / "run_id.txt").write_text(os.environ["TN_RUN_ID"] + "\n",
                                                encoding="utf-8")
        snapshot_frozen_data(output, os.environ.get("TN_DEVELOP_SET", "develop_v2.json"))
        os.environ["OPENEVOLVE_ITERATION_JOURNAL"] = str(output / "iteration_journal.jsonl")
        previous = attach_previous_run_summary(output)
        if previous:
            os.environ["TN_PREVIOUS_RUN_SUMMARY_PATH"] = str(output / "previous_run_summary.json")
            os.environ["TN_PREVIOUS_RUN_SUMMARY_SHA256"] = previous["sha256"]

    fake_drill = os.environ.get("TN_FAKE_DRILL") == "1"
    image_id = (subprocess.run(
        ["docker", "image", "inspect", "tnlab-runner:py313-v1", "--format", "{{.Id}}"],
        capture_output=True, text=True, check=True).stdout.strip()
        if os.environ.get("TN_EXECUTION_MODE") == "container" else None)
    if fake_drill:
        image_id = None
    runner_source_hash = (subprocess.run(
        [sys.executable, "-c", "from tnlab.freeze import image_source_hash; print(image_source_hash())"],
        cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        if image_id else None)
    if args.resume_run and image_id:
        saved_image_manifest = output / "runner_image_manifest.json"
        if not saved_image_manifest.is_file():
            raise RuntimeError("resume run is missing its runner image manifest")
        saved_image = json.loads(saved_image_manifest.read_text(encoding="utf-8"))
        if saved_image.get("image_id") != image_id:
            raise RuntimeError("current runner image differs from the resumed run")
        if saved_image.get("source_sha256") != runner_source_hash:
            raise RuntimeError("current runner source differs from the resumed runner")
    if image_id and not (output / "runner_image_manifest.json").is_file():
        archive_runner_image(output, image_id, runner_source_hash)
    if fake_drill and not (output / "runner_image_manifest.json").is_file():
        _ensure_fake_runner_image(output)
    if not args.resume_run:
        prepare_development_baselines(output, os.environ.get("TN_DEVELOP_SET", "develop_v2.json"))
    elif not (output / "development_baselines.json").is_file():
        raise RuntimeError("resume run is missing its frozen development baselines")
    config = load_config(ROOT / "config.yaml")
    api_base = os.environ.get("TN_API_BASE")
    if api_base:
        config.llm.update_model_params({"api_base": api_base}, overwrite=True)
    selected_model = os.environ.get("TN_MODEL")
    if selected_model:
        for model in config.llm.models:
            model.name = selected_model
        for model in config.llm.evaluator_models:
            model.name = selected_model
    run_iterations = remaining_iterations if args.resume_run else args.iterations
    result = run_evolution(initial, ROOT / "openevolve_evaluator.py",
                           config=config, iterations=run_iterations,
                           output_dir=str(output), cleanup=False,
                           checkpoint_path=str(checkpoint) if checkpoint else None)
    write_report(result, output, args.iterations)


if __name__ == "__main__":
    main()
