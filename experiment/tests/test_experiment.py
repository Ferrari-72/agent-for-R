import itertools
import io
import json
import os
from collections import Counter
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from contextlib import redirect_stdout, redirect_stderr
from math import prod
from pathlib import Path
from types import SimpleNamespace

from tnlab.baselines import find_path
from tnlab.instances import circuit, lattice, load_cases
from tnlab.scoring import score_path, validate_path

ROOT = Path(__file__).resolve().parents[1]
os.environ["TN_EXECUTION_MODE"] = "local"
os.environ["TN_DEVELOP_SET"] = "develop.json"
CHAIN = {"name": "chain", "inputs": [["a", "b"], ["b", "c"], ["c", "d"]],
         "output": ["a", "d"], "sizes": {"a": 2, "b": 3, "c": 4, "d": 5}}
FOUR_CHAIN = {"name": "four_chain", "inputs": [["a", "b"], ["b", "c"],
              ["c", "d"], ["d", "e"]], "output": ["a", "e"],
              "sizes": {"a": 2, "b": 3, "c": 4, "d": 5, "e": 6}}


class InstanceTests(unittest.TestCase):
    def test_versioned_benchmark_is_reproducible(self):
        import hashlib
        from prepare_benchmark import build_sets
        manifest = json.loads((ROOT / "data" / "manifest_v2.json").read_text(encoding="utf-8"))
        for name, expected in build_sets().items():
            with self.subTest(name=name):
                content = (ROOT / "data" / name).read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), manifest[name]["sha256"])
                self.assertEqual(json.loads(content), expected)

    def test_fixed_instances_match_generators_and_network_rules(self):
        cases = load_cases() + load_cases("holdout.json")
        self.assertEqual(len(cases), 6)
        self.assertEqual(len({case["name"] for case in cases}), 6)
        for case in cases:
            with self.subTest(case=case["name"]):
                source = case["source"]
                if case["family"] == "lattice":
                    rows, cols = source["rows"], source["cols"]
                    regenerated = lattice(rows, cols, source["seed"])
                    self.assertEqual(len(case["inputs"]), rows * cols)
                    self.assertEqual(len(case["sizes"]), rows * (cols - 1) + cols * (rows - 1))
                    self.assertEqual(case["output"], [])
                else:
                    regenerated = circuit(source["qubits"], source["depth"], source["seed"])
                    self.assertEqual(len(case["output"]), source["qubits"])
                self.assertEqual(case, regenerated)
                counts = Counter(label for tensor in case["inputs"] for label in tensor)
                self.assertEqual(set(counts), set(case["sizes"]))
                self.assertTrue(all(size == 2 for size in case["sizes"].values()))
                self.assertTrue(all(counts[label] == 1 for label in case["output"]))
                self.assertTrue(all(counts[label] == 2 for label in counts if label not in case["output"]))


def direct_cost(case, path):
    """Independent count: each pair costs the product of all involved dimensions."""
    active = [set(tensor) for tensor in case["inputs"]]
    total = 0
    for i, j in path:
        left, right = active[i], active[j]
        total += prod(case["sizes"][index] for index in left | right)
        remaining = [tensor for k, tensor in enumerate(active) if k not in (i, j)]
        keep = set(case["output"]).union(*remaining)
        remaining.append((left | right) & keep)
        active = remaining
    return total


