"""Validate and select the pre-registered best discovery run."""

import argparse
import hashlib
import json
import math
import os
import subprocess
from pathlib import Path

from openevolve.utils.request_budget import request_usage
from openevolve_evaluator import evaluate_set
from tnlab.baselines import run_baseline
from tnlab.freeze import frozen_file_hashes, verify_runner_image_archive
from tnlab.instances import load_cases
from tnlab.scoring import score_path
from tnlab.execution import run_baseline as run_isolated_baseline

ROOT = Path(__file__).resolve().parent
REQUIRED_RUNS = 5
REQUIRED_ITERATIONS = 15
DEVELOP_SET = "develop_v2.json"
BASELINE_METHODS = {"greedy", "random-greedy", "simulated-annealing"}


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _manifest(path, expected_research_id):
    data = _json(path)
    if not isinstance(data.get("run_ids"), list) or len(data["run_ids"]) != REQUIRED_RUNS:
        raise ValueError("discovery run manifest must contain exactly five run IDs")
    entries = data.get("runs")
    if not isinstance(entries, list) or len(entries) != REQUIRED_RUNS:
        raise ValueError("discovery run manifest must contain exactly five run entries")
    if data.get("research_id") != expected_research_id:
        raise ValueError("discovery run manifest research ID differs from current study")
    if {item.get("run_id") for item in entries} != set(data["run_ids"]):
        raise ValueError("discovery run manifest IDs and entries differ")
    if any(item.get("status") != "completed" or not item.get("directory") for item in entries):
        raise ValueError("discovery run manifest contains incomplete runs")
    if len({item["directory"] for item in entries}) != REQUIRED_RUNS:
        raise ValueError("discovery run manifest contains duplicate directories")
    return data, entries


def _manifest_sha(path):
    return _sha(path)


def _rounds(run):
    path = run / "iteration_journal.jsonl"
    if not path.is_file():
        raise ValueError("iteration journal is missing")
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"iteration journal line {number} is invalid JSON") from exc
    if len(records) != REQUIRED_ITERATIONS:
        raise ValueError(f"expected exactly {REQUIRED_ITERATIONS} journal iterations, got {len(records)}")
    iterations = [item.get("iteration") for item in records]
    if iterations != list(range(1, REQUIRED_ITERATIONS + 1)):
        raise ValueError(f"iteration journal is not continuous: {iterations}")
    return records


def _candidate_path(run, report):
    environment = report.get("environment", {})
    candidate = run / "best_recheck.py"
    if not candidate.is_file():
        raise ValueError("best_recheck.py is missing")
    actual = _sha(candidate)
    expected = environment.get("best_code_sha256")
    if not expected or actual != expected:
        raise ValueError("best candidate hash differs from development report")
    return candidate, actual


def _failure(run, reason):
    return {"run": str(run), "reasons": [reason]}


def _independent_baselines(run):
    baseline_file = run / "development_baselines.json"
    if not baseline_file.is_file():
        raise ValueError("development baselines are missing")
    report = _json(run / "development_report.json")
    expected_hash = report.get("environment", {}).get("development_baselines_sha256")
    if not expected_hash or _sha(baseline_file) != expected_hash:
        raise ValueError("development baselines hash differs from development report")
    baselines = _json(baseline_file)
    cases = {case["name"]: case for case in load_cases(DEVELOP_SET)}
    grouped = {name: {} for name in cases}
    for item in baselines:
        case_name, method = item.get("case"), item.get("method")
        if case_name not in cases or method in grouped[case_name]:
            raise ValueError("development baselines have invalid or duplicate case methods")
        if method not in BASELINE_METHODS:
            raise ValueError("development baselines contain an unknown method")
        score = score_path(cases[case_name], item.get("path"))
        if item.get("cost") != score.cost or item.get("peak_elements") != score.peak_elements:
            raise ValueError("development baseline path score differs from saved metrics")
        grouped[case_name][method] = score.cost
    if any(set(methods) != BASELINE_METHODS for methods in grouped.values()):
        raise ValueError("development baselines do not cover every predefined method")
    rerun = {}
    for case_name, case in cases.items():
        rerun[case_name] = {}
        for method in sorted(BASELINE_METHODS):
            answer, _ = run_isolated_baseline(case, method, 10)
            checked = score_path(case, answer["path"])
            if float(answer["search_seconds"]) > 10:
                raise ValueError("rerun baseline exceeded the search limit")
            rerun[case_name][method] = checked.cost
    if rerun != grouped:
        differences = {
            case_name: {method: (grouped[case_name].get(method), rerun[case_name].get(method))
                        for method in BASELINE_METHODS
                        if grouped[case_name].get(method) != rerun[case_name].get(method)}
            for case_name in grouped
            if any(grouped[case_name].get(method) != rerun[case_name].get(method)
                   for method in BASELINE_METHODS)
        }
        raise ValueError(f"independent baseline rerun differs from saved metrics: {differences}")
    return {case_name: min(methods.values()) for case_name, methods in grouped.items()}


