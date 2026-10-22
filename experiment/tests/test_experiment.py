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
CHAIN = {"name": "chain", "inputs": [["a", "b"], ["b", "c"], ["c", "d"]],
         "output": ["a", "d"], "sizes": {"a": 2, "b": 3, "c": 4, "d": 5}}


class InstanceTests(unittest.TestCase):
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
        self.assertEqual(result.metrics["failure_count"], 4)
        self.assertEqual(result.metrics["combined_score"], FAILURE_SCORE)

    def test_candidate_exception_and_invalid_path(self):
        from openevolve_evaluator import evaluate_case
        case = CHAIN
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            file = Path(directory) / "bad.py"
            file.write_text("def find_path(*args, **kwargs):\n    raise RuntimeError('broken')\n")
            self.assertIn("error", evaluate_case(file, case))
            file.write_text("def find_path(*args, **kwargs):\n    return [(0, 0), (0, 1)]\n")
            self.assertIn("error", evaluate_case(file, case))

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


if __name__ == "__main__":
    unittest.main()