class ScoringTests(unittest.TestCase):
    def test_all_four_tensor_pairwise_paths_match_independent_count(self):
        for first in itertools.combinations(range(4), 2):
            for second in itertools.combinations(range(3), 2):
                path = [first, second, (0, 1)]
                with self.subTest(path=path):
                    self.assertEqual(score_path(FOUR_CHAIN, path).cost,
                                     direct_cost(FOUR_CHAIN, path))

    def test_known_chain(self):
        self.assertEqual(score_path(CHAIN, [(0, 1), (0, 1)]).cost, 64)
        self.assertEqual(score_path(CHAIN, [(1, 2), (0, 1)]).cost, 90)
        self.assertEqual(score_path(CHAIN, [(0, 1), (0, 1)]).peak_elements, 20)

    def test_all_three_tensor_first_pairs(self):
        for pair in itertools.combinations(range(3), 2):
            path = [pair, (0, 1)]
            self.assertEqual(score_path(CHAIN, path).cost, direct_cost(CHAIN, path))

    def test_reject_invalid_paths(self):
        for bad in ([], [(0, 0), (0, 1)], [(0, 3), (0, 1)],
                    [(0, 1), (0, 2)], [(0, 1), (0, 1.0)]):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                validate_path(CHAIN, bad)

    def test_baseline_repeatability(self):
        case = load_cases()[0]
        for method in ("greedy", "random-greedy", "simulated-annealing"):
            first, _ = find_path(case, method)
            second, _ = find_path(case, method)
            self.assertEqual(first, second)
            self.assertGreater(score_path(case, first).cost, 0)