def _independent_development(candidate, run):
    old_set = os.environ.get("TN_DEVELOP_SET")
    try:
        os.environ["TN_DEVELOP_SET"] = DEVELOP_SET
        result = evaluate_set(candidate, DEVELOP_SET)
    finally:
        if old_set is None:
            os.environ.pop("TN_DEVELOP_SET", None)
        else:
            os.environ["TN_DEVELOP_SET"] = old_set
    cases = json.loads(result.artifacts["case_results.json"])
    if result.metrics.get("failure_count"):
        raise ValueError("independent development evaluation has failed cases")
    best_by_case = _independent_baselines(run)
    if {item["case"] for item in cases} != set(best_by_case):
        raise ValueError("development cases and baseline cases differ")
    ratios = [item["cost"] / best_by_case[item["case"]] for item in cases]
    ratio = math.exp(sum(math.log(value) for value in ratios) / len(ratios))
    return {
        "metrics": result.metrics,
        "cases": cases,
        "geometric_ratio_to_best_baseline": ratio,
        "baseline_costs": best_by_case,
    }


def validate_run(run, registration_bytes, expected_research_id, expected_sources,
                 *, allow_completed_final=False):
    """Return independently verified metrics or raise a reason-bearing error."""
    run = Path(run).resolve()
    if not run.is_dir():
        raise ValueError("run directory is missing")
    registration = run / "preregistration.md"
    if not registration.is_file() or registration.read_bytes() != registration_bytes:
        raise ValueError("registration copy is missing or differs from the frozen registration")
    saved_id = run / "research_id.txt"
    if not saved_id.is_file() or saved_id.read_text(encoding="utf-8").strip() != expected_research_id:
        raise ValueError("research ID is missing or differs from the registered study")
    manifest = run / "frozen_source_manifest.json"
    if not manifest.is_file() or _json(manifest) != expected_sources:
        raise ValueError("frozen source manifest is missing or differs from current source")
    report_path = run / "development_report.json"
    if not report_path.is_file():
        raise ValueError("development report is missing")
    report = _json(report_path)
    search = report.get("search", {})
    environment = report.get("environment", {})
    if search.get("research_id") != expected_research_id:
        raise ValueError("development report research ID differs from the registered study")
    saved_initial = run / "initial_program.sha256"
    current_initial = _sha(ROOT / "initial_program.py")
    if not saved_initial.is_file() or saved_initial.read_text(encoding="ascii").strip() != current_initial:
        raise ValueError("initial program hash is missing or differs from current source")
    if environment.get("initial_program_sha256") != current_initial:
        raise ValueError("development report initial program hash is inconsistent")
    if environment.get("iterations_recorded") != REQUIRED_ITERATIONS:
        raise ValueError("development report does not record all 15 iterations")
    if environment.get("develop_set") != DEVELOP_SET:
        raise ValueError("development report uses a different development set")
    benchmark_manifest = ROOT / "data" / "manifest_v2.json"
    expected_manifest_hash = _sha(benchmark_manifest)
    if environment.get("benchmark_manifest_sha256") != expected_manifest_hash:
        raise ValueError("development benchmark manifest differs from the registered data")
    frozen_data = run / "frozen_data"
    for name in ("manifest_v2.json", DEVELOP_SET):
        source = ROOT / "data" / name
        saved = frozen_data / name
        if not saved.is_file() or _sha(saved) != _sha(source):
            raise ValueError(f"frozen development data is missing or changed: {name}")
    image_manifest_path = run / "runner_image_manifest.json"
    report_image_id = environment.get("runner_image_id")
    report_source_hash = environment.get("runner_image_source_sha256")
    if not image_manifest_path.is_file() or not report_image_id or not report_source_hash:
        raise ValueError("runner image identity or archive manifest is missing")
    verify_runner_image_archive(run, report_image_id, report_source_hash)
    if os.environ.get("TN_EXECUTION_MODE") == "container":
        current_image_id = subprocess.run(
            ["docker", "image", "inspect", "tnlab-runner:py313-v1", "--format", "{{.Id}}"],
            check=True, capture_output=True, text=True).stdout.strip()
        if current_image_id != report_image_id:
            raise ValueError("current runner image differs from development report")
    if report.get("final") or report.get("transfer") or (run / "final_report.json").exists():
        if not allow_completed_final or not (run / "final_report.json").is_file():
            raise ValueError("final or transfer evaluation entered the discovery run")
    run_id_path = run / "run_id.txt"
    run_id = run_id_path.read_text(encoding="utf-8").strip() if run_id_path.is_file() else search.get("run_id")
    if not run_id or search.get("run_id") != run_id:
        raise ValueError("run ID is missing or inconsistent")
    ledger = os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB")
    if not ledger:
        raise ValueError("persistent request budget ledger is not configured")
    usage = request_usage(ledger, run_id=run_id)
    recorded = search.get("requests_added_this_run", {})
    if usage != recorded:
        raise ValueError("request attribution differs from the run report")
    rounds = _rounds(run)
    candidate, code_sha = _candidate_path(run, report)
    independent = _independent_development(candidate, run)
    framework = report.get("develop") or {}
    framework_ratio = framework.get("geometric_ratio_to_best_baseline")
    if not isinstance(framework_ratio, (int, float)) or not math.isclose(
            float(framework_ratio), independent["geometric_ratio_to_best_baseline"],
            rel_tol=0, abs_tol=1e-12):
        raise ValueError("framework and independent development ratios differ")
    return {
        "run": str(run),
        "run_id": run_id,
        "candidate_sha256": code_sha,
        "iterations": len(rounds),
        "primary_metric": independent["geometric_ratio_to_best_baseline"],
        "independent_development": independent,
        "request_usage": search.get("requests_added_this_run", {}),
        "evidence_sha256": hashlib.sha256(json.dumps({
            "report": _sha(run / "development_report.json"),
            "candidate": code_sha,
            "baselines": _sha(run / "development_baselines.json"),
            "source_manifest": _sha(run / "frozen_source_manifest.json"),
            "runner_image": _sha(run / "runner_image_manifest.json"),
        }, sort_keys=True).encode("utf-8")).hexdigest(),
    }


