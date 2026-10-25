"""
Test that artifacts produced while evaluating the INITIAL program are stored.

Regression test for the bug where the controller evaluated the initial program
(populating the evaluator's pending artifacts) but never retrieved/stored them,
unlike evolved programs. All initial-program artifacts (stderr, failure logs, LLM
feedback, etc.) were therefore silently dropped.

See: https://github.com/algorithmicsuperintelligence/openevolve/pull/462
"""

import asyncio
import logging
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

# Dummy API key so LLM ensembles initialize without a real key
os.environ.setdefault("OPENAI_API_KEY", "test")

from openevolve.config import Config
from openevolve.controller import OpenEvolve


class TestInitialProgramArtifacts(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

        # Initial program with an evolve block
        self.program_file = os.path.join(self.test_dir, "initial_program.py")
        with open(self.program_file, "w") as f:
            f.write(
                "# EVOLVE-BLOCK-START\n"
                "def solve(x):\n"
                "    return x + 1\n"
                "# EVOLVE-BLOCK-END\n"
            )

        # Evaluator returns metrics AND artifacts via EvaluationResult
        self.eval_file = os.path.join(self.test_dir, "evaluator.py")
        with open(self.eval_file, "w") as f:
            f.write(
                "from openevolve.evaluation_result import EvaluationResult\n"
                "\n"
                "def evaluate(program_path):\n"
                "    return EvaluationResult(\n"
                "        metrics={'combined_score': 0.7},\n"
                "        artifacts={'stderr': 'initial-program-warning', 'note': 'hello'},\n"
                "    )\n"
            )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _make_config(self):
        config = Config()
        config.max_iterations = 1
        config.database.in_memory = True
        config.database.db_path = None
        # Keep artifacts inline in the DB for easy retrieval
        config.prompt.include_artifacts = True
        return config

    def test_run_resource_rebuild_failure_closes_existing_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "resource-rebuild-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch.object(controller, "_ensure_run_resources", side_effect=RuntimeError("rebuild failed")):
            with self.assertRaisesRegex(RuntimeError, "rebuild failed"):
                asyncio.run(controller.run(iterations=1))
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_parallel_controller_construction_failure_closes_run_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "controller-construction-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch(
            "openevolve.controller.ProcessParallelController",
            side_effect=RuntimeError("controller construction failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "controller construction failed"):
                asyncio.run(controller.run(iterations=1))
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_parallel_controller_start_failure_closes_run_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "controller-start-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch("openevolve.controller.ProcessParallelController") as mock_ppc:
            mock_ppc.return_value.start.side_effect = RuntimeError("controller start failed")
            with self.assertRaisesRegex(RuntimeError, "controller start failed"):
                asyncio.run(controller.run(iterations=1))
        self.assertIsNone(controller.parallel_controller)
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_initial_program_artifacts_are_stored(self):
        config = self._make_config()
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=config,
            output_dir=os.path.join(self.test_dir, "out"),
        )

        # Neutralize the parallel evolution loop - we only want the initial-program
        # handling in run() to execute.
        with (
            patch.object(
                controller, "_run_evolution_with_checkpoints", new=AsyncMock(return_value=None)
            ),
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            # start()/stop()/request_shutdown() are called on the instance
            instance = mock_ppc.return_value
            instance.start.return_value = None
            instance.stop.return_value = None

            asyncio.run(controller.run(iterations=1))

        # Exactly one (initial) program should have been added
        self.assertEqual(len(controller.database.programs), 1)
        initial_id = next(iter(controller.database.programs))

        artifacts = controller.database.get_artifacts(initial_id)
        self.assertIsNotNone(artifacts, "Initial program artifacts must be stored, not dropped")
        self.assertEqual(artifacts.get("stderr"), "initial-program-warning")
        self.assertEqual(artifacts.get("note"), "hello")

    def test_constructor_failure_closes_run_logging(self):
        before = list(logging.getLogger().handlers)
        with patch.object(OpenEvolve, "_setup_manual_mode_queue", side_effect=RuntimeError("queue failed")):
            with self.assertRaisesRegex(RuntimeError, "queue failed"):
                OpenEvolve(
                    initial_program_path=self.program_file,
                    evaluation_file=self.eval_file,
                    config=self._make_config(),
                    output_dir=os.path.join(self.test_dir, "constructor-failure-out"),
                )
        self.assertEqual(logging.getLogger().handlers, before)

    def test_constructor_language_failure_closes_run_logging(self):
        before = list(logging.getLogger().handlers)
        with patch(
            "openevolve.controller.extract_code_language",
            side_effect=RuntimeError("language detection failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "language detection failed"):
                OpenEvolve(
                    initial_program_path=self.program_file,
                    evaluation_file=self.eval_file,
                    config=self._make_config(),
                    output_dir=os.path.join(self.test_dir, "language-failure-out"),
                )
        self.assertEqual(logging.getLogger().handlers, before)

    def test_checkpoint_load_failure_closes_run_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "checkpoint-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        checkpoint_path = os.path.join(self.test_dir, "checkpoint.json")
        with open(checkpoint_path, "w") as stream:
            stream.write("{}");
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch.object(controller, "_load_checkpoint", side_effect=RuntimeError("checkpoint failed")):
            with self.assertRaisesRegex(RuntimeError, "checkpoint failed"):
                asyncio.run(controller.run(iterations=1, checkpoint_path=checkpoint_path))
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_initial_program_construction_failure_closes_run_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "construction-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch("openevolve.controller.Program", side_effect=RuntimeError("program failed")):
            with self.assertRaisesRegex(RuntimeError, "program failed"):
                asyncio.run(controller.run(iterations=1))
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_initial_program_database_failure_closes_run_resources(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "database-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer
        with patch.object(controller.database, "add", side_effect=RuntimeError("database failed")):
            with self.assertRaisesRegex(RuntimeError, "database failed"):
                asyncio.run(controller.run(iterations=1))
        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        self.assertEqual(controller._run_logging_handlers, [])
        tracer.close.assert_called_once()

    def test_initial_evaluation_failure_closes_run_logging(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        controller.evaluator.evaluate_program = AsyncMock(side_effect=RuntimeError("evaluation failed"))

        with self.assertRaisesRegex(RuntimeError, "evaluation failed"):
            asyncio.run(controller.run(iterations=1))

        self.assertFalse(set(handlers).intersection(logging.getLogger().handlers))
        file_handlers = [handler for handler in handlers if isinstance(handler, logging.FileHandler)]
        self.assertTrue(file_handlers)
        self.assertTrue(all(handler.stream is None for handler in file_handlers))
        self.assertIsNone(controller.parallel_controller)

    def test_primary_run_failure_is_not_masked_by_cleanup_failure(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "primary-failure-out"),
        )
        controller.evolution_tracer = unittest.mock.Mock()
        controller.evolution_tracer.close.side_effect = RuntimeError("tracer cleanup failed")

        with (
            patch.object(
                controller,
                "_run_evolution_with_checkpoints",
                new=AsyncMock(side_effect=RuntimeError("primary failure")),
            ),
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            mock_ppc.return_value.start.return_value = None
            mock_ppc.return_value.stop.side_effect = RuntimeError("stop cleanup failed")
            with self.assertRaisesRegex(RuntimeError, "primary failure"):
                asyncio.run(controller.run(iterations=1))

        self.assertIsNone(controller.parallel_controller)
        self.assertEqual(controller._run_logging_handlers, [])

    def test_parallel_stop_failure_still_closes_tracer_and_logging(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "stop-failure-out"),
        )
        handlers = list(controller._run_logging_handlers)
        tracer = unittest.mock.Mock()
        controller.evolution_tracer = tracer

        with (
            patch.object(
                controller, "_run_evolution_with_checkpoints", new=AsyncMock(return_value=None)
            ),
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            mock_ppc.return_value.start.return_value = None
            mock_ppc.return_value.stop.side_effect = RuntimeError("stop failed")
            with self.assertRaisesRegex(RuntimeError, "stop failed"):
                asyncio.run(controller.run(iterations=1))

        tracer.close.assert_called_once()
        file_handlers = [handler for handler in handlers if isinstance(handler, logging.FileHandler)]
        self.assertTrue(file_handlers)
        self.assertTrue(all(handler.stream is None for handler in file_handlers))

    def test_successful_run_reopens_resources_for_retry(self):
        config = self._make_config()
        config.evolution_trace.enabled = True
        config.evolution_trace.output_path = os.path.join(self.test_dir, "trace.jsonl")
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=config,
            output_dir=os.path.join(self.test_dir, "retry-out"),
        )

        with (
            patch.object(controller, "_setup_logging", wraps=controller._setup_logging) as setup_logging,
            patch.object(
                controller, "_create_evolution_tracer", wraps=controller._create_evolution_tracer
            ) as create_tracer,
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            mock_ppc.return_value.start.return_value = None
            mock_ppc.return_value.stop.return_value = None
            mock_ppc.return_value.run_evolution = AsyncMock(return_value=None)
            asyncio.run(controller.run(iterations=0))
            asyncio.run(controller.run(iterations=0))

        self.assertEqual(setup_logging.call_count, 1)
        create_tracer.assert_called_once()
        self.assertIsNone(controller.evolution_tracer)

    def test_successful_run_logs_completion_before_closing_handlers(self):
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=self._make_config(),
            output_dir=os.path.join(self.test_dir, "success-out"),
        )
        handlers = list(controller._run_logging_handlers)

        with (
            patch.object(
                controller, "_run_evolution_with_checkpoints", new=AsyncMock(return_value=None)
            ),
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            mock_ppc.return_value.start.return_value = None
            mock_ppc.return_value.stop.return_value = None
            asyncio.run(controller.run(iterations=1))

        log_path = os.path.join(self.test_dir, "success-out", "logs")
        log_files = [name for name in os.listdir(log_path) if name.endswith(".log")]
        self.assertEqual(len(log_files), 1)
        with open(os.path.join(log_path, log_files[0]), encoding="utf-8") as stream:
            self.assertIn("Evolution complete", stream.read())
        file_handlers = [handler for handler in handlers if isinstance(handler, logging.FileHandler)]
        self.assertTrue(file_handlers)
        self.assertTrue(all(handler.stream is None for handler in file_handlers))

    def test_no_artifacts_when_evaluator_returns_none(self):
        """When the evaluator returns no artifacts, nothing is stored (and no crash)."""
        # Overwrite evaluator to return a bare metrics dict (no artifacts)
        with open(self.eval_file, "w") as f:
            f.write("def evaluate(program_path):\n    return {'combined_score': 0.7}\n")

        config = self._make_config()
        controller = OpenEvolve(
            initial_program_path=self.program_file,
            evaluation_file=self.eval_file,
            config=config,
            output_dir=os.path.join(self.test_dir, "out"),
        )

        with (
            patch.object(
                controller, "_run_evolution_with_checkpoints", new=AsyncMock(return_value=None)
            ),
            patch("openevolve.controller.ProcessParallelController") as mock_ppc,
        ):
            mock_ppc.return_value.start.return_value = None
            mock_ppc.return_value.stop.return_value = None
            asyncio.run(controller.run(iterations=1))

        self.assertEqual(len(controller.database.programs), 1)
        initial_id = next(iter(controller.database.programs))
        artifacts = controller.database.get_artifacts(initial_id)
        self.assertEqual(artifacts, {}, "No artifacts should be stored when evaluator returns none")


if __name__ == "__main__":
    unittest.main()