class CandidateTests(unittest.TestCase):
    def test_saved_report_recheck_detects_cost_tampering(self):
        from verify_saved_report import verify
        from hashlib import sha256
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            run = Path(directory)
            (run / "best_recheck.py").write_text("def find_path(*args): pass\n", encoding="utf-8")
            code_hash = sha256((run / "best_recheck.py").read_bytes()).hexdigest()
            (run / "development_report.json").write_text(json.dumps(
                {"environment": {"best_code_sha256": code_hash}}), encoding="utf-8")
            data = run / "frozen_data"
            data.mkdir()
            (data / "synthetic.json").write_text(json.dumps([CHAIN]), encoding="utf-8")
            manifest = {"synthetic.json": {"sha256": sha256(
                (data / "synthetic.json").read_bytes()).hexdigest()}}
            (data / "manifest_v2.json").write_text(json.dumps(manifest), encoding="utf-8")
            path = [(0, 1), (0, 1)]
            score = score_path(CHAIN, path)
            item = {"path": path, "cost": score.cost,
                    "peak_elements": score.peak_elements, "search_seconds": 0.1}
            group = {"cases": [{"case": CHAIN["name"], "baselines": {"greedy": item},
                                "best_baseline_cost": score.cost,
                                "candidate": {"0": {**item, "ratio_to_best_baseline": 1.0,
                                                    "ratio_to_greedy": 1.0}}}],
                     "summary": {"trials": 1, "valid_trials": 1, "failure_rate": 0.0,
                                 "geometric_ratio_to_best_baseline": 1.0}}
            report = {"program_sha256": code_hash, "benchmark_manifest": manifest,
                      "results": {"synthetic.json": group}}
            final = run / "final_report.json"
            final.write_text(json.dumps(report), encoding="utf-8")
            self.assertEqual(verify(run)["verified_paths"], 2)
            report["results"]["synthetic.json"]["cases"][0]["candidate"]["0"]["cost"] += 1
            final.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cost or peak differs"):
                verify(run)

    def test_frozen_source_snapshot_has_verifiable_copies(self):
        from tnlab.freeze import snapshot_frozen_sources
        from hashlib import sha256
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            hashes = snapshot_frozen_sources(directory)
            for name, expected in hashes.items():
                relative = Path(*Path(name).parts[1:]) if name.startswith("../") else Path(name)
                saved = Path(directory) / "frozen_sources" / relative
                self.assertEqual(sha256(saved.read_bytes()).hexdigest(), expected)

    def test_research_summary_separates_run_and_cumulative_requests(self):
        from final_evaluation import research_summary
        development = {"search": {
            "requests_added_this_run": {"total": 4},
            "budget_db_cumulative_count": 45,
            "request_limit": 30,
            "candidate_attempts": 5,
            "valid_candidate_rate": 0.6,
        }}
        summary = research_summary(development, {"results": {
            "final_v2.json": {"summary": {"valid_trials": 0, "trials": 0,
                                             "failure_rate": 0.0,
                                             "geometric_ratio_to_best_baseline": 1.0}},
            "transfer_v2.json": {"summary": {"valid_trials": 0, "trials": 0,
                                                "failure_rate": 0.0}},
        }})
        self.assertIn("本次新增 4 次", summary)
        self.assertIn("预算库累计 45 次", summary)
        self.assertIn("本次运行上限 30", summary)
        self.assertIn("本次请求起点已记录", summary)

        legacy = {"search": {"http_requests": {"total": 26},
                             "candidate_attempts": 5}}
        legacy_summary = research_summary(legacy, {"results": {
            "final_v2.json": {"summary": {"valid_trials": 0, "trials": 0,
                                            "failure_rate": 0.0,
                                            "geometric_ratio_to_best_baseline": 1.0}},
            "transfer_v2.json": {"summary": {"valid_trials": 0, "trials": 0,
                                               "failure_rate": 0.0}},
        }})
        self.assertIn("本次新增 未知 次", legacy_summary)
        self.assertIn("预算库累计 26 次", legacy_summary)
        self.assertIn("不能从累计值反推本次新增请求", legacy_summary)

        from tnlab.freeze import archive_runner_image, verify_runner_image_archive
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            def fake_save(command, check):
                archive = Path(command[command.index("--output") + 1])
                archive.write_bytes(b"deterministic image archive")

            with patch("tnlab.freeze.subprocess.run", side_effect=fake_save):
                manifest = archive_runner_image(output, "sha256:image", "source-hash")
            self.assertEqual(
                verify_runner_image_archive(output, "sha256:image", "source-hash"), manifest
            )
            (output / "runner-image.tar").write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "missing or has changed"):
                verify_runner_image_archive(output, "sha256:image", "source-hash")

        from final_evaluation import evaluate_frozen_sets
        cases = [{"name": "first"}, {"name": "second"}]
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            (output / "final_progress.jsonl").write_text(
                json.dumps({"set": "synthetic.json", "result": {"case": "first"}}) + "\n",
                encoding="utf-8")
            with patch("final_evaluation.load_cases", return_value=cases), \
                 patch("final_evaluation.compare_case",
                       return_value={"case": "second"}) as compare, \
                 patch("final_evaluation.summarize", return_value={"trials": 2}):
                report = evaluate_frozen_sets(output, Path("candidate.py"),
                                              ("synthetic.json",))
            compare.assert_called_once_with(Path("candidate.py"), cases[1])
            self.assertEqual([item["case"] for item in report["synthetic.json"]["cases"]],
                             ["first", "second"])

    def test_experiment_prompt_uses_strict_custom_diff_template(self):
        from openevolve.config import load_config
        from openevolve.prompt.sampler import PromptSampler

        with patch.dict(os.environ, {"OPENAI_API_KEY": "prompt-test-only"}):
            config = load_config(ROOT / "config.yaml")
        prompt = PromptSampler(config.prompt).build_prompt(
            current_program=(ROOT / "initial_program.py").read_text(encoding="utf-8"),
            parent_program=(ROOT / "initial_program.py").read_text(encoding="utf-8"),
            program_metrics={"combined_score": 0.0},
            diff_based_evolution=True,
            program_artifacts={"case_results.json": json.dumps([{
                "case": "dev_case", "error": "invalid path feedback"}])},
        )
        self.assertFalse(config.prompt.use_template_stochasticity)
        self.assertIn("Output exactly one complete SEARCH/REPLACE block", prompt["user"])
        self.assertIn("response must end immediately after `>>>>>>> REPLACE`", prompt["user"])
        self.assertIn("dev_case", prompt["user"])
        self.assertIn("invalid path feedback", prompt["user"])
        self.assertNotIn("You can suggest multiple changes", prompt["user"])
        self.assertNotIn("explain your reasoning thoroughly", prompt["user"])

        from openevolve.utils.request_budget import reserve_request, request_last_id, request_usage
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            environment = {"OPENEVOLVE_REQUEST_BUDGET_DB": str(Path(directory) / "budget.db"),
                           "OPENEVOLVE_REQUEST_LIMIT": "2"}
            with patch.dict(os.environ, environment):
                reserve_request("model_list")
                first_id = request_last_id()
                reserve_request("probe_completion")
                self.assertEqual(request_usage(after_id=first_id)["total"], 1)
                with self.assertRaisesRegex(RuntimeError, "budget exhausted"):
                    reserve_request("chat_completion")

    def test_request_run_ids_isolate_interleaved_requests_and_migrate_legacy_rows(self):
        import sqlite3
        from contextlib import closing
        from concurrent.futures import ThreadPoolExecutor
        from openevolve.utils.request_budget import reserve_request, request_usage

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            database_path = Path(directory) / "budget.sqlite3"
            with closing(sqlite3.connect(database_path)) as database:
                database.execute("CREATE TABLE requests (id INTEGER PRIMARY KEY, "
                                 "kind TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
                database.execute("INSERT INTO requests (kind) VALUES ('legacy')")
                database.commit()
            environment = {"OPENEVOLVE_REQUEST_BUDGET_DB": str(database_path),
                           "OPENEVOLVE_REQUEST_LIMIT": "10", "TN_EXECUTION_MODE": "container"}
            with patch.dict(os.environ, environment):
                with self.assertRaisesRegex(RuntimeError, "no run_id column"):
                    request_usage(run_id="run-a")
                reserve_request("model_list", run_id="run-a")
                reserve_request("model_list", run_id="run-b")
                reserve_request("chat_completion", run_id="run-a")
                reserve_request("chat_completion", run_id="run-b")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    list(pool.map(lambda run: reserve_request("chat_completion", run),
                                  ("run-a", "run-b", "run-a", "run-b")))
                self.assertEqual(request_usage(run_id="run-a"),
                                 {"total": 4, "by_kind": {"chat_completion": 3, "model_list": 1}})
                self.assertEqual(request_usage(run_id="run-b")["total"], 4)
                self.assertEqual(request_usage()["total"], 9)
            with closing(sqlite3.connect(database_path)) as database:
                self.assertEqual(database.execute(
                    "SELECT kind, run_id FROM requests WHERE id = 1").fetchone(),
                    ("legacy", None))

    def test_failure_classification_keeps_observation_separate(self):
        from tnlab.experience import classify_failure
        self.assertEqual(classify_failure("invalid_path", "bad pair"), "path_semantics")
        self.assertEqual(classify_failure("syntax_or_interface", "SyntaxError"),
                         "syntax_interface")
        self.assertEqual(classify_failure("nondeterministic", "different path"),
                         "nondeterminism")
        self.assertEqual(classify_failure("llm_request_timeout", ""), "request_service")
        self.assertEqual(classify_failure("timeout", "model HTTP timeout"), "request_service")
        self.assertEqual(classify_failure("timeout", "candidate exceeded limit"), "resource")
        self.assertEqual(classify_failure("invalid_path", "nondeterministic different path"),
                         "nondeterminism")

    def test_experience_validation_requires_evidence_and_replication(self):
        from tnlab.experience import validate_experience
        record = {
            "experience_id": "exp-1", "status": "replicated",
            "scope": {"failure_class": "path_semantics"},
            "observation": "two candidates used stale positions",
            "interpretation": "likely prompt/API confusion",
            "recommendation": "show dynamic-position rule",
            "source": {"run_id": "run-1", "artifact_path": "a.json",
                       "artifact_sha256": "abc", "dataset": "develop_v2.json"},
            "counterexamples": [], "validation_runs": ["run-1"],
            "last_reviewed": "2026-10-23",
        }
        self.assertTrue(any("replicated status requires" in error
                            for error in validate_experience(record)))
        record["validation_runs"].append("run-2")
        self.assertEqual(validate_experience(record), [])

    def test_experience_validation_rejects_held_out_source(self):
        from tnlab.experience import validate_experience
        record = {
            "experience_id": "exp-2", "status": "single_run",
            "scope": {"failure_class": "objective_regression"},
            "observation": "candidate regressed",
            "interpretation": "unknown",
            "recommendation": "test a different heuristic",
            "source": {"run_id": "run-1", "artifact_path": "final.json",
                       "artifact_sha256": "abc", "dataset": "final_v2.json"},
            "counterexamples": [], "validation_runs": ["run-1"],
            "last_reviewed": "2026-10-23",
        }
        self.assertTrue(any("held-out" in error for error in validate_experience(record)))

        from openevolve.utils.request_budget import reserve_request
        with patch.dict(os.environ, {"TN_EXECUTION_MODE": "container"}):
            os.environ.pop("OPENEVOLVE_REQUEST_BUDGET_DB", None)
            with self.assertRaisesRegex(RuntimeError, "persistent budget database"):
                reserve_request("chat_completion")

    def test_pre_admission_errors_reach_next_prompt(self):
        from openevolve.process_parallel import format_pipeline_feedback
        feedback = format_pipeline_feedback([
            {"iteration": 1, "error": "No valid diffs found in response"},
            {"iteration": 2, "error": "LLM generation failed: timeout"},
        ])
        self.assertIn("No valid diffs", feedback)
        self.assertIn("generation failed", feedback)

    def test_failed_evaluation_cannot_be_admitted(self):
        from openevolve.process_parallel import candidate_failure_reason
        artifacts = {"case_results.json": json.dumps([
            {"case": "preflight_chain", "error": "path must have exactly n-1 steps"}])}
        reason = candidate_failure_reason({"failure_count": 1}, artifacts)
        self.assertIn("path must have exactly n-1 steps", reason)
        self.assertEqual(candidate_failure_reason({"failure_count": 0}, artifacts), "")

    def test_feedback_keeps_last_traceback_line(self):
        from openevolve.process_parallel import candidate_failure_reason
        artifacts = {"case_results.json": json.dumps([{
            "error": "candidate error", "error_code": "execution_error",
            "detail": "Traceback (most recent call last):\n" + "context\n" * 100
                      + "TypeError: greedy() got an unexpected keyword argument 'seed'\n\n"}])}
        reason = candidate_failure_reason({"failure_count": 1}, artifacts)
        self.assertIn("unexpected keyword argument 'seed'", reason)

    def test_preflight_rejects_bad_api_before_development_set(self):
        from openevolve_evaluator import evaluate
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "bad_api.py"
            file.write_text(
                "def find_path(inputs, output, sizes, seed=0):\n"
                "    import opt_einsum as oe\n"
                "    try:\n"
                "        return oe.paths.greedy([set(x) for x in inputs], set(output), sizes, seed=seed)\n"
                "    except TypeError:\n"
                "        return []\n", encoding="utf-8")
            result = evaluate(file)
        records = json.loads(result.artifacts["case_results.json"])
        self.assertEqual(result.metrics["failure_count"], 1)
        self.assertEqual(records[0]["case"], "preflight_chain")
        self.assertEqual(records[0]["error_code"], "invalid_path")
        stages = json.loads(result.artifacts["pipeline_stages.json"])
        self.assertEqual([(item["stage"], item["status"]) for item in stages],
                         [("syntax_and_interface", "passed"),
                          ("small_network", "failed")])

    def test_container_command_does_not_mount_benchmarks(self):
        from tnlab.execution import run_candidate
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "candidate.py"
            file.write_text("def find_path(*args, **kwargs): return []\n", encoding="utf-8")
            fake = SimpleNamespace(returncode=0,
                                    stdout='{"path": [], "search_seconds": 0.0}', stderr="")
            with patch.dict(os.environ, {"TN_EXECUTION_MODE": "container"}), \
                 patch("tnlab.execution.subprocess.run", return_value=fake) as call:
                run_candidate(file, CHAIN)
        command = call.call_args.args[0]
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("--env", command)
        self.assertIn("PYTHONHASHSEED=0", command)
        self.assertEqual(sum("type=bind" in part for part in command), 1)
        self.assertNotIn("OPENAI_API_KEY", str(command))

    def test_container_timeout_removes_started_container(self):
        from tnlab.execution import run_candidate
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "candidate.py"
            file.write_text("def find_path(*args, **kwargs): return []\n", encoding="utf-8")
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                if command[1] == "run":
                    cid = Path(command[command.index("--cidfile") + 1])
                    cid.write_text("test-container-id", encoding="utf-8")
                    raise subprocess.TimeoutExpired(command, 15)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch.dict(os.environ, {"TN_EXECUTION_MODE": "container"}), \
                 patch("tnlab.execution.subprocess.run", side_effect=fake_run), \
                 self.assertRaises(subprocess.TimeoutExpired):
                run_candidate(file, CHAIN)
        self.assertEqual(calls[-1], ["docker", "rm", "-f", "test-container-id"])

    def test_initial_evaluator(self):
        from openevolve_evaluator import evaluate
        result = evaluate(ROOT / "initial_program.py")
        self.assertEqual(result.metrics["failure_count"], 0)
        self.assertAlmostEqual(result.metrics["combined_score"], 0)

    def test_any_invalid_case_rejects_candidate(self):
        from openevolve_evaluator import FAILURE_SCORE, evaluate
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "invalid.py"
            file.write_text("def find_path(*args, **kwargs):\n    return []\n")
            result = evaluate(file)
        self.assertEqual(result.metrics["failure_count"], 1)
        self.assertEqual(result.metrics["combined_score"], FAILURE_SCORE)

    def test_nondeterministic_candidate_is_rejected(self):
        from openevolve_evaluator import evaluate_case
        first = {"path": [(0, 1), (0, 1)], "search_seconds": 0.1}
        changed = {"path": [(1, 2), (0, 1)], "search_seconds": 0.1}
        with patch("openevolve_evaluator.run_candidate",
                   side_effect=[(first, 0.2), (changed, 0.2)]):
            record = evaluate_case(ROOT / "initial_program.py", CHAIN)
        self.assertEqual(record["error_code"], "invalid_path")
        self.assertIn("nondeterministic", record["error"])

    def test_candidate_exception_and_invalid_path(self):
        from openevolve_evaluator import evaluate_case
        case = CHAIN
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "bad.py"
            file.write_text("def find_path(*args, **kwargs):\n    raise RuntimeError('broken')\n")
            self.assertIn("error", evaluate_case(file, case))
            file.write_text("def find_path(*args, **kwargs):\n    return [(0, 0), (0, 1)]\n")
            self.assertIn("error", evaluate_case(file, case))

    def test_runner_decodes_non_utf8_child_errors(self):
        from tnlab.runner_protocol import run_worker
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            worker = Path(directory) / "worker.py"
            worker.write_text(
                "import sys\nsys.stderr.buffer.write(bytes([0xd5]))\nsys.exit(1)\n",
                encoding="utf-8")
            with self.assertRaises(RuntimeError) as context:
                run_worker(worker, {}, timeout=2)
            self.assertIsInstance(str(context.exception), str)

    def test_runner_json_protocol(self):
        case = CHAIN
        process = subprocess.run(
            [sys.executable, str(ROOT / "candidate_runner.py"), str(ROOT / "initial_program.py")],
            input=json.dumps(case), text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        answer = json.loads(process.stdout)
        self.assertIn(score_path(case, answer["path"]).cost, (64, 90))

    def test_candidate_timeout(self):
        from openevolve_evaluator import evaluate_case
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "slow.py"
            file.write_text("import time\ndef find_path(*args, **kwargs):\n    time.sleep(2)\n    return []\n")
            with patch("openevolve_evaluator.CASE_TIMEOUT_SECONDS", 0.2):
                self.assertEqual(evaluate_case(file, CHAIN)["error"], "timeout")

    def test_trusted_search_timer_includes_candidate_import(self):
        from openevolve_evaluator import evaluate_case
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "slow_import.py"
            file.write_text(
                "import time\ntime.sleep(0.4)\n"
                "def find_path(inputs, output, sizes, seed=0):\n"
                "    return [(0, 1), (0, 1)]\n", encoding="utf-8")
            record = evaluate_case(file, CHAIN)
        self.assertNotIn("error", record)
        self.assertGreater(record["search_seconds"], 0.4)
        self.assertLess(record["function_seconds_untrusted"], 0.2)
        self.assertGreater(record["wall_seconds"], 0.35)

    def test_api_probe_selects_fast_listed_model(self):
        import probe_api
        fake = MagicMock()
        fake.models.list.return_value.data = [MagicMock(id="Qwen/Qwen3.6-27B")]
        fake.chat.completions.create.return_value.choices = [MagicMock()]
        output = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "local-test"}), \
             patch.object(probe_api, "OpenAI", return_value=fake), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            probe_api.main()
        self.assertEqual(output.getvalue().strip(), "Qwen/Qwen3.6-27B")
        self.assertEqual(fake.chat.completions.create.call_args.kwargs["extra_body"],
                         {"enable_thinking": False})

    def test_failed_candidate_feedback_reaches_next_prompt(self):
        from openevolve.process_parallel import _recent_failure_feedback
        failed = SimpleNamespace(id="bad", iteration_found=1,
                                 metrics={"failure_count": 4.0})
        records = [{"case": "small", "error": "path must have exactly n-1 steps"}]
        message = _recent_failure_feedback(
            [failed], {"bad": {"case_results.json": json.dumps(records)}}
        )
        self.assertIn("path must have exactly n-1 steps", message)
        self.assertIn("Fix these errors", message)

    def test_v2_baseline_entrypoint_accepts_frozen_sets(self):
        import run_baselines
        with patch.object(run_baselines, "run_baseline",
                          return_value={"case": "x", "method": "greedy",
                                        "cost": 1, "peak_elements": 1,
                                        "search_seconds": 0}):
            with patch.object(run_baselines, "load_cases", return_value=[]):
                with patch("sys.argv", ["run_baselines.py", "--set", "final_v2.json"]):
                    run_baselines.main()

    def test_no_admitted_candidate_still_writes_report(self):
        from run_experiment import write_report
        from types import SimpleNamespace
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            (output / "iteration_journal.jsonl").write_text(
                json.dumps({"iteration": 1, "status": "rejected",
                            "error": "budget exhausted"}) + "\n", encoding="utf-8")
            with patch.dict(os.environ, {"TN_EXECUTION_MODE": "local",
                                         "OPENEVOLVE_REQUEST_BUDGET_DB": "",
                                         "OPENEVOLVE_REQUEST_LIMIT": "1"}, clear=False):
                report = write_report(SimpleNamespace(best_program=None), output, 2)
            self.assertIsNone(report["develop"])
            self.assertEqual(report["search"]["termination_reason"],
                             "no valid candidate was admitted")
            self.assertTrue((output / "development_report.json").is_file())

    def test_process_summary_preserves_change_and_failure_history(self):
        from run_experiment import write_process_summary
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            rounds = [{
                "iteration": 1, "status": "rejected", "parent_id": "p1",
                "program_id": "c1", "error": "invalid path", "error_code": "invalid_path",
                "changes_description": "try a safer fallback",
                "change_summary": {"parent_sha256": "a" * 64, "child_sha256": "b" * 64,
                                   "added_lines": 2, "removed_lines": 1},
                "stages": [{"stage": "development_set", "status": "failed"}],
                "token_usage": {"total_tokens": 9},
                "prompt_metadata": {"user": {"sha256": "c" * 64, "characters": 12}},
                "artifact_files": {"prompt": "pipeline_artifacts/iteration_001/prompt.json"},
            }]
            report = {"search": {"candidate_attempts": 1, "valid_candidates": 0,
                                  "tokens": {"total_tokens": 9},
                                  "termination_reason": "no valid candidate was admitted"}}
            write_process_summary(output, rounds, report)
            summary = json.loads((output / "process_summary.json").read_text(encoding="utf-8"))
            markdown = (output / "experiment_process.md").read_text(encoding="utf-8")
            self.assertEqual(summary[0]["change_summary"]["added_lines"], 2)
            self.assertIn("invalid path", markdown)
            self.assertIn("parent `aaaaaaaaaaaa` -> child `bbbbbbbbbbbb`", markdown)
            self.assertIn("total_tokens", markdown)
            self.assertTrue((output / "experiment_process.md").is_file())


if __name__ == "__main__":
    unittest.main()
