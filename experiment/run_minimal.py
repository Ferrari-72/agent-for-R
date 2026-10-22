"""Verify the initial solution, then run one OpenEvolve generation."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from openevolve.api import run_evolution
from openevolve.config import load_config

from openevolve_evaluator import evaluate, evaluate_set
from tnlab.baselines import run_baseline
from tnlab.instances import load_cases

ROOT = Path(__file__).resolve().parent


def write_report(result, output, iterations_requested=None):
    trace = output / "evolution_trace.jsonl"
    if not trace.exists() or not trace.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"模型未生成可记录的候选；查看日志：{output / 'logs'}")
    if result.best_program is None:
        raise RuntimeError("框架没有返回有效程序")
    print("输出目录：", output)
    print("框架最佳分数：", result.best_score)
    if result.best_program is not None:
        best_file = output / "best_recheck.py"
        best_file.write_text(result.best_code, encoding="utf-8")
        checked = evaluate(best_file)
        print("独立复核：", json.dumps(checked.metrics, ensure_ascii=False))
        if abs(checked.metrics["combined_score"] - result.best_score) > 1e-9:
            raise RuntimeError("框架最佳分数与独立复核不一致")
        holdout = evaluate_set(best_file, "holdout.json")
        baselines = {
            name: [run_baseline(case, method)
                   for case in load_cases(name)
                   for method in ("greedy", "random-greedy", "simulated-annealing")]
            for name in ("develop.json", "holdout.json")
        }
        report = {"develop": {"metrics": checked.metrics,
                               "cases": json.loads(checked.artifacts["case_results.json"])},
                  "holdout": {"metrics": holdout.metrics,
                              "cases": json.loads(holdout.artifacts["case_results.json"])},
                  "baselines": baselines,
                  "environment": {
                      "python": sys.version,
                      "versions": {name: version(name) for name in
                                   ("cotengra", "opt_einsum", "quimb", "openevolve")},
                      "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
                      "config_sha256": sha256((ROOT / "config.yaml").read_bytes()).hexdigest(),
                      "best_code_sha256": sha256(result.best_code.encode("utf-8")).hexdigest(),
                      "model": os.environ.get("TN_MODEL", "deepseek-ai/DeepSeek-V3.2"),
                      "iterations_requested": iterations_requested,
                      "iterations_recorded": len(trace.read_text(encoding="utf-8").splitlines()),
                  }}
        (output / "final_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("保留集：", json.dumps(holdout.metrics, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=3)
    args = parser.parse_args()
    if args.iterations < 1 or args.iterations > 20:
        parser.error("iterations must be between 1 and 20")
    initial = ROOT / "initial_program.py"
    before = evaluate(initial)
    print("初始程序：", json.dumps(before.metrics, ensure_ascii=False))
    if before.metrics["failure_count"]:
        raise RuntimeError("初始程序未通过评估")
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("缺少 OPENAI_API_KEY；请运行 run.ps1 输入 SiliconFlow 密钥")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    output = ROOT / "results" / f"evolve_{stamp}"
    config = load_config(ROOT / "config.yaml")
    selected_model = os.environ.get("TN_MODEL")
    if selected_model:
        for model in config.llm.models:
            model.name = selected_model
        for model in config.llm.evaluator_models:
            model.name = selected_model
    result = run_evolution(initial, ROOT / "openevolve_evaluator.py",
                           config=config, iterations=args.iterations,
                           output_dir=str(output), cleanup=False)
    write_report(result, output, args.iterations)


if __name__ == "__main__":
    main()
