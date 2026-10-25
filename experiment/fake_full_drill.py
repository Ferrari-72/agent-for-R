"""Run a complete local fake-provider study drill without real model traffic.

This script creates an isolated request ledger and a local OpenAI-compatible
server. It exercises probe, one-shot calibration, five fixed discovery runs,
checkpoint/resume, deterministic selection, and the final admission gate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

from openevolve.utils.request_budget import initialize_request_budget, request_usage

from tnlab.prompt_policy import prompt_policy_manifest, prompt_policy_sha256
from tnlab.freeze import frozen_file_hashes
from select_discovery import verify_selection_record
from hashlib import sha256

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MODEL = "deepseek-ai/DeepSeek-V3.2"
RESEARCH_ID = "tensor-path-discovery-fake-drill-2026-10"

CALIBRATION_DIFF = """<<<<<<< SEARCH
    return [tuple(pair) for pair in oe.paths.greedy(
        [set(tensor) for tensor in inputs], set(output), sizes
    )]
=======
    if len(inputs) == 3 and output == ['a', 'd']:
        return [(0, 1), (0, 1)]
    return [tuple(pair) for pair in oe.paths.greedy(
        [set(tensor) for tensor in inputs], set(output), sizes
    )]
>>>>>>> REPLACE"""

DISCOVERY_DIFF = """<<<<<<< SEARCH
    \"\"\"Return exactly len(inputs) - 1 pairs of current tensor positions.\"\"\"
=======
    \"\"\"Return exactly len(inputs) - 1 deterministic position pairs.\"\"\"
