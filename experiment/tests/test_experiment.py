import itertools
import io
import json
import os
from collections import Counter
import subprocess
import sys
import tempfile
import unittest
import shutil
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

    def test_local_baseline_ignores_parent_hash_seed(self):
        from tnlab.execution import run_baseline as isolated_baseline

        case = next(case for case in load_cases("develop_v2.json")
                    if case["name"] == "circuit_5q_d3_s31")
        with patch.dict(os.environ, {"TN_EXECUTION_MODE": "local", "PYTHONHASHSEED": "1"}):
            first, _ = isolated_baseline(case, "random-greedy")
        with patch.dict(os.environ, {"TN_EXECUTION_MODE": "local", "PYTHONHASHSEED": "2"}):
            second, _ = isolated_baseline(case, "random-greedy")
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(score_path(case, first["path"]).cost, 1708)


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

    def test_saved_report_recheck_accepts_v3_manifest(self):
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
            (data / "manifest_v3.json").write_text(json.dumps(manifest), encoding="utf-8")
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
            (run / "final_report.json").write_text(json.dumps(
                {"program_sha256": code_hash, "benchmark_manifest": manifest,
                 "results": {"synthetic.json": group}}), encoding="utf-8")
            self.assertEqual(verify(run)["verified_paths"], 2)

    def test_frozen_benchmark_snapshot_includes_development_and_heldout_sets(self):
        from tnlab.freeze import snapshot_frozen_data
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            names = snapshot_frozen_data(directory)
            self.assertEqual(names, ("manifest_v2.json", "develop_v2.json",
                                     "manifest_v3.json", "final_v3.json", "transfer_v3.json"))
            for name in names:
                self.assertEqual(
                    (Path(directory) / "frozen_data" / name).read_bytes(),
                    (ROOT / "data" / name).read_bytes())

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
        }}, final_name="final_v2.json", transfer_name="transfer_v2.json")
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
        }}, final_name="final_v2.json", transfer_name="transfer_v2.json")
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

        from final_evaluation import evaluate_frozen_sets, _evidence_sha256, _rules_sha256
        cases = [{"name": "first"}, {"name": "second"}]
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            (output / "final_progress.jsonl").write_text(
                json.dumps({"set": "synthetic.json", "result": {"case": "first"}}) + "\n",
                encoding="utf-8")
            with patch("final_evaluation.load_cases", return_value=cases), \
                 patch("final_evaluation.compare_case") as compare:
                with self.assertRaisesRegex(RuntimeError, "progress evidence is invalid"):
                    evaluate_frozen_sets(output, Path("candidate.py"), ("synthetic.json",),
                                         "candidate-hash", "rules-hash")
                compare.assert_not_called()

            (output / "final_progress.jsonl").unlink()
            first = {"case": "first", "value": 1, "wall_seconds": 0.1}
            second = {"case": "second", "value": 2, "wall_seconds": 0.1}
            with patch("final_evaluation.load_cases", return_value=cases), \
                 patch("final_evaluation.compare_case", side_effect=[first, second, first, second]) as compare, \
                 patch("final_evaluation.summarize", return_value={"trials": 2}):
                evaluate_frozen_sets(output, Path("candidate.py"), ("synthetic.json",),
                                     "candidate-hash", "rules-hash")
                report = evaluate_frozen_sets(output, Path("candidate.py"), ("synthetic.json",),
                                              "candidate-hash", "rules-hash")
            self.assertEqual(compare.call_count, 4)
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
            database_path = Path(directory) / "budget.db"
            from openevolve.utils.request_budget import initialize_request_budget
            initialize_request_budget(database_path, "budget-test", 2)
            environment = {"OPENEVOLVE_REQUEST_BUDGET_DB": str(database_path),
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
                database.execute("CREATE TABLE budget_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                database.executemany("INSERT INTO budget_meta (key, value) VALUES (?, ?)", [
                    ("research_id", "study-test"), ("limit", "10")])
                database.commit()
            from openevolve.utils.request_budget import initialize_request_budget
            initialize_request_budget(database_path, "study-test", 10)
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
        self.assertEqual(record["error_code"], "nondeterministic")
        self.assertEqual(record["failure_class"], "nondeterminism")
        self.assertEqual(record["reproducibility_repeat"], 2)
        self.assertIn("different path", record["error"])

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

    def test_request_budget_rejects_environment_limit_mismatch(self):
        from openevolve.utils.request_budget import initialize_request_budget, reserve_request
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            ledger = Path(directory) / "budget.sqlite3"
            initialize_request_budget(ledger, "study-test", 100)
            with patch.dict(os.environ, {
                    "OPENEVOLVE_REQUEST_BUDGET_DB": str(ledger),
                    "OPENEVOLVE_REQUEST_LIMIT": "101"}):
                with self.assertRaisesRegex(RuntimeError, "differs from ledger limit"):
                    reserve_request("chat_completion")
            with patch.dict(os.environ, {
                    "OPENEVOLVE_REQUEST_BUDGET_DB": str(ledger),
                    "OPENEVOLVE_REQUEST_LIMIT": "1"}):
                with self.assertRaisesRegex(RuntimeError, "differs from ledger limit"):
                    reserve_request("chat_completion")
            with patch.dict(os.environ, {
                    "OPENEVOLVE_REQUEST_BUDGET_DB": str(ledger)}, clear=True):
                reserve_request("chat_completion")

    def test_reproducibility_repeat_failures_keep_class_and_index(self):
        from openevolve_evaluator import evaluate_case
        from tnlab.execution import ResourceLimitError
        first = ({"path": [(0, 1), (0, 1)], "search_seconds": 0.1}, 0.2)
        failures = (
            (TimeoutError("timeout repeat"), "timeout", "resource"),
            (MemoryError("memory limit exceeded"), "resource_limit", "resource"),
            (RuntimeError("runner import failed"), "execution_error", "unknown"),
        )
        for failure, error_code, failure_class in failures:
            with self.subTest(error_code=error_code), patch(
                    "openevolve_evaluator._run_checked", side_effect=[first, failure]):
                record = evaluate_case(ROOT / "initial_program.py", CHAIN)
                self.assertEqual(record["error_code"], error_code)
                self.assertEqual(record["failure_class"], failure_class)
                self.assertEqual(record["reproducibility_repeat"], 2)

    def test_repeat_resource_limit_exception_is_classified(self):
        from openevolve_evaluator import evaluate_case
        from tnlab.execution import ResourceLimitError
        first = ({"path": [(0, 1), (0, 1)], "search_seconds": 0.1}, 0.2)
        with patch("openevolve_evaluator._run_checked",
                   side_effect=[first, MemoryError("memory limit exceeded")]):
            record = evaluate_case(ROOT / "initial_program.py", CHAIN)
        self.assertEqual(record["error_code"], "resource_limit")
        self.assertEqual(record["reproducibility_repeat"], 2)

    def test_candidate_timeout(self):
        from openevolve_evaluator import evaluate_case
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "slow.py"
            file.write_text("import time\ndef find_path(*args, **kwargs):\n    time.sleep(2)\n    return []\n")
            with patch("openevolve_evaluator.CASE_TIMEOUT_SECONDS", 0.2):
                record = evaluate_case(file, CHAIN)
            self.assertEqual(record["error_code"], "timeout")
            self.assertEqual(record["failure_class"], "resource")
            self.assertEqual(record["reproducibility_repeat"], 1)

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
        fake.models.list.return_value.data = [MagicMock(id="deepseek-ai/DeepSeek-V3.2")]
        fake.chat.completions.create.return_value.choices = [MagicMock()]
        output = io.StringIO()
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "local-test",
            "OPENEVOLVE_REQUEST_BUDGET_DB": "",
            "TN_EXECUTION_MODE": "",
        }), patch.object(probe_api, "OpenAI", return_value=fake), \
             redirect_stdout(output), redirect_stderr(io.StringIO()):
            probe_api.main()
        self.assertEqual(output.getvalue().strip(), "deepseek-ai/DeepSeek-V3.2")
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
                for dataset in ("final_v2.json", "final_v3.json", "transfer_v3.json"):
                    with patch("sys.argv", ["run_baselines.py", "--set", dataset]):
                        run_baselines.main()

    def test_iteration_statistics_separate_requests_generation_evaluation_and_admission(self):
        from run_experiment import derive_iteration_statistics
        rounds = [
            {"iteration": 1, "status": "rejected",
             "stages": [{"stage": "model_request", "status": "passed"},
                        {"stage": "evaluation_total", "status": "failed"}],
             "metrics": {"failure_count": 1}},
            {"iteration": 2, "status": "rejected",
             "stages": [{"stage": "model_request", "status": "passed"},
                        {"stage": "evaluation_total", "status": "passed"}],
             "metrics": {"failure_count": 0}},
            {"iteration": 3, "status": "admitted",
             "stages": [{"stage": "model_request", "status": "passed"},
                        {"stage": "evaluation_total", "status": "passed"}],
             "metrics": {"failure_count": 0}},
            {"iteration": 4, "status": "rejected",
             "stages": [{"stage": "model_request", "status": "failed"}]},
        ]
        stats = derive_iteration_statistics(rounds, {"total": 5, "by_kind": {"chat_completion": 5}})
        self.assertEqual(stats["journal_iterations"], 4)
        self.assertEqual(stats["generation_attempts"], 4)
        self.assertEqual(stats["completed_evaluations"], 3)
        self.assertEqual(stats["failed_evaluations"], 1)
        self.assertEqual(stats["valid_candidates"], 2)
        self.assertEqual(stats["admitted_candidates"], 1)
        self.assertEqual(stats["model_requests"]["total"], 5)
        self.assertFalse(stats["invariants"]["journal_iterations_equal_registered_limit"])

    def test_prompt_policy_manifest_is_canonical_and_verifiable(self):
        from run_experiment import _verify_prompt_policy_manifest, _write_prompt_policy_manifest
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory)
            saved = _write_prompt_policy_manifest(output)
            self.assertEqual(saved["manifest"]["failure_feedback_policy"]["id"],
                             "openevolve_recent_v1")
            self.assertFalse(saved["manifest"]["experience_policy"]["prompt_injection"])
            self.assertEqual(_verify_prompt_policy_manifest(output), saved)
            saved["manifest"]["history_policy"]["num_top_programs"] = 99
            (output / "prompt_policy_manifest.json").write_text(
                json.dumps(saved), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "prompt policy"):
                _verify_prompt_policy_manifest(output)

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

    def test_calibration_main_uses_mock_response_and_writes_machine_result(self):
        import calibrate_api
        from tempfile import TemporaryDirectory
        initial_code = (ROOT / "initial_program.py").read_text(encoding="utf-8")
        changed_code = initial_code.replace(
            '"""Return exactly len(inputs) - 1 pairs of current tensor positions."""',
            '"""Return exactly len(inputs) - 1 deterministic position pairs."""')
        response_text = (
            "<<<<<<< SEARCH\n"
            '    """Return exactly len(inputs) - 1 pairs of current tensor positions."""\n'
            "=======\n"
            '    """Return exactly len(inputs) - 1 deterministic position pairs."""\n'
            ">>>>>>> REPLACE\n")
        fake_client = MagicMock()
        fake_client.chat.completions.create.return_value.choices = [SimpleNamespace(
            message=SimpleNamespace(content=response_text))]
        with TemporaryDirectory(dir=ROOT) as directory:
            output = Path(directory) / "calibration"
            with patch.object(calibrate_api, "ROOT", ROOT), \
                 patch.object(calibrate_api, "OpenAI", return_value=fake_client), \
                 patch.object(calibrate_api, "evaluate_case", side_effect=[
                     {"cost": 100, "path": [[0, 1]], "search_seconds": 0.01},
                     {"cost": 99, "path": [[0, 1]], "search_seconds": 0.01},
                 ]), \
                 patch.dict(os.environ, {"OPENAI_API_KEY": "mock-only",
                                         "TN_RUN_ID": "calibration-test",
                                         "OPENEVOLVE_REQUEST_BUDGET_DB": "",
                                         "TN_EXECUTION_MODE": "local"}, clear=False), \
                 patch("sys.argv", ["calibrate_api.py", "--model", "fake-model",
                                     "--output", str(output)]), \
                 redirect_stdout(io.StringIO()):
                calibrate_api.main()
            result = json.loads((output / "calibration_result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "passed")
            self.assertTrue(all(check["status"] == "passed"
                                for check in result["checks"].values()))
            self.assertTrue((output / "candidate.py").is_file())
            self.assertTrue((output / "response.txt").is_file())
            self.assertEqual(fake_client.chat.completions.create.call_count, 1)

    def test_calibration_controlled_improvement_requires_strict_lower_cost(self):
        from calibrate_api import _check_controlled_improvement

        initial = {"cost": 100}
        self.assertEqual(
            _check_controlled_improvement(initial, {"cost": 99}),
            (True, "candidate cost is strictly lower than initial cost"),
        )
        passed, message = _check_controlled_improvement(initial, {"cost": 100})
        self.assertFalse(passed)
        self.assertIn("strictly lower", message)
        passed, message = _check_controlled_improvement(initial, {"cost": 101})
        self.assertFalse(passed)
        self.assertIn("strictly lower", message)
        passed, message = _check_controlled_improvement(initial, {"error": "invalid path"})
        self.assertFalse(passed)
        self.assertIn("candidate failed", message)
        passed, message = _check_controlled_improvement({"error": "initial"}, {"cost": 1})
        self.assertFalse(passed)
        self.assertIn("initial program failed", message)

    def test_calibration_controlled_improvement_rejects_non_numeric_costs(self):
        from calibrate_api import _check_controlled_improvement

        passed, message = _check_controlled_improvement({"cost": "100"}, {"cost": 99})
        self.assertFalse(passed)
        self.assertIn("numeric", message)
        passed, message = _check_controlled_improvement({"cost": 100}, {})
        self.assertFalse(passed)
        self.assertIn("numeric", message)

        from calibrate_api import _check_interface
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            program = Path(directory) / "candidate.py"
            program.write_text(
                "def find_path(inputs, output, sizes, seed=0):\n    return []\n",
                encoding="utf-8")
            self.assertTrue(_check_interface(program)[0])
            program.write_text(
                "def find_path(inputs, output, sizes):\n    return []\n",
                encoding="utf-8")
            self.assertFalse(_check_interface(program)[0])

    def test_calibration_interface_checker_rejects_wrong_defaults_and_extra_parameters(self):
        from calibrate_api import _check_interface
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            program = Path(directory) / "candidate.py"
            cases = (
                ("def find_path(inputs, output, sizes, seed=0):\n    return []\n", True),
                ("def find_path(inputs, output, sizes, seed=1):\n    return []\n", False),
                ("def find_path(inputs, output, sizes, seed=0, extra=None):\n    return []\n", False),
                ("def find_path(inputs, output, sizes, *, seed=0):\n    return []\n", False),
                ("def find_path(inputs, output, sizes, *args, seed=0):\n    return []\n", False),
            )
            for source, expected in cases:
                program.write_text(source, encoding="utf-8")
                self.assertEqual(_check_interface(program)[0], expected, source)

        import select_discovery
        from hashlib import sha256
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace

        registration = ROOT / "notes" / "formal_registration_2026-10.md"
        source_hashes = __import__("tnlab.freeze", fromlist=["frozen_file_hashes"]).frozen_file_hashes()
        initial_hash = sha256((ROOT / "initial_program.py").read_bytes()).hexdigest()
        synthetic_case = {"name": "case", "inputs": [["a", "b"], ["b", "c"]],
                          "output": ["a", "c"], "sizes": {"a": 2, "b": 3, "c": 4}}
        cases = [{"case": "case", "cost": 100, "path": [[0, 1]],
                  "peak_elements": 6, "search_seconds": 0.01}]
        with TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            runs = []
            ratios = {"run-1": 1.20, "run-2": 0.95, "run-3": 1.10,
                      "run-4": 1.05, "run-5": 1.00}
            from tnlab.baselines import run_baseline
            baseline_rows = [run_baseline(synthetic_case, method) for method in
                             ("greedy", "random-greedy", "simulated-annealing")]
            baseline_cost = min(row["cost"] for row in baseline_rows)
            for name, ratio in ratios.items():
                run = root / name
                run.mkdir()
                (run / "preregistration.md").write_bytes(registration.read_bytes())
                (run / "research_id.txt").write_text("study-test\n", encoding="utf-8")
                (run / "initial_program.sha256").write_text(initial_hash + "\n", encoding="ascii")
                (run / "frozen_source_manifest.json").write_text(
                    json.dumps(source_hashes), encoding="utf-8")
                (run / "run_id.txt").write_text(name + "\n", encoding="utf-8")
                code = (ROOT / "initial_program.py").read_text(encoding="utf-8") + "\n# " + name + "\n"
                candidate = run / "best_recheck.py"
                candidate.write_text(code, encoding="utf-8")
                candidate_hash = sha256(candidate.read_bytes()).hexdigest()
                from tnlab.freeze import snapshot_frozen_data
                snapshot_frozen_data(run)
                for frozen_name in ("manifest_v2.json", "develop_v2.json",
                                     "manifest_v3.json", "final_v3.json", "transfer_v3.json"):
                    self.assertEqual(
                        (run / "frozen_data" / frozen_name).read_bytes(),
                        (ROOT / "data" / frozen_name).read_bytes())
                baseline_file = run / "development_baselines.json"
                baseline_file.write_text(json.dumps([{"case": "case", **row}
                                                     for row in baseline_rows]), encoding="utf-8")
                archive = run / "runner-image.tar"
                archive.write_bytes(b"offline runner archive fixture")
                (run / "runner_image_manifest.json").write_text(json.dumps({
                    "image_id": "sha256:fixture", "source_sha256": "source-fixture",
                    "requirements_sha256": sha256((ROOT / "requirements.lock").read_bytes()).hexdigest(),
                    "archive": archive.name,
                    "archive_sha256": sha256(archive.read_bytes()).hexdigest()}), encoding="utf-8")
                (run / "iteration_journal.jsonl").write_text(
                    "".join(json.dumps({"iteration": index, "status": "accepted"}) + "\n"
                            for index in range(1, 16)), encoding="utf-8")
                report = {"develop": {"geometric_ratio_to_best_baseline": ratio},
                          "search": {"run_id": name, "research_id": "study-test",
                                     "requests_added_this_run": {"total": 0, "by_kind": {}}},
                          "environment": {"research_id": "study-test",
                                          "initial_program_sha256": initial_hash,
                                          "benchmark_manifest_sha256": sha256(
                                              (ROOT / "data" / "manifest_v2.json").read_bytes()).hexdigest(),
                                          "iterations_recorded": 15,
                                          "develop_set": "develop_v2.json",
                                          "best_code_sha256": candidate_hash,
                                          "development_baselines_sha256": sha256(
                                              baseline_file.read_bytes()).hexdigest(),
                                          "runner_image_id": "sha256:fixture",
                                          "runner_image_source_sha256": "source-fixture"}}
                (run / "development_report.json").write_text(
                    json.dumps(report), encoding="utf-8")
                runs.append(run)
            run_manifest_path = root / "discovery_run_manifest.json"
            run_manifest_path.write_text(json.dumps({
                "research_id": "study-test", "run_ids": list(ratios),
                "runs": [{"run_id": name, "directory": str(root / name),
                          "status": "completed"} for name in ratios],
                "registration_sha256": sha256(registration.read_bytes()).hexdigest()}),
                encoding="utf-8")
            manifest_bytes = run_manifest_path.read_bytes()
            run_manifest_path.write_bytes(b"\xef\xbb\xbf" + manifest_bytes)
            def fake_evaluate_set(candidate, set_name):
                name = Path(candidate).parent.name
                result = cases.copy()
                result[0] = {**cases[0], "cost": round(ratios[name] * baseline_cost, 5)}
                return SimpleNamespace(metrics={"failure_count": 0.0, "valid_cases": 1.0},
                                       artifacts={"case_results.json": json.dumps(result)})

            with patch.object(select_discovery, "ROOT", ROOT), \
                 patch.object(select_discovery, "load_cases", return_value=[synthetic_case]), \
                 patch.object(select_discovery, "evaluate_set", side_effect=fake_evaluate_set), \
                 patch.dict(os.environ, {"OPENEVOLVE_REQUEST_BUDGET_DB": str(root / "budget.sqlite3")}, clear=False):
                from openevolve.utils.request_budget import initialize_request_budget
                initialize_request_budget(root / "budget.sqlite3", "study-test", 100)
                result = select_discovery.select_discovery(
                    runs, root / "selection.json", registration, "study-test", run_manifest_path)
            self.assertEqual(result["status"], "selected")
            self.assertEqual(result["eligible_run_count"], 5)
            self.assertEqual(result["selected"]["run_id"], "run-2")
            self.assertTrue((root / "selection.md").is_file())

            (runs[0] / "iteration_journal.jsonl").write_text("", encoding="utf-8")
            with patch.object(select_discovery, "ROOT", ROOT), \
                 patch.object(select_discovery, "load_cases", return_value=[synthetic_case]), \
                 patch.object(select_discovery, "evaluate_set", side_effect=fake_evaluate_set), \
                 patch.dict(os.environ, {"OPENEVOLVE_REQUEST_BUDGET_DB": str(root / "budget.sqlite3")}, clear=False):
                incomplete = select_discovery.select_discovery(
                    runs, root / "incomplete.json", registration, "study-test", run_manifest_path)
            self.assertEqual(incomplete["status"], "inconclusive")
            self.assertEqual(incomplete["eligible_run_count"], 4)
            self.assertIn("expected exactly 15 journal iterations", incomplete["rejected_runs"][0]["reasons"][0])

        from openevolve.utils.request_budget import initialize_request_budget
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            ledger = Path(directory) / "requests.sqlite3"
            initialize_request_budget(ledger, "study-a", 100)
            initialize_request_budget(ledger, "study-a", 100)
            with self.assertRaisesRegex(RuntimeError, "research ID"):
                initialize_request_budget(ledger, "study-b", 100)
            with self.assertRaisesRegex(RuntimeError, "limit"):
                initialize_request_budget(ledger, "study-a", 99)

    def test_discovery_orchestration_checks_manifest_before_model_probe(self):
        script = (ROOT / "run.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[switch]$ResumeDiscovery", script)
        self.assertIn("use -ResumeDiscovery to continue its fixed identities", script)
        self.assertIn("calibration_status", script)
        self.assertIn("calibration_run_id", script)
        self.assertIn("$runManifest.runs[$runIndex - 1]", script)
        self.assertLess(script.index("$runManifestPath ="), script.index("probe_api.py"))
        self.assertLess(script.index("registration_sha256"), script.index("probe_api.py"))
        self.assertIn("if ($entry.status -eq 'completed') { continue }", script)
        self.assertIn("--resume-run $resumePath", script)
        self.assertIn("Calibration failed under the preregistered one-shot rule", script)
        self.assertIn("Calibration was interrupted after request processing began", script)
        self.assertIn("frozen_source_hashes_sha256", script)
        self.assertIn("Assert-FrozenSources", script)
        self.assertEqual(script.count("Get-RequestUsageTotal -RunId"), 1)
        self.assertEqual(script.count("[string](Get-RequestUsageTotal)"), 2)
        self.assertNotIn('request_usage()["total"]', script)

        powershell = next((candidate for candidate in (
            "powershell.exe", "pwsh.exe",
            r"C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        ) if shutil.which(candidate) or Path(candidate).is_file()), None)
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")

        from hashlib import sha256
        def run_resume_case(status, mutate=None, expect_selection=False,
                            expect_no_ledger=False):
            with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                project = Path(directory) / "experiment"
                shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns(
                    ".venv", "results", "tests", "__pycache__", "tmp*"))
                shutil.copytree(ROOT.parent / "openevolve", Path(directory) / "openevolve")
                (project / "tests").mkdir()
                (project / "tests" / "test_smoke.py").write_text(
                    "import unittest\n"
                    "class SmokeTest(unittest.TestCase):\n"
                    "    def test_smoke(self):\n"
                    "        self.assertTrue(True)\n", encoding="ascii")
                log = project / "harness.log"
                (project / "probe_api.py").write_text(
                    "from pathlib import Path\n"
                    "import os\n"
                    "path = Path(os.environ['TN_HARNESS_LOG'])\n"
                    "path.write_text('probe', encoding='utf-8')\n"
                    "print('fake-model')\n", encoding="utf-8")
                (project / "calibrate_api.py").write_text(
                    "from pathlib import Path\n"
                    "import os\n"
                    "path = Path(os.environ['TN_HARNESS_LOG'])\n"
                    "path.write_text('calibrate', encoding='utf-8')\n",
                    encoding="utf-8")
                (project / "select_discovery.py").write_text(
                    "from pathlib import Path\n"
                    "import os\n"
                    "path = Path(os.environ['TN_HARNESS_LOG'])\n"
                    "path.write_text('select', encoding='utf-8')\n",
                    encoding="utf-8")
                from tnlab import freeze
                with patch.object(freeze, "ROOT", project):
                    hashes = freeze.frozen_file_hashes()
                    source_hash = freeze.image_source_hash()
                docker = project / "docker.cmd"
                docker.write_text(
                    "@echo off\n"
                    'echo [{"Config":{"Labels":{"org.tnlab.source-sha256":"'
                    + source_hash + '"}}}]\n',
                    encoding="ascii")
                registration = project / "notes" / "formal_registration_2026-10.md"
                manifest = {
                    "research_id": "tensor-path-discovery-2026-10",
                    "registration_sha256": sha256(registration.read_bytes()).hexdigest(),
                    "frozen_source_hashes": hashes,
                    "frozen_source_hashes_sha256": sha256(json.dumps(
                        hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "run_ids": [f"run-{index}" for index in range(1, 6)],
                    "model": "fake-model",
                    "calibration_run_id": "calibration-test",
                    "calibration_status": status,
                    "calibration_directory": str(project / "results" / "calibration"),
                    "runs": [{"run_id": f"run-{index}", "status": "completed"}
                             for index in range(1, 6)],
                }
                results = project / "results"
                results.mkdir()
                manifest_path = results / "discovery_run_manifest.json"
                (project / "run.ps1").write_text(
                    (project / "run.ps1").read_text(encoding="utf-8").replace(
                        "$venvPython = Join-Path $project '.venv\\Scripts\\python.exe'",
                        "$venvPython = $env:TN_PYTHON"),
                    encoding="utf-8")
                environment = os.environ.copy()
                environment.update({
                    "TN_PYTHON": str(ROOT / ".venv" / "Scripts" / "python.exe"),
                    "OPENAI_API_KEY": "offline-test-only",
                    "TN_HARNESS_LOG": str(log),
                    "PATH": str(project) + os.pathsep + environment.get("PATH", ""),
                })
                with patch.object(freeze, "ROOT", project):
                    hashes = freeze.frozen_file_hashes()
                manifest["frozen_source_hashes"] = hashes
                manifest["frozen_source_hashes_sha256"] = sha256(json.dumps(
                    hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                if mutate:
                    mutate(project)
                completed = subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive",
                     "-File", str(project / "run.ps1"), "-ResumeDiscovery"],
                    cwd=project, env=environment, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120)
                contents = log.read_text(encoding="utf-8") if log.exists() else ""
                if expect_no_ledger:
                    self.assertFalse((results / "model_request_budget_100.sqlite3").exists())
                if expect_selection:
                    self.assertEqual(completed.returncode, 0,
                                     (completed.stdout or "") + (completed.stderr or ""))
                    self.assertEqual(contents, "select")
                else:
                    self.assertNotEqual(completed.returncode, 0,
                                        (completed.stdout or "") + (completed.stderr or ""))
                    self.assertNotIn("probe", contents)
                    self.assertNotIn("calibrate", contents)

        run_resume_case("failed")
        run_resume_case("requesting")
        run_resume_case("completed", lambda project: (project / "config.yaml").write_text(
            (project / "config.yaml").read_text(encoding="utf-8") + "\n# changed\n",
            encoding="utf-8"))
        run_resume_case("completed", lambda project: (project / "docker.cmd").write_text(
            "@echo off\nexit /b 1\n", encoding="ascii"), expect_no_ledger=True)
        run_resume_case("completed", expect_selection=True)

        from run_experiment import summarize_previous_run
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            run = Path(directory)
            (run / "research_id.txt").write_text("study-x\n", encoding="utf-8")
            journal = [{"iteration": 1, "status": "rejected", "error": "invalid path",
                        "parent_id": "p0", "error_code": "path_semantics",
                        "stages": [{"stage": "evaluation", "status": "failed"}]}]
            (run / "iteration_journal.jsonl").write_text(
                "\n".join(json.dumps(item) for item in journal) + "\n", encoding="utf-8")
            (run / "checkpoints" / "checkpoint_1").mkdir(parents=True)
            summary = summarize_previous_run(run)
            self.assertEqual(summary["research_id"], "study-x")
            self.assertEqual(Path(summary["latest_checkpoint"]).as_posix(),
                             "checkpoints/checkpoint_1")
            self.assertEqual(summary["recent_iterations"][0]["failure"]["error_code"],
                             "path_semantics")
            self.assertIn("never appended", summary["prompt_policy"])

    def test_powershell_request_usage_handles_total_and_run_id(self):
        powershell = next((candidate for candidate in (
            "powershell.exe", "pwsh.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ) if shutil.which(candidate) or Path(candidate).is_file()), None)
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        from openevolve.utils.request_budget import initialize_request_budget, reserve_request
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            ledger = Path(directory) / "request_budget.sqlite3"
            initialize_request_budget(ledger, "offline-test", 100)
            with patch.dict(os.environ, {"OPENEVOLVE_REQUEST_BUDGET_DB": str(ledger)}):
                reserve_request("test", run_id="run-a")
                reserve_request("test", run_id="run-a")
                reserve_request("test", run_id="run-b")
            script = (ROOT / "run.ps1").read_text(encoding="utf-8-sig")
            helper = "function Get-RequestUsageTotal {" + script.split(
                "function Get-RequestUsageTotal {", 1)[1].split("$framework =", 1)[0]
            python_path = str(ROOT / ".venv" / "Scripts" / "python.exe")
            command = ("$venvPython = '" + python_path.replace("'", "''") + "'; "
                       + helper + "; Get-RequestUsageTotal; "
                       + "Get-RequestUsageTotal -RunId 'run-a'")
            environment = os.environ.copy()
            environment["OPENEVOLVE_REQUEST_BUDGET_DB"] = str(ledger)
            environment["PYTHONPATH"] = str(ROOT.parent / "openevolve")
            completed = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
                cwd=ROOT, env=environment, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.split(), ["3", "2"])

    def test_powershell_orchestration_counts_each_run_and_resume(self):
        powershell = next((candidate for candidate in (
            "powershell.exe", "pwsh.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ) if shutil.which(candidate) or Path(candidate).is_file()), None)
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory) / "experiment"
            shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns(
                ".venv", "results", "tests", "__pycache__", "tmp*"))
            shutil.copytree(ROOT.parent / "openevolve", Path(directory) / "openevolve")
            (project / "tests").mkdir()
            (project / "tests" / "test_smoke.py").write_text(
                "import unittest\nclass SmokeTest(unittest.TestCase):\n"
                "    def test_smoke(self): self.assertTrue(True)\n", encoding="ascii")
            (project / "probe_api.py").write_text(
                "print('deepseek-ai/DeepSeek-V3.2')\n", encoding="ascii")
            (project / "calibrate_api.py").write_text("pass\n", encoding="ascii")
            (project / "select_discovery.py").write_text("pass\n", encoding="ascii")
            (project / "run_experiment.py").write_text(
                "import json, os, sys\nfrom pathlib import Path\n"
                "from openevolve.utils.request_budget import reserve_request\n"
                "run_id = os.environ['TN_RUN_ID']\n"
                "run = Path('results') / ('evolve_' + run_id)\nrun.mkdir(exist_ok=True)\n"
                "(run / 'run_id.txt').write_text(run_id, encoding='utf-8')\n"
                "with Path('counts.jsonl').open('a', encoding='utf-8') as out:\n"
                "    out.write(json.dumps({'run_id': run_id, "
                "'before': int(os.environ['TN_RUN_REQUEST_COUNT_BEFORE']), "
                "'resume': '--resume-run' in sys.argv}) + '\\n')\n"
                "if '--resume-run' not in sys.argv: reserve_request('chat_completion')\n"
                "(run / 'development_report.json').write_text('{}', encoding='utf-8')\n",
                encoding="ascii")
            script = (project / "run.ps1").read_text(encoding="utf-8-sig")
            script = script.replace(
                "$venvPython = Join-Path $project '.venv\\Scripts\\python.exe'",
                "$venvPython = $env:TN_PYTHON")
            (project / "run.ps1").write_text(script, encoding="utf-8")
            from tnlab import freeze
            with patch.object(freeze, "ROOT", project):
                source_hash = freeze.image_source_hash()
            (project / "docker.cmd").write_text(
                "@echo off\n"
                'echo [{"Config":{"Labels":{"org.tnlab.source-sha256":"'
                + source_hash + '"}}}]\n', encoding="ascii")
            environment = os.environ.copy()
            environment.update({
                "TN_PYTHON": str(ROOT / ".venv" / "Scripts" / "python.exe"),
                "OPENAI_API_KEY": "offline-test-only",
                "PYTHONPATH": str(Path(directory) / "openevolve"),
                "PATH": str(project) + os.pathsep + environment.get("PATH", ""),
            })
            def launch(*args):
                return subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-File",
                     str(project / "run.ps1"), *args],
                    cwd=project, env=environment, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120)
            completed = launch()
            self.assertEqual(completed.returncode, 0,
                             (completed.stdout or "") + (completed.stderr or ""))
            counts = [json.loads(line) for line in (project / "counts.jsonl").read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual([row["before"] for row in counts], list(range(5)))
            self.assertEqual(len({row["run_id"] for row in counts}), 5)
            run = project / "results" / ("evolve_" + counts[0]["run_id"])
            (run / "development_report.json").unlink()
            resumed = launch("-ResumeRun", str(run))
            self.assertEqual(resumed.returncode, 0,
                             (resumed.stdout or "") + (resumed.stderr or ""))
            last = json.loads((project / "counts.jsonl").read_text(
                encoding="utf-8").splitlines()[-1])
            self.assertEqual((last["before"], last["resume"]), (4, True))

    def test_powershell_calibration_failure_is_terminal_and_recorded(self):
        powershell = next((candidate for candidate in (
            "powershell.exe", "pwsh.exe",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        ) if shutil.which(candidate) or Path(candidate).is_file()), None)
        if powershell is None:
            self.skipTest("Windows PowerShell is unavailable")
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory) / "experiment"
            shutil.copytree(ROOT, project, ignore=shutil.ignore_patterns(
                ".venv", "results", "tests", "__pycache__", "tmp*"))
            shutil.copytree(ROOT.parent / "openevolve", Path(directory) / "openevolve")
            (project / "tests").mkdir()
            (project / "tests" / "test_smoke.py").write_text(
                "import unittest\nclass SmokeTest(unittest.TestCase):\n"
                "    def test_smoke(self): self.assertTrue(True)\n", encoding="ascii")
            (project / "probe_api.py").write_text(
                "from pathlib import Path\n"
                "with Path('fake_calls.txt').open('a') as log: log.write('probe\\n')\n"
                "print('deepseek-ai/DeepSeek-V3.2')\n", encoding="ascii")
            (project / "calibrate_api.py").write_text(
                "from pathlib import Path\nimport sys\n"
                "with Path('fake_calls.txt').open('a') as log: log.write('calibrate\\n')\n"
                "sys.exit(1)\n", encoding="ascii")
            (project / "run_experiment.py").write_text(
                "raise RuntimeError('discovery must not start')\n", encoding="ascii")
            script = (project / "run.ps1").read_text(encoding="utf-8-sig")
            script = script.replace(
                "$venvPython = Join-Path $project '.venv\\Scripts\\python.exe'",
                "$venvPython = $env:TN_PYTHON")
            (project / "run.ps1").write_text(script, encoding="utf-8")
            from tnlab import freeze
            with patch.object(freeze, "ROOT", project):
                source_hash = freeze.image_source_hash()
            (project / "docker.cmd").write_text(
                "@echo off\n"
                'echo [{"Config":{"Labels":{"org.tnlab.source-sha256":"'
                + source_hash + '"}}}]\n', encoding="ascii")
            from hashlib import sha256
            with patch.object(freeze, "ROOT", project):
                hashes = freeze.frozen_file_hashes()
            results = project / "results"
            results.mkdir()
            registration = project / "notes" / "formal_registration_2026-10.md"
            manifest = {
                "research_id": "tensor-path-discovery-2026-10",
                "registration_sha256": sha256(registration.read_bytes()).hexdigest(),
                "frozen_source_hashes": hashes,
                "frozen_source_hashes_sha256": sha256(json.dumps(
                    hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "run_ids": [f"run-{index}" for index in range(5)],
                "model": None,
                "calibration_run_id": "calibration-test",
                "calibration_status": "pending",
                "calibration_directory": str(results / "calibration"),
                "runs": [{"run_id": f"run-{index}", "status": "pending"}
                         for index in range(5)],
            }
            (results / "discovery_run_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            environment = os.environ.copy()
            environment.update({
                "TN_PYTHON": str(ROOT / ".venv" / "Scripts" / "python.exe"),
                "OPENAI_API_KEY": "offline-test-only",
                "PYTHONPATH": str(Path(directory) / "openevolve"),
                "PATH": str(project) + os.pathsep + environment.get("PATH", ""),
            })
            def launch(*args):
                return subprocess.run(
                    [powershell, "-NoProfile", "-NonInteractive", "-File",
                     str(project / "run.ps1"), *args],
                    cwd=project, env=environment, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=120)
            first = launch("-ResumeDiscovery")
            self.assertNotEqual(first.returncode, 0)
            self.assertIn("Machine-checkable calibration failed", first.stderr)
            self.assertNotIn("ExceptionWhenSetting", first.stderr)
            manifest = json.loads((project / "results" / "discovery_run_manifest.json")
                                  .read_text(encoding="utf-8-sig"))
            self.assertEqual(manifest["calibration_status"], "failed")
            self.assertIn("Machine-checkable calibration failed", manifest["calibration_error"])
            self.assertEqual(len(set(manifest["run_ids"])), 5)
            self.assertEqual([item["status"] for item in manifest["runs"]], ["pending"] * 5)
            self.assertEqual((project / "fake_calls.txt").read_text(encoding="ascii"),
                             "probe\ncalibrate\n")
            second = launch("-ResumeDiscovery")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("preregistered one-shot rule", second.stderr)
            self.assertEqual((project / "fake_calls.txt").read_text(encoding="ascii"),
                             "probe\ncalibrate\n")
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(
                    project / "results" / "model_request_budget_100.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 0)

    def test_previous_run_summary_is_attached_as_audit_artifact(self):
        from run_experiment import attach_previous_run_summary
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(dir=ROOT) as directory:
            project = Path(directory)
            results = project / "results"
            results.mkdir()
            previous, current = results / "evolve_old", results / "evolve_new"
            previous.mkdir()
            current.mkdir()
            (previous / "iteration_journal.jsonl").write_text(
                json.dumps({"iteration": 2, "status": "rejected", "error": "case failed"}) + "\n",
                encoding="utf-8")
            with patch("run_experiment.ROOT", project):
                checksum = attach_previous_run_summary(current)
            saved = current / "previous_run_summary.json"
            self.assertEqual(checksum["sha256"], __import__("hashlib").sha256(
                saved.read_bytes()).hexdigest())
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["iterations_recorded"], 1)

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
