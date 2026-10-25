"""One-time evaluation of a frozen run on untouched benchmark sets."""

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

from tnlab.comparison import compare_case, summarize
from tnlab.freeze import frozen_file_hashes, image_source_hash, verify_runner_image_archive
from tnlab.instances import load_cases
from select_discovery import verify_selection_record

ROOT = Path(__file__).resolve().parent


def _stable(value):
    """Drop timing-only fields before hashing independently checked evidence."""
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in sorted(value.items())
                if key not in {"wall_seconds", "search_seconds", "function_seconds_untrusted"}}
    if isinstance(value, (list, tuple)):
        return [_stable(item) for item in value]
    return value


def _evidence_sha256(result):
    encoded = json.dumps(_stable(result), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rules_sha256():
    hashes = frozen_file_hashes()
    encoded = json.dumps(hashes, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_frozen_sets(run_dir, program, set_names, candidate_sha256=None,
                         rules_sha256=None):
    """Resume only missing cases after independently checking saved evidence."""
    candidate_sha256 = candidate_sha256 or _sha(program)
    rules_sha256 = rules_sha256 or _rules_sha256()
    progress = run_dir / "final_progress.jsonl"
    saved = []
    if progress.exists():
        saved = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    expected = [(name, case) for name in set_names for case in load_cases(name)]
    if len(saved) > len(expected):
        raise RuntimeError("final progress contains more cases than the frozen benchmark")
    for index, (item, (name, case)) in enumerate(zip(saved, expected)):
        result = item.get("result") or {}
        if (item.get("set") != name or item.get("case_sha256") != _evidence_sha256(case)
                or result.get("case") != case["name"]
                or item.get("candidate_sha256") != candidate_sha256
                or item.get("rules_sha256") != rules_sha256
                or item.get("result_sha256") != _evidence_sha256(result)):
            raise RuntimeError(f"final progress evidence is invalid at case {index + 1}")
        checked = compare_case(program, case)
        if _stable(checked) != _stable(result):
            raise RuntimeError(f"saved final result differs on independent recheck at case {index + 1}")
    for name, case in expected[len(saved):]:
        result = compare_case(program, case)
        record = {"set": name, "case_sha256": _evidence_sha256(case),
                  "candidate_sha256": candidate_sha256, "rules_sha256": rules_sha256,
                  "result_sha256": _evidence_sha256(result), "result": result}
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        saved.append(record)
    return {name: {"cases": [item["result"] for item in saved if item["set"] == name],
                   "summary": summarize([item["result"] for item in saved
                                         if item["set"] == name])}
            for name in set_names}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def research_summary(development, final_report, final_name="final_v3.json",
                     transfer_name="transfer_v3.json"):
    final = final_report["results"][final_name]["summary"]
    transfer = final_report["results"][transfer_name]["summary"]
    ratio = final["geometric_ratio_to_best_baseline"]
    if ratio is None:
        finding = "部分候选试验失败；不能计算覆盖全部最终例的几何平均比值。"
    elif ratio < 1:
        finding = f"在本次最终电路集上，候选的几何平均代价比为 {ratio:.4f}，低于逐例最优预设基线。"
    else:
        finding = f"在本次最终电路集上，候选的几何平均代价比为 {ratio:.4f}，未优于逐例最优预设基线。"
    usage = development.get("search", {})
    added = usage.get("requests_added_this_run")
    added_count = added.get("total", "未知") if isinstance(added, dict) else "未知"
    attribution = ("本次请求起点已记录。" if added is not None else
                   "旧运行没有记录请求起点；不能从累计值反推本次新增请求。")
    cumulative = usage.get("budget_db_cumulative_count", usage.get(
        "http_requests_budget_total", usage.get("http_requests", {})).get("total", "未知"))
    request_limit = usage.get("request_limit", "未记录")
    return "\n".join([
        "# 张量网络收缩顺序研究报告", "", "## 事实", "",
        f"- 模型 HTTP 请求：本次新增 {added_count} 次；"
        f"预算库累计 {cumulative} 次；本次运行上限 {request_limit}。"
        f"累计值不等于本次运行消耗。{attribution}",
        f"候选尝试：{usage.get('candidate_attempts', '未知')} 次；"
        f"有效候选率：{usage.get('valid_candidate_rate', '未知')}。",
        f"- 最终电路试验：{final['valid_trials']}/{final['trials']} 次有效；"
        f"失败率：{final['failure_rate']:.4f}。",
        f"- 格点迁移试验：{transfer['valid_trials']}/{transfer['trials']} 次有效；"
        f"失败率：{transfer['failure_rate']:.4f}。", "",
        "## 推断", "", finding, "",
        "## 局限", "",
        "结论仅适用于保存的实例、候选代码、模型、种子和环境；请求预算与实际运行记录见本报告事实和开发报告。",
        "若旧运行没有保存镜像归档或运行前请求位置，不得声称其运行时间可完整复现或请求增量已精确归因。",
        "本实验没有证明 Agent 一般能或不能解决张量网络收缩顺序问题。",
        "逐例路径、代价、峰值、时间及基线见 final_report.json；开发过程见 iteration_journal.jsonl。",
        "",
    ])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--final-set", default=os.environ.get("TN_FINAL_SET", "final_v3.json"))
    parser.add_argument("--transfer-set", default=os.environ.get(
        "TN_TRANSFER_SET", "transfer_v3.json"))
    args = parser.parse_args()
    if args.final_set == "final_v2.json" or args.transfer_set == "transfer_v2.json":
        parser.error("the viewed v2 sets are historical and cannot serve as new held-out data")
    run_dir = args.run_dir.resolve()
    program = run_dir / "best_recheck.py"
    development = run_dir / "development_report.json"
    if not program.is_file() or not development.is_file():
        parser.error("frozen program and development report are required")
    previous = json.loads(development.read_text(encoding="utf-8"))
    if _sha(program) != previous["environment"]["best_code_sha256"]:
        parser.error("best program differs from the development report")
    selection_path = Path(os.environ.get(
        "TN_DISCOVERY_SELECTION", ROOT / "results" / "discovery_selection.json"))
    if not selection_path.is_file():
        parser.error("verified discovery selection record is required before final evaluation")
    selection = verify_selection_record(
        selection_path, research_id=previous.get("search", {}).get("research_id"))
    selected = selection.get("selected") or {}
    if selection.get("status") != "selected" or selected.get("run") != str(run_dir):
        parser.error("this run was not selected by the verified discovery selection")
    if selected.get("candidate_sha256") != _sha(program):
        parser.error("selected candidate hash differs from the frozen program")
    if selected.get("run_id") != previous.get("search", {}).get("run_id"):
        parser.error("selected run ID differs from the development report")
    if selection.get("research_id") != previous.get("search", {}).get("research_id"):
        parser.error("selection research ID differs from the development report")
    if frozen_file_hashes() != previous["environment"].get("frozen_file_hashes"):
        parser.error("evaluation rules or runner code changed since development freeze")
    fake_drill = os.environ.get("TN_FAKE_DRILL") == "1"
    if fake_drill and not previous.get("search", {}).get("research_id", "").startswith(
            "tensor-path-discovery-fake-drill-"):
        parser.error("TN_FAKE_DRILL is restricted to the fake drill research ID")
    if not fake_drill and os.environ.get("TN_EXECUTION_MODE") != "container":
        parser.error("final evaluation requires TN_EXECUTION_MODE=container")
    if not fake_drill:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
    if not fake_drill:
        image_id = subprocess.run(
            ["docker", "image", "inspect", "tnlab-runner:py313-v1", "--format", "{{.Id}}"],
            check=True, capture_output=True, text=True).stdout.strip()
        if image_id != previous["environment"].get("runner_image_id"):
            parser.error("candidate runner image differs from development freeze")
        try:
            verify_runner_image_archive(
                run_dir, image_id, previous["environment"].get("runner_image_source_sha256")
            )
        except (OSError, ValueError, KeyError) as error:
            parser.error(str(error))
        if image_source_hash() != previous["environment"].get("runner_image_source_sha256"):
            parser.error("runner source differs from development freeze")
    manifest_path = ROOT / "data" / "manifest_v3.json"
    frozen_data = run_dir / "frozen_data"
    frozen_manifest = frozen_data / "manifest_v3.json"
    if not frozen_manifest.is_file() or _sha(frozen_manifest) != _sha(manifest_path):
        parser.error("run is missing the matching frozen held-out benchmark manifest")
    manifest = json.loads(frozen_manifest.read_text(encoding="utf-8"))
    for name in (args.final_set, args.transfer_set):
        entry = manifest.get(name)
        frozen_set = frozen_data / name
        if (not entry or not frozen_set.is_file()
                or _sha(frozen_set) != entry["sha256"]
                or _sha(ROOT / "data" / name) != entry["sha256"]):
            parser.error(f"held-out benchmark is missing or changed: {name}")
    if previous["environment"].get("heldout_manifest_sha256") != _sha(frozen_manifest):
        parser.error("development report held-out manifest differs from the run's frozen copy")
    if previous["environment"].get("iterations_recorded", 0) < 15:
        parser.error("all 15 real-model iterations are required before final evaluation")
    marker = run_dir / "final_evaluation.started"
    if (run_dir / "final_report.json").exists():
        parser.error("final evaluation has already completed")
    if marker.exists():
        if marker.read_text(encoding="utf-8").strip() != _sha(program):
            parser.error("final evaluation marker has a different program hash")
    else:
        with marker.open("x", encoding="utf-8") as stream:
            stream.write(_sha(program) + "\n")
    results = evaluate_frozen_sets(
        run_dir, program, (args.final_set, args.transfer_set),
        candidate_sha256=_sha(program), rules_sha256=_rules_sha256())
    report = {"program_sha256": _sha(program), "benchmark_manifest": manifest,
              "results": results,
              "scope": "one frozen discovery run; request accounting is in development_report.json"}
    with (run_dir / "final_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    (run_dir / "research_report.md").write_text(
        research_summary(previous, report, args.final_set, args.transfer_set), encoding="utf-8")
    print(run_dir / "final_report.json")


if __name__ == "__main__":
    main()
