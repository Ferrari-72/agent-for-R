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

ROOT = Path(__file__).resolve().parent


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate_frozen_sets(run_dir, program, set_names):
    """Resume only missing cases after an interrupted one-time final run."""
    progress = run_dir / "final_progress.jsonl"
    saved = []
    if progress.exists():
        saved = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()
                 if line.strip()]
    expected = [(name, case) for name in set_names for case in load_cases(name)]
    if len(saved) > len(expected):
        raise RuntimeError("final progress contains more cases than the frozen benchmark")
    for item, (name, case) in zip(saved, expected):
        if item.get("set") != name or item.get("result", {}).get("case") != case["name"]:
            raise RuntimeError("final progress does not match frozen case order")
    for name, case in expected[len(saved):]:
        record = {"set": name, "result": compare_case(program, case)}
        with progress.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        saved.append(record)
    return {name: {"cases": [item["result"] for item in saved if item["set"] == name],
                   "summary": summarize([item["result"] for item in saved
                                         if item["set"] == name])}
            for name in set_names}


def research_summary(development, final_report):
    final = final_report["results"]["final_v2.json"]["summary"]
    transfer = final_report["results"]["transfer_v2.json"]["summary"]
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
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    program = run_dir / "best_recheck.py"
    development = run_dir / "development_report.json"
    if not program.is_file() or not development.is_file():
        parser.error("frozen program and development report are required")
    previous = json.loads(development.read_text(encoding="utf-8"))
    if _sha(program) != previous["environment"]["best_code_sha256"]:
        parser.error("best program differs from the development report")
    if frozen_file_hashes() != previous["environment"].get("frozen_file_hashes"):
        parser.error("evaluation rules or runner code changed since development freeze")
    if os.environ.get("TN_EXECUTION_MODE") != "container":
        parser.error("final evaluation requires TN_EXECUTION_MODE=container")
    subprocess.run(["docker", "info"], check=True, capture_output=True)
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
    if _sha(ROOT / "data" / "manifest_v2.json") != previous["environment"].get(
            "benchmark_manifest_sha256"):
        parser.error("benchmark manifest differs from development freeze")
    if previous["environment"].get("iterations_recorded", 0) < 5:
        parser.error("at least five real-model iterations are required before final evaluation")
    manifest = json.loads((ROOT / "data" / "manifest_v2.json").read_text(encoding="utf-8"))
    for name, entry in manifest.items():
        if _sha(ROOT / "data" / name) != entry["sha256"]:
            parser.error(f"benchmark changed: {name}")
    frozen_data = run_dir / "frozen_data"
    frozen_data.mkdir(exist_ok=True)
    for name in ("manifest_v2.json", "final_v2.json", "transfer_v2.json"):
        source = ROOT / "data" / name
        destination = frozen_data / name
        if destination.exists():
            if _sha(destination) != _sha(source):
                parser.error(f"saved benchmark copy changed: {name}")
        else:
            destination.write_bytes(source.read_bytes())
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
        run_dir, program, ("final_v2.json", "transfer_v2.json"))
    report = {"program_sha256": _sha(program), "benchmark_manifest": manifest,
              "results": results,
              "scope": "one frozen discovery run; request accounting is in development_report.json"}
    with (run_dir / "final_report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    (run_dir / "research_report.md").write_text(
        research_summary(previous, report), encoding="utf-8")
    print(run_dir / "final_report.json")


if __name__ == "__main__":
    main()