def _selection_projection(item):
    return {key: item.get(key) for key in (
        "run", "run_id", "candidate_sha256", "primary_metric",
        "request_usage", "evidence_sha256")}


def verify_selection_record(selection_path, registration_path=None, research_id=None,
                            *, allow_completed_final=False):
    """Re-verify every run and the deterministic ranking behind a saved selection."""
    selection_path = Path(selection_path)
    selection = _json(selection_path)
    registration_path = Path(registration_path or ROOT / "notes" / "formal_registration_2026-10.md")
    registration_bytes = registration_path.read_bytes()
    research_id = research_id or os.environ.get("TN_RESEARCH_ID", "tensor-path-discovery-2026-10")
    expected_sources = frozen_file_hashes()
    manifest_path = selection_path.parent / "discovery_run_manifest.json"
    manifest, entries = _manifest(manifest_path, research_id)
    if selection.get("run_manifest_sha256") != _sha(
            selection_path.parent / "discovery_run_manifest.json"):
        raise ValueError("selection run manifest hash differs")
    if selection.get("registration_sha256") != hashlib.sha256(registration_bytes).hexdigest():
        raise ValueError("selection registration hash differs")
    verified = [validate_run(Path(item["directory"]), registration_bytes,
                             research_id, expected_sources,
                             allow_completed_final=allow_completed_final)
                for item in entries]
    verified.sort(key=lambda item: (item["primary_metric"], item["candidate_sha256"]))
    if selection.get("status") != "selected" or len(verified) != REQUIRED_RUNS:
        raise ValueError("selection record is not a complete selected study")
    if [_selection_projection(item) for item in selection.get("eligible_runs", [])] != [
            _selection_projection(item) for item in verified]:
        raise ValueError("selection eligible-run evidence differs after revalidation")
    if _selection_projection(selection.get("selected") or {}) != _selection_projection(verified[0]):
        raise ValueError("selection winner differs after revalidation")
    return selection