>>>>>>> REPLACE"""


class FakeProvider(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") != "/v1/models":
            self.send_error(404)
            return
        self.server.events.append({"kind": "model_list"})
        self._json({"object": "list", "data": [{"id": MODEL, "object": "model"}]})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        user = "\n".join(str(item.get("content", "")) for item in payload.get("messages", []))
        if "Calibration passes only" in user:
            content = CALIBRATION_DIFF
            kind = "calibration_completion"
        else:
            content = DISCOVERY_DIFF
            kind = "chat_completion"
        self.server.events.append({"kind": kind, "model": payload.get("model"),
                                   "prompt": user})
        self._json({
            "id": f"fake-{len(self.server.events)}",
            "object": "chat.completion",
            "created": 0,
            "model": MODEL,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 31, "total_tokens": 48},
        })

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def _run(command, env, *, timeout=None):
    return subprocess.run(command, cwd=ROOT, env=env, text=True,
                          encoding="utf-8", errors="replace",
                          capture_output=True, timeout=timeout, check=True)


def _run_dir(run_id):
    matches = []
    for path in RESULTS.glob("evolve_*"):
        if (path / "run_id.txt").is_file() and (path / "run_id.txt").read_text().strip() == run_id:
            matches.append(path)
    if len(matches) != 1:
        raise RuntimeError(f"expected one directory for {run_id}, found {matches}")
    return matches[0]


def _base_env(ledger, api_base):
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONHASHSEED": "0",
        "TN_DEVELOP_SET": "develop_v2.json",
        "TN_RESEARCH_ID": RESEARCH_ID,
        "TN_MODEL": MODEL,
        "TN_API_BASE": api_base,
        "OPENAI_API_KEY": "fake-provider-key-not-a-secret",
        "TN_FAKE_DRILL": "1",
        "OPENEVOLVE_REQUEST_BUDGET_DB": str(ledger),
        "OPENEVOLVE_REQUEST_LIMIT": "100",
        "TN_EXECUTION_MODE": "local",
    })
    return env


def _wait_for_checkpoint(run_id, minimum=2, timeout=240):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        try:
            path = _run_dir(run_id)
        except RuntimeError:
            time.sleep(0.5)
            continue
        checkpoints = [
            int(item.name.removeprefix("checkpoint_"))
            for item in (path / "checkpoints").glob("checkpoint_*")
            if item.is_dir() and item.name.removeprefix("checkpoint_").isdigit()
        ]
        if max(checkpoints, default=0) >= minimum:
            return path
        time.sleep(0.5)
    raise TimeoutError(f"checkpoint {minimum} not created for {run_id}")


def _fake_runner_evidence(run_path):
    archive = run_path / "runner-image.tar"
    archive.write_bytes(b"fake-drill-runner-image-v1")
    archive_hash = sha256(archive.read_bytes()).hexdigest()
    source_hash = sha256(b"fake-drill-runner-source-v1").hexdigest()
    manifest = {"image_id": "fake-drill-image-v1", "source_sha256": source_hash,
                "requirements_sha256": sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
                "archive": archive.name, "archive_sha256": archive_hash}
    (run_path / "runner_image_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-server-log", action="store_true")
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6]
    drill = RESULTS / f"fake_full_drill_{stamp}"
    drill.mkdir(parents=True, exist_ok=False)
    ledger = drill / "request_budget.sqlite3"
    initialize_request_budget(ledger, RESEARCH_ID, 100)
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    server.events = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    api_base = f"http://127.0.0.1:{server.server_port}/v1"
    env = _base_env(ledger, api_base)
    run_ids = [str(uuid4()) for _ in range(5)]
    calibration_id = "calibration-" + str(uuid4())
    manifest = {
        "research_id": RESEARCH_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "registration_sha256": sha256((ROOT / "notes" / "formal_registration_2026-10.md").read_bytes()).hexdigest(),
        "frozen_source_hashes": frozen_file_hashes(),
        "model": MODEL,
        "calibration_run_id": calibration_id,
        "calibration_status": "pending",
        "run_ids": run_ids,
        "runs": [{"run_id": run_id, "status": "pending"} for run_id in run_ids],
        "prompt_policy": prompt_policy_manifest(),
        "prompt_policy_sha256": prompt_policy_sha256(),
        "ledger": ledger.name,
    }
    manifest_path = drill / "discovery_run_manifest.json"
    try:
        env["TN_RUN_ID"] = calibration_id
        env["TN_EXECUTION_MODE"] = "local"
        _run([sys.executable, "probe_api.py"], env, timeout=60)
        _run([sys.executable, "calibrate_api.py", "--model", MODEL,
              "--output", str(drill / "calibration")], env, timeout=120)
        manifest["calibration_status"] = "completed"
        manifest["calibration_directory"] = "calibration"

        for index, run_id in enumerate(run_ids):
            env = _base_env(ledger, api_base)
            env["TN_RUN_ID"] = run_id
            command = [sys.executable, "run_experiment.py", "--iterations", "15"]
            if index == 0:
                interrupted_output = drill / "interrupted_run_output.txt"
                with interrupted_output.open("w", encoding="utf-8") as stream:
                    process = subprocess.Popen(command, cwd=ROOT, env=env,
                                               text=True, stdout=stream,
                                               stderr=subprocess.STDOUT)
                    run_path = _wait_for_checkpoint(run_id, minimum=2)
                    process.terminate()
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            check=False, capture_output=True, text=True,
                        )
                        process.wait(timeout=30)
                output = interrupted_output.read_text(encoding="utf-8")
                manifest["interrupted_run"] = {"run_id": run_id,
                                                "checkpoint": str(run_path / "checkpoints" / "checkpoint_2")}
                env = _base_env(ledger, api_base)
                env["TN_RUN_ID"] = run_id
                _run([sys.executable, "run_experiment.py", "--iterations", "15",
                      "--resume-run", str(run_path)], env, timeout=1800)
            else:
                _run(command, env, timeout=1800)
            path = _run_dir(run_id)
            _fake_runner_evidence(path)
            report = json.loads((path / "development_report.json").read_text(encoding="utf-8"))
            report["environment"]["runner_image_id"] = "fake-drill-image-v1"
            report["environment"]["runner_image_source_sha256"] = sha256(
                b"fake-drill-runner-source-v1").hexdigest()
            (path / "development_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            manifest["runs"][index] = {"run_id": run_id, "status": "completed",
                                       "directory": str(path.resolve())}
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        selection_path = drill / "discovery_selection.json"
        env = _base_env(ledger, api_base)
        env["TN_RUN_ID"] = "selection"
        _run([sys.executable, "select_discovery.py", "--run-manifest", str(manifest_path),
              "--output", str(selection_path)], env, timeout=3600)

        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selected = selection["selected"]
        summary = {"selection": str(selection_path.resolve()),
                   "selected_run": selected["run"],
                   "selected_run_id": selected["run_id"]}
        (drill / "drill_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        env["TN_FAKE_DRILL"] = "1"
        env["TN_EXECUTION_MODE"] = "local"
        env["TN_RUN_ID"] = selected["run_id"]
        env["TN_DISCOVERY_SELECTION"] = str(selection_path.resolve())
        if not selection_path.is_file() or selection_path.parent != drill:
            raise RuntimeError("fake drill selection path is outside the drill directory")
        manifest_sha256 = sha256(manifest_path.read_bytes()).hexdigest()
        selection_sha256_before = sha256(selection_path.read_bytes()).hexdigest()
        _run([sys.executable, "final_evaluation.py", selected["run"],
              "--final-set", "final_v3.json", "--transfer-set", "transfer_v3.json"],
              env, timeout=3600)
        final_report = Path(selected["run"]) / "final_report.json"
        if not final_report.is_file():
            raise RuntimeError("final evaluation did not produce final_report.json")
        selection_sha256_after = sha256(selection_path.read_bytes()).hexdigest()
        if selection_sha256_after != selection_sha256_before:
            raise RuntimeError("selection record changed during final evaluation")
        previous_ledger = os.environ.get("OPENEVOLVE_REQUEST_BUDGET_DB")
        previous_mode = os.environ.get("TN_EXECUTION_MODE")
        os.environ["OPENEVOLVE_REQUEST_BUDGET_DB"] = str(ledger)
        os.environ["TN_EXECUTION_MODE"] = "local"
        try:
            verify_selection_record(selection_path, research_id=RESEARCH_ID,
                                    allow_completed_final=True)
        finally:
            if previous_ledger is None:
                os.environ.pop("OPENEVOLVE_REQUEST_BUDGET_DB", None)
            else:
                os.environ["OPENEVOLVE_REQUEST_BUDGET_DB"] = previous_ledger
            if previous_mode is None:
                os.environ.pop("TN_EXECUTION_MODE", None)
            else:
                os.environ["TN_EXECUTION_MODE"] = previous_mode
        request_usage_record = request_usage(ledger)
        if request_usage_record.get("total") != 79 or len(server.events) != 79:
            raise RuntimeError(
                f"fake drill expected 79 requests, got ledger={request_usage_record.get('total')} "
                f"server_events={len(server.events)}"
            )
        if sha256(manifest_path.read_bytes()).hexdigest() != manifest_sha256:
            raise RuntimeError("discovery run manifest changed after selection")
        (drill / "server_events.json").write_text(
            json.dumps(server.events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        completion = {
            "status": "completed",
            "research_id": RESEARCH_ID,
            "discovery_run_manifest": str(manifest_path.resolve()),
            "discovery_run_manifest_sha256": manifest_sha256,
            "selection": str(selection_path.resolve()),
            "selection_sha256_before_final": selection_sha256_before,
            "selection_sha256_after_final": selection_sha256_after,
            "selection_revalidated": True,
            "selected_run": str(Path(selected["run"]).resolve()),
            "selected_run_id": selected["run_id"],
            "final_report": str(final_report.resolve()),
            "request_usage": request_usage_record,
            "server_events": len(server.events),
        }
        (drill / "drill_completion.json").write_text(
            json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(drill)
    finally:
        server.shutdown()
        if args.keep_server_log and server.events:
            (drill / "server_events.json").write_text(
                json.dumps(server.events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
