"""Run the bounded, machine-checkable pre-discovery calibration request."""

import argparse
import ast
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from openai import OpenAI
from openevolve.utils.code_utils import apply_diff_blocks, extract_diffs
from openevolve.utils.request_budget import reserve_request

from openevolve_evaluator import PREFLIGHT_CASE, evaluate_case

ROOT = Path(__file__).resolve().parent
BASE_URL = os.environ.get("TN_API_BASE", "https://api.siliconflow.cn/v1")
CALIBRATION_PROMPT = """Return exactly one complete SEARCH/REPLACE diff block and nothing else.
The block must make a small deterministic improvement to the provided tensor-network
path search program. Preserve the exact public signature
find_path(inputs, output, sizes, seed=0). It must return exactly len(inputs)-1 legal
current-list-position pairs, and must keep a valid deterministic fallback. The candidate will be checked on one fixed, machine-checkable control case during calibration.
Calibration passes only when the candidate cost is strictly lower than the initial
program cost on that control case; equal cost or regression fails calibration.
Start with <<<<<<< SEARCH and end with >>>>>>> REPLACE.

Current program:
"""


def _check_interface(path):
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    function = next((node for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef)
                     and node.name == "find_path"), None)
    if function is None or len(function.args.args) != 4:
        return False, "find_path signature is not preserved"
    if function.args.vararg or function.args.kwarg or function.args.kwonlyargs:
        return False, "find_path must use exactly four ordinary positional arguments"
    if [arg.arg for arg in function.args.args] != ["inputs", "output", "sizes", "seed"]:
        return False, "find_path argument names changed"
    if len(function.args.defaults) != 1 or function.args.defaults[0].__class__ is not ast.Constant:
        return False, "find_path seed default is missing"
    if function.args.defaults[0].value != 0 or type(function.args.defaults[0].value) is not int:
        return False, "find_path seed default must be 0"
    return True, "signature preserved"


def _check_controlled_improvement(initial_result, candidate_result):
    """Require a valid candidate whose fixed-control cost is strictly lower."""
    if "error" in initial_result:
        return False, "initial program failed the fixed control task"
    if "error" in candidate_result:
        return False, "candidate failed the fixed control task"
    initial_cost = initial_result.get("cost")
    candidate_cost = candidate_result.get("cost")
    if not isinstance(initial_cost, (int, float)) or not isinstance(candidate_cost, (int, float)):
        return False, "fixed control task did not return numeric costs"
    if candidate_cost >= initial_cost:
        return False, "candidate cost is not strictly lower than initial cost"
    return True, "candidate cost is strictly lower than initial cost"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is missing")
    output = args.output or ROOT / "results" / (
        "calibration_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_" + uuid4().hex[:6]
    )
    output.mkdir(parents=True, exist_ok=False)
    initial = ROOT / "initial_program.py"
    initial_code = initial.read_text(encoding="utf-8")
    prompt = CALIBRATION_PROMPT + initial_code
    (output / "prompt.txt").write_text(prompt, encoding="utf-8")
    client = OpenAI(api_key=key, base_url=BASE_URL,
                    timeout=75.0, max_retries=0)
    reserve_request("calibration_completion", run_id=os.environ.get("TN_RUN_ID"))
    try:
        response = client.chat.completions.create(
            model=args.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            stream=False,
            extra_body={"enable_thinking": False},
        )
        text = response.choices[0].message.content if response.choices else ""
    except Exception as exc:
        result = {"model": args.model, "request_id": os.environ.get("TN_RUN_ID"),
                  "status": "failed", "stage": "request",
                  "error": f"{type(exc).__name__}: {exc}",
                  "prompt_sha256": sha256(prompt.encode()).hexdigest()}
        (output / "calibration_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"Calibration request failed; evidence saved at {output}") from exc
    (output / "response.txt").write_text(text or "", encoding="utf-8")
    result = {"model": args.model,
              "request_id": os.environ.get("TN_RUN_ID"),
              "response_sha256": sha256((text or "").encode()).hexdigest(),
              "checks": {
                  "single_diff_block": {"status": "pending"},
                  "interface_contract": {"status": "pending"},
                  "legal_deterministic_path": {"status": "pending"},
                  "controlled_improvement": {"status": "pending"},
              }}
    try:
        blocks = extract_diffs(text or "")
        if len(blocks) != 1:
            raise ValueError(f"expected one diff block, got {len(blocks)}")
        result["checks"]["single_diff_block"] = {"status": "passed", "count": len(blocks)}
        child_code, applied = apply_diff_blocks(initial_code, blocks)
        if applied != 1 or child_code == initial_code:
            raise ValueError("diff did not make exactly one applied change")
        candidate = output / "candidate.py"
        candidate.write_text(child_code, encoding="utf-8")
        interface_ok, interface_message = _check_interface(candidate)
        result["checks"]["interface_contract"] = {
            "status": "passed" if interface_ok else "failed", "detail": interface_message}
        if not interface_ok:
            raise ValueError(interface_message)
        initial_result = evaluate_case(initial, PREFLIGHT_CASE)
        candidate_result = evaluate_case(candidate, PREFLIGHT_CASE)
        if "error" in candidate_result:
            result["checks"]["legal_deterministic_path"] = {
                "status": "failed", "result": candidate_result}
            raise ValueError("calibration candidate failed the fixed legality task")
        result["checks"]["legal_deterministic_path"] = {
            "status": "passed", "result": candidate_result}
        improved, improvement_message = _check_controlled_improvement(
            initial_result, candidate_result)
        result["checks"]["controlled_improvement"] = {
            "status": "passed" if improved else "failed",
            "message": improvement_message,
            "initial": initial_result, "candidate": candidate_result}
        if not improved:
            raise ValueError(improvement_message)
        result.update({"status": "passed", "diff_blocks": 1, "applied_blocks": applied,
                       "interface": interface_message,
                       "candidate_metrics": candidate_result})
    except Exception as exc:
        result.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
        (output / "calibration_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise RuntimeError(f"Calibration failed; evidence saved at {output}") from exc
    (output / "calibration_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