def select_discovery(runs, output, registration_path=None, research_id=None,
                     run_manifest_path=None):
    """Verify all supplied runs and select the deterministic best eligible run."""
    runs = list(runs)
    output = Path(output)
    registration_path = Path(registration_path or ROOT / "notes" / "formal_registration_2026-10.md")
    registration_bytes = registration_path.read_bytes()
    research_id = research_id or os.environ.get("TN_RESEARCH_ID", "tensor-path-discovery-2026-10")
    expected_sources = frozen_file_hashes()
    if run_manifest_path is None:
        raise ValueError("discovery run manifest is required")
    manifest_path = Path(run_manifest_path)
    manifest, entries = _manifest(manifest_path, research_id)
    runs = [Path(item["directory"]) for item in entries]
    if manifest.get("registration_sha256") != hashlib.sha256(registration_bytes).hexdigest():
        raise ValueError("discovery run manifest registration hash differs")
    verified = []
    rejected = []
    for run in sorted((Path(item) for item in runs), key=lambda path: str(path)):
        try:
            verified.append(validate_run(run, registration_bytes, research_id, expected_sources))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            rejected.append(_failure(run.resolve(), str(exc)))
    verified.sort(key=lambda item: (item["primary_metric"], item["candidate_sha256"]))
    unique = []
    seen_ids = set()
    for item in verified:
        if item["run_id"] in seen_ids:
            rejected.append(_failure(item["run"], "duplicate run ID is not an independent discovery run"))
        else:
            seen_ids.add(item["run_id"])
            unique.append(item)
    verified = unique
    supplied_count = len(runs)
    eligible = supplied_count == REQUIRED_RUNS and len(verified) == REQUIRED_RUNS
    selected = verified[0] if eligible else None
    result = {
        "status": "selected" if selected else "inconclusive",
        "required_runs": REQUIRED_RUNS,
        "eligible_run_count": len(verified),
        "supplied_run_count": supplied_count,
        "eligible_runs": verified,
        "rejected_runs": rejected,
        "selected": selected,
        "selection_rule": "minimum development geometric ratio to strongest predefined baseline; candidate SHA-256 tie-break",
        "research_id": research_id,
        "registration_sha256": hashlib.sha256(registration_bytes).hexdigest(),
        "run_manifest_sha256": _manifest_sha(manifest_path),
        "run_manifest_path": manifest_path.name,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = output.with_suffix(".md")
    lines = ["# Discovery Selection", "", f"Status: **{result['status']}**", "",
             f"Eligible runs: {len(verified)}/{REQUIRED_RUNS}", "",
             "## Eligible Runs", ""]
    for item in verified:
        lines.append(f"- `{item['run_id']}`: ratio `{item['primary_metric']:.12g}`, candidate `{item['candidate_sha256']}`")
    lines.extend(["", "## Rejected Runs", ""])
    for item in rejected:
        lines.append(f"- `{item['run']}`: " + "; ".join(item["reasons"]))
    if selected:
        lines.extend(["", "## Selected", "", f"- Run: `{selected['run_id']}`",
                      f"- Candidate: `{selected['candidate_sha256']}`",
                      f"- Development ratio: `{selected['primary_metric']:.12g}`"])
    else:
        lines.extend(["", f"No candidate was selected because exactly five eligible runs are required (got {len(verified)} eligible from {supplied_count} supplied)."])
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "discovery_selection.json")
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--research-id")
    args = parser.parse_args()
    result = select_discovery([], args.output, args.registration, args.research_id,
                              args.run_manifest)
    print(json.dumps({key: result[key] for key in ("status", "eligible_run_count", "selected")},
                     ensure_ascii=False, indent=2))
    if result["status"] != "selected":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
