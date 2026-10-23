"""
Process-based parallel controller for true parallelism
"""

import asyncio
import difflib
import hashlib
import json
import logging
import multiprocessing as mp
import pickle
import signal
import time
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, fields
from numbers import Integral
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openevolve.config import Config
from openevolve.database import Program, ProgramDatabase
from openevolve.selection import IslandSelectionContext, IslandSelector, IslandState
from openevolve.utils.metrics_utils import safe_numeric_average

logger = logging.getLogger(__name__)

_worker_event_loop = None


def _recent_failure_feedback(programs, artifacts, limit=2):
    """Give the next generation concrete errors from recent invalid programs."""
    failed = sorted(
        (p for p in programs if p.metrics.get("failure_count", 0) > 0),
        key=lambda p: p.iteration_found or 0,
        reverse=True,
    )


    notes = []
    for program in failed[:limit]:
        payload = artifacts.get(program.id, {}).get("case_results.json")
        if not payload:
            continue
        try:
            records = json.loads(payload)
        except (TypeError, ValueError):
            continue
        errors = []
        for record in records:
            message = record.get("error")
            if message and record.get("detail"):
                detail = record["detail"].splitlines()[-1][:240]
                message = f"{message}: {detail}"
            failure_class = record.get("failure_class", "unknown")
            if message:
                message = f"[{failure_class}] {message}"
            if message and message not in errors:
                errors.append(message)
        if errors:
            notes.append(f"Iteration {program.iteration_found}: " + "; ".join(errors[:3]))
    if not notes:
        return ""
    return (
        "\n\n## Recent invalid candidate feedback\n"
        "Fix these errors before seeking lower contraction cost. "
        "A failed candidate is not an improvement.\n" + "\n".join(notes)
    )


def format_pipeline_feedback(errors, limit=3):
    """Format failures that happened before a program entered the database."""
    if not errors:
        return ""
    return "\n\n## Recent pipeline failures\n" + "\n".join(
        f"Iteration {item['iteration']}: {item['error']}"
        for item in errors[-limit:]
    )


def candidate_failure_reason(metrics, artifacts):
    """Return a concrete rejection reason for failed domain evaluations."""
    if not metrics or metrics.get("failure_count", 0) <= 0:
        return ""
    payload = (artifacts or {}).get("case_results.json")
    try:
        records = json.loads(payload) if payload else []
    except (TypeError, ValueError):
        records = []
    details = []
    for item in records:
        if not isinstance(item, dict) or not item.get("error"):
            continue
        detail = str(item.get("detail") or item["error"])
        failure_class = item.get("failure_class", "unknown")
        # Python tracebacks put the actionable exception on the final line.
        last_line = (detail.strip().splitlines() or [str(item["error"])])[-1]
        details.append(f"{failure_class}/{item.get('error_code', item['error'])}: "
                       f"{last_line[:240]}")
    return "candidate evaluation failed: " + ("; ".join(dict.fromkeys(details[:3]))
                                              if details else "unknown error")


def _change_summary(parent_code, child_code):
    """Return compact, deterministic source-change metadata for the journal."""
    if not isinstance(parent_code, str) or not isinstance(child_code, str):
        return None
    parent_lines = parent_code.splitlines()
    child_lines = child_code.splitlines()
    changed = list(difflib.ndiff(parent_lines, child_lines))
    added = sum(line.startswith("+ ") for line in changed)
    removed = sum(line.startswith("- ") for line in changed)
    return {
        "parent_sha256": hashlib.sha256(parent_code.encode("utf-8")).hexdigest(),
        "child_sha256": hashlib.sha256(child_code.encode("utf-8")).hexdigest(),
        "parent_lines": len(parent_lines),
        "child_lines": len(child_lines),
        "added_lines": added,
        "removed_lines": removed,
        "changed_lines": added + removed,
    }


class _CandidateRejected(Exception):
    """Stop processing an iteration after admission rejects its child."""


@dataclass
class SerializableResult:
    """Result that can be pickled and sent between processes"""

    child_program_dict: Optional[Dict[str, Any]] = None
    parent_id: Optional[str] = None
    iteration_time: float = 0.0
    prompt: Optional[Dict[str, str]] = None
    llm_response: Optional[str] = None
    artifacts: Optional[Dict[str, Any]] = None
    iteration: int = 0
    error: Optional[str] = None
    target_island: Optional[int] = None  # Island where child should be placed
    token_usage: Optional[Dict[str, Any]] = None
    stages: Optional[List[Dict[str, Any]]] = None
    error_code: Optional[str] = None


def _worker_init(config_dict: dict, evaluation_file: str, parent_env: dict = None) -> None:
    """Initialize worker process with necessary components"""
    import os

    # Set environment from parent process
    if parent_env:
        os.environ.update(parent_env)

    global _worker_config
    global _worker_evaluation_file
    global _worker_evaluator
    global _worker_llm_ensemble
    global _worker_prompt_sampler
    global _worker_event_loop

    # Store config for later use
    # Reconstruct Config object from nested dictionaries
    from openevolve.config import (
        Config,
        DatabaseConfig,
        EvaluatorConfig,
        EvolutionTraceConfig,
        LLMConfig,
        LLMModelConfig,
        PromptConfig,
    )

    # Reconstruct model objects
    models = [LLMModelConfig(**m) for m in config_dict["llm"]["models"]]
    evaluator_models = [LLMModelConfig(**m) for m in config_dict["llm"]["evaluator_models"]]

    # Create LLM config with models
    llm_dict = config_dict["llm"].copy()
    llm_dict["models"] = models
    llm_dict["evaluator_models"] = evaluator_models
    llm_config = LLMConfig(**llm_dict)

    # Create other configs
    prompt_config = PromptConfig(**config_dict["prompt"])
    database_config = DatabaseConfig(**config_dict["database"])
    evaluator_config = EvaluatorConfig(**config_dict["evaluator"])
    evolution_trace_config = EvolutionTraceConfig(**config_dict["evolution_trace"])

    _worker_config = Config(
        llm=llm_config,
        prompt=prompt_config,
        database=database_config,
        evaluator=evaluator_config,
        evolution_trace=evolution_trace_config,
        **{
            k: v
            for k, v in config_dict.items()
            if k not in ["llm", "prompt", "database", "evaluator", "evolution_trace"]
        },
    )
    _worker_evaluation_file = evaluation_file

    # These will be lazily initialized on first use
    _worker_evaluator = None
    _worker_llm_ensemble = None
    _worker_prompt_sampler = None
    _worker_event_loop = None


def _worker_run(coro):
    """Run async worker operations on one loop for the worker lifetime."""
    global _worker_event_loop
    import asyncio

    if _worker_event_loop is None or _worker_event_loop.is_closed():
        _worker_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_event_loop)
    return _worker_event_loop.run_until_complete(coro)


def _lazy_init_worker_components():
    """Lazily initialize expensive components on first use"""
    global _worker_evaluator
    global _worker_llm_ensemble
    global _worker_prompt_sampler

    if _worker_llm_ensemble is None:
        from openevolve.llm.ensemble import LLMEnsemble

        _worker_llm_ensemble = LLMEnsemble(_worker_config.llm.models)

    if _worker_prompt_sampler is None:
        from openevolve.prompt.sampler import PromptSampler

        _worker_prompt_sampler = PromptSampler(_worker_config.prompt)

    if _worker_evaluator is None:
        from openevolve.evaluator import Evaluator
        from openevolve.llm.ensemble import LLMEnsemble
        from openevolve.prompt.sampler import PromptSampler

        # Create evaluator-specific components
        evaluator_llm = LLMEnsemble(_worker_config.llm.evaluator_models)
        evaluator_prompt = PromptSampler(_worker_config.prompt)
        evaluator_prompt.set_templates("evaluator_system_message")

        _worker_evaluator = Evaluator(
            _worker_config.evaluator,
            _worker_evaluation_file,
            evaluator_llm,
            evaluator_prompt,
            database=None,  # No shared database in worker
            suffix=getattr(_worker_config, "file_suffix", ".py"),
        )


def _run_iteration_worker(
    iteration: int, db_snapshot: Dict[str, Any], parent_id: str, inspiration_ids: List[str]
) -> SerializableResult:
    """Run a single iteration in a worker process"""
    try:
        # Lazy initialization
        _lazy_init_worker_components()

        # Reconstruct programs from snapshot
        programs = {pid: Program(**prog_dict) for pid, prog_dict in db_snapshot["programs"].items()}

        parent = programs[parent_id]
        inspirations = [programs[pid] for pid in inspiration_ids if pid in programs]

        # Get parent artifacts if available
        parent_artifacts = db_snapshot["artifacts"].get(parent_id)

        # Get island-specific programs for context
        parent_island = parent.metadata.get("island", db_snapshot["current_island"])
        island_programs = [
            programs[pid] for pid in db_snapshot["islands"][parent_island] if pid in programs
        ]

        # Sort by metrics for top programs
        island_programs.sort(
            key=lambda p: p.metrics.get("combined_score", safe_numeric_average(p.metrics)),
            reverse=True,
        )

        # Use config values for limits instead of hardcoding
        # Programs for LLM display (includes both top and diverse for inspiration)
        programs_for_prompt = island_programs[
            : _worker_config.prompt.num_top_programs + _worker_config.prompt.num_diverse_programs
        ]
        # Best programs only (for previous attempts section, focused on top performers)
        best_programs_only = island_programs[: _worker_config.prompt.num_top_programs]

        # Build prompt
        if _worker_config.prompt.programs_as_changes_description:
            parent_changes_desc = (
                parent.changes_description or _worker_config.prompt.initial_changes_description
            )
            child_changes_desc = parent_changes_desc
        else:
            parent_changes_desc = None
            child_changes_desc = None

        prompt = _worker_prompt_sampler.build_prompt(
            current_program=parent.code,
            parent_program=parent.code,
            program_metrics=parent.metrics,
            previous_programs=[p.to_dict() for p in best_programs_only],
            top_programs=[p.to_dict() for p in programs_for_prompt],
            inspirations=[p.to_dict() for p in inspirations],
            language=_worker_config.language,
            evolution_round=iteration,
            diff_based_evolution=_worker_config.diff_based_evolution,
            program_artifacts=parent_artifacts,
            feature_dimensions=db_snapshot.get("feature_dimensions", []),
            current_changes_description=parent_changes_desc,
            island_id=db_snapshot.get("sampling_island"),
        )
        prompt["user"] += _recent_failure_feedback(island_programs, db_snapshot["artifacts"])
        prompt["user"] += format_pipeline_feedback(
            db_snapshot.get("recent_iteration_errors", []))

        iteration_start = time.time()
        stage_started = time.monotonic()
        stages = []
        llm_response = None
        token_usage = None

        def reject(error, code):
            return SerializableResult(
                error=error, error_code=code, iteration=iteration,
                prompt=prompt, llm_response=llm_response, token_usage=token_usage,
                stages=stages + [{"stage": "model_request" if code == "model_error"
                                   else "patch_parse_apply", "status": "failed",
                                   "error_code": code,
                                   "seconds": time.monotonic() - stage_started}],
            )

        # Generate code modification (sync wrapper for async)
        try:
            llm_response = _worker_run(
                _worker_llm_ensemble.generate_with_context(
                    system_message=prompt["system"],
                    messages=[{"role": "user", "content": prompt["user"]}],
                )
            )
            token_usage = getattr(_worker_llm_ensemble, "last_usage", None)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return reject(f"LLM generation failed: {e}", "model_error")

        # Check for None response
        if llm_response is None:
            return reject("LLM returned None response", "model_error")

        stages.append({"stage": "model_request", "status": "passed",
                       "seconds": time.monotonic() - stage_started})
        stage_started = time.monotonic()

        # Parse response based on evolution mode
        if _worker_config.diff_based_evolution:
            from openevolve.utils.code_utils import (
                apply_diff_blocks,
                extract_diffs,
                format_diff_summary,
                split_diffs_by_target,
            )

            try:
                diff_blocks = extract_diffs(llm_response, _worker_config.diff_pattern)
            except ValueError as exc:
                return reject(str(exc), "patch_parse_error")
            if not diff_blocks:
                return reject("No valid diffs found in response", "patch_parse_error")

            if _worker_config.prompt.programs_as_changes_description:
                try:
                    code_blocks, desc_blocks, _unmatched = split_diffs_by_target(
                        diff_blocks,
                        code_text=parent.code,
                        changes_description_text=parent_changes_desc,
                    )
                except Exception as e:
                    return reject(str(e), "patch_parse_error")

                child_code, _ = apply_diff_blocks(parent.code, code_blocks)
                child_changes_desc, desc_applied = apply_diff_blocks(
                    parent_changes_desc, desc_blocks
                )

                # Must update the previous changes description
                if (
                    desc_applied == 0
                    or not child_changes_desc.strip()
                    or child_changes_desc.strip() == parent_changes_desc.strip()
                ):
                    return reject("changes_description was not updated or empty, program is discarded",
                                  "patch_apply_error")

                changes_summary = format_diff_summary(
                    code_blocks,
                    max_line_len=_worker_config.prompt.diff_summary_max_line_len,
                    max_lines=_worker_config.prompt.diff_summary_max_lines,
                )
            else:
                # All diffs applied only to code
                child_code, applied = apply_diff_blocks(parent.code, diff_blocks)
                if applied == 0:
                    return reject(
                        f"None of the {len(diff_blocks)} SEARCH block(s) matched the parent program",
                        "patch_apply_error")
                if applied < len(diff_blocks):
                    logger.warning(
                        f"Iteration {iteration}: only {applied} of {len(diff_blocks)} "
                        "SEARCH block(s) matched the parent program"
                    )
                if child_code == parent.code:
                    return reject("Diff did not change the parent program", "patch_apply_error")
                changes_summary = format_diff_summary(
                    diff_blocks,
                    max_line_len=_worker_config.prompt.diff_summary_max_line_len,
                    max_lines=_worker_config.prompt.diff_summary_max_lines,
                )
        else:
            from openevolve.utils.code_utils import parse_full_rewrite

            new_code = parse_full_rewrite(llm_response, _worker_config.language)
            if not new_code:
                return reject("No valid code found in response", "patch_parse_error")

            if new_code == parent.code:
                return reject("Rewrite is identical to the parent program", "patch_apply_error")

            child_code = new_code
            changes_summary = "Full rewrite"

        # Revert edits made outside the EVOLVE-BLOCK regions if configured
        if _worker_config.enforce_evolve_blocks:
            from openevolve.utils.code_utils import enforce_evolve_blocks

            try:
                enforced_code = enforce_evolve_blocks(parent.code, child_code)
            except ValueError as exc:
                return reject(str(exc), "patch_apply_error")
            if enforced_code != child_code:
                logger.info(
                    f"Iteration {iteration}: reverted edits outside the EVOLVE-BLOCK regions"
                )
                child_code = enforced_code
                if child_code == parent.code:
                    return reject("All edits were outside the EVOLVE-BLOCK regions",
                                  "patch_apply_error")

        # Check code length
        if len(child_code) > _worker_config.max_code_length:
            return reject(
                f"Generated code exceeds maximum length ({len(child_code)} > {_worker_config.max_code_length})",
                "patch_apply_error")

        stages.append({"stage": "patch_parse_apply", "status": "passed",
                       "seconds": time.monotonic() - stage_started})
        stage_started = time.monotonic()

        # Evaluate the child program
        import uuid

        child_id = str(uuid.uuid4())
        child_metrics = _worker_run(_worker_evaluator.evaluate_program(child_code, child_id))

        # Get artifacts
        artifacts = _worker_evaluator.get_pending_artifacts(child_id)
        stages.extend(json.loads((artifacts or {}).get("pipeline_stages.json", "[]")))
        stages.append({"stage": "evaluation_total", "status": "failed"
                       if child_metrics.get("failure_count", 0) else "passed",
                       "seconds": time.monotonic() - stage_started})

        # Create child program
        child_program = Program(
            id=child_id,
            code=child_code,
            changes_description=child_changes_desc,
            language=_worker_config.language,
            parent_id=parent.id,
            generation=parent.generation + 1,
            metrics=child_metrics,
            iteration_found=iteration,
            metadata={
                "changes": changes_summary,
                "parent_metrics": parent.metrics,
                "island": parent_island,
                "token_usage": token_usage,
            },
        )

        iteration_time = time.time() - iteration_start

        # Get target island from snapshot (where child should be placed)
        target_island = db_snapshot.get("sampling_island")

        return SerializableResult(
            child_program_dict=child_program.to_dict(),
            parent_id=parent.id,
            iteration_time=iteration_time,
            prompt=prompt,
            llm_response=llm_response,
            artifacts=artifacts,
            iteration=iteration,
            target_island=target_island,
            token_usage=token_usage,
            stages=stages,
        )

    except Exception as e:
        logger.exception(f"Error in worker iteration {iteration}")
        return SerializableResult(error=str(e), iteration=iteration)


def _wait_for_processes(processes: tuple[mp.Process, ...], timeout: float) -> list[mp.Process]:
    """Wait for process handles to observe worker exits without blocking indefinitely."""
    deadline = time.monotonic() + timeout
    alive = list(processes)
    while alive:
        next_alive = []
        for process in alive:
            try:
                process.join(timeout=0)
                if process.is_alive():
                    next_alive.append(process)
            except (AssertionError, ValueError):
                continue
        alive = next_alive
        remaining = deadline - time.monotonic()
        if not alive or remaining <= 0:
            break
        time.sleep(min(0.001, remaining))
    return alive


def _terminate_process_pool(executor: ProcessPoolExecutor) -> None:
    """Cancel queued work and ensure all process-pool workers have exited."""
    # Python < 3.14 has no public force-shutdown API. Capture only this
    # executor's workers before shutdown clears its private process mapping.
    process_map = getattr(executor, "_processes", None) or {}
    processes = tuple(process_map.copy().values())
    terminate_workers = getattr(executor, "terminate_workers", None)

    if callable(terminate_workers):
        terminate_workers()
    else:
        executor.shutdown(wait=False, cancel_futures=True)
        for process in processes:
            try:
                if process.is_alive():
                    process.terminate()
            except (ProcessLookupError, ValueError):
                continue

    surviving_processes = _wait_for_processes(processes, timeout=1.0)
    for process in surviving_processes:
        try:
            process.kill()
        except (ProcessLookupError, ValueError):
            continue

    surviving_processes = _wait_for_processes(tuple(surviving_processes), timeout=1.0)
    if surviving_processes:
        logger.warning(
            "Process-pool workers did not exit: %s",
            [process.pid for process in surviving_processes],
        )


class ProcessParallelController:
    """Controller for process-based parallel evolution"""

    def __init__(
        self,
        config: Config,
        evaluation_file: str,
        database: ProgramDatabase,
        evolution_tracer=None,
        file_suffix: str = ".py",
        island_selector: Optional[IslandSelector] = None,
    ):
        self.config = config
        self.evaluation_file = evaluation_file
        self.database = database
        self.evolution_tracer = evolution_tracer
        self.file_suffix = file_suffix
        self.island_selector = island_selector

        self.executor: Optional[ProcessPoolExecutor] = None
        self.shutdown_event = mp.Event()
        self.early_stopping_triggered = False
        self.recent_iteration_errors: List[Dict[str, Any]] = []

        # Number of worker processes
        self.num_workers = config.evaluator.parallel_evaluations
        self.num_islands = config.database.num_islands

        logger.info(f"Initialized process parallel controller with {self.num_workers} workers")

    def _serialize_config(self, config: Config) -> dict:
        """Serialize config object to a dictionary that can be pickled"""
        # Manual serialization to handle nested objects properly

        # The asdict() call itself triggers the deepcopy which tries to serialize novelty_llm. Remove it first.
        config.database.novelty_llm = None

        # Forward every remaining top-level field automatically. Listing them by hand
        # let new fields fall back to their defaults in workers (issue #516)
        nested_sections = {"llm", "prompt", "database", "evaluator", "evolution_trace"}
        top_level = {
            f.name: getattr(config, f.name) for f in fields(Config) if f.name not in nested_sections
        }

        return {
            "llm": {
                "models": [asdict(m) for m in config.llm.models],
                "evaluator_models": [asdict(m) for m in config.llm.evaluator_models],
                "api_base": config.llm.api_base,
                "api_key": config.llm.api_key,
                "temperature": config.llm.temperature,
                "top_p": config.llm.top_p,
                "max_tokens": config.llm.max_tokens,
                "timeout": config.llm.timeout,
                "retries": config.llm.retries,
                "retry_delay": config.llm.retry_delay,
            },
            "prompt": asdict(config.prompt),
            "database": asdict(config.database),
            "evaluator": asdict(config.evaluator),
            "evolution_trace": asdict(config.evolution_trace),
            **top_level,
            "file_suffix": self.file_suffix,
        }

    def start(self) -> None:
        """Start the process pool"""
        # Convert config to dict for pickling
        # We need to be careful with nested dataclasses
        config_dict = self._serialize_config(self.config)

        # Pass current environment to worker processes
        import os
        import sys

        current_env = dict(os.environ)

        executor_kwargs = {
            "max_workers": self.num_workers,
            "initializer": _worker_init,
            "initargs": (config_dict, self.evaluation_file, current_env),
        }
        if sys.version_info >= (3, 11):
            logger.info(f"Set max {self.config.max_tasks_per_child} tasks per child")
            executor_kwargs["max_tasks_per_child"] = self.config.max_tasks_per_child
        elif self.config.max_tasks_per_child is not None:
            logger.warn(
                "max_tasks_per_child is only supported in Python 3.11+. "
                "Ignoring max_tasks_per_child and using spawn start method."
            )
            executor_kwargs["mp_context"] = mp.get_context("spawn")

        # Create process pool with initializer
        self.executor = ProcessPoolExecutor(**executor_kwargs)
        logger.info(f"Started process pool with {self.num_workers} processes")

    def stop(self) -> None:
        """Stop the process pool"""
        self.shutdown_event.set()

        executor = self.executor
        self.executor = None
        if executor:
            _terminate_process_pool(executor)

        logger.info("Stopped process pool")

    def request_shutdown(self) -> None:
        """Request graceful shutdown"""
        logger.info("Graceful shutdown requested...")
        self.shutdown_event.set()

    def _create_database_snapshot(self) -> Dict[str, Any]:
        """Create a serializable snapshot of the database state"""
        # Only include necessary data for workers
        snapshot = {
            "programs": {pid: prog.to_dict() for pid, prog in self.database.programs.items()},
            "islands": [list(island) for island in self.database.islands],
            "current_island": self.database.current_island,
            "feature_dimensions": self.database.config.feature_dimensions,
            "artifacts": {},  # Will be populated selectively
            "recent_iteration_errors": self.recent_iteration_errors[-5:],
        }

        # Include artifacts for programs that might be selected
        # This limits artifacts (execution outputs/errors) to avoid large snapshot sizes.
        # This does NOT affect program code - all programs are fully serialized above.
        # With max_artifact_bytes=20KB and population_size=1000, artifacts could be 20MB total,
        # which would significantly slow worker process initialization. The default limit of 100
        # keeps artifact data under 2MB while still providing execution context for recent programs.
        # Workers can still evolve properly as they have access to ALL program code.
        # Configure via database.max_snapshot_artifacts (None for unlimited).
        max_artifacts = self.database.config.max_snapshot_artifacts
        program_ids = list(self.database.programs.keys())
        if max_artifacts is not None:
            program_ids = program_ids[:max_artifacts]
        for pid in program_ids:
            artifacts = self.database.get_artifacts(pid)
            if artifacts:
                snapshot["artifacts"][pid] = artifacts

        return snapshot

    def _record_iteration(self, record: Dict[str, Any]) -> None:
        """Keep rejected iterations visible outside the population database."""
        import os
        from hashlib import sha256
        target = os.environ.get("OPENEVOLVE_ITERATION_JOURNAL")
        if not target:
            return
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = dict(record)
        prompt = record.get("prompt")
        if isinstance(prompt, dict):
            record["prompt_metadata"] = {
                key: {
                    "sha256": sha256(str(prompt.get(key, "")).encode("utf-8")).hexdigest(),
                    "characters": len(str(prompt.get(key, ""))),
                }
                for key in ("system", "user")
            }
        artifact_dir = path.parent / "pipeline_artifacts" / f"iteration_{record['iteration']:03d}"
        files = {}
        for field, filename in (("prompt", "prompt.json"),
                                ("llm_response", "model_response.txt"),
                                ("child_code", "candidate.py"),
                                ("source_diff", "source_diff.patch")):
            value = record.pop(field, None)
            if value is None:
                continue
            artifact_dir.mkdir(parents=True, exist_ok=True)
            content = (json.dumps(value, ensure_ascii=False, indent=2)
                       if field == "prompt" else str(value))
            destination = artifact_dir / filename
            destination.write_text(content, encoding="utf-8")
            files[field] = str(destination.relative_to(path.parent))
            if field == "child_code":
                record["candidate_sha256"] = sha256(content.encode("utf-8")).hexdigest()
        artifacts = record.pop("artifacts", None) or {}
        for name, content in artifacts.items():
            if name not in ("case_results.json", "pipeline_stages.json"):
                continue
            artifact_dir.mkdir(parents=True, exist_ok=True)
            destination = artifact_dir / name
            destination.write_text(str(content), encoding="utf-8")
            files[name] = str(destination.relative_to(path.parent))
        record["artifact_files"] = files
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _select_island(self, iteration: int, island_pending: Dict[int, List[int]]) -> int:
        """Ask a custom policy for an island using a read-only state snapshot."""
        stats = self.database.get_island_stats()
        context = IslandSelectionContext(
            iteration=iteration,
            pending_counts=tuple(len(island_pending[i]) for i in range(self.num_islands)),
            islands=tuple(
                IslandState(
                    population_size=stat["population_size"],
                    best_score=stat["best_score"],
                    average_score=stat["average_score"],
                    diversity=stat["diversity"],
                    generation=stat["generation"],
                )
                for stat in stats
            ),
        )
        island_id = self.island_selector(context)
        if (
            isinstance(island_id, bool)
            or not isinstance(island_id, Integral)
            or not 0 <= island_id < self.num_islands
        ):
            raise ValueError(
                f"island_selector must return an integer island ID in [0, {self.num_islands - 1}], "
                f"got {island_id!r}"
            )
        return int(island_id)

    def _checkpoint_if_due(self, iteration: int, callback=None) -> None:
        if iteration > 0 and iteration % self.config.checkpoint_interval == 0:
            logger.info("Checkpoint interval reached at iteration %d", iteration)
            self.database.log_island_status()
            if callback:
                callback(iteration)

    async def run_evolution(
        self,
        start_iteration: int,
        max_iterations: int,
        target_score: Optional[float] = None,
        checkpoint_callback=None,
    ):
        """Run evolution with process-based parallelism"""
        if not self.executor:
            raise RuntimeError("Process pool not started")

        total_iterations = start_iteration + max_iterations

        logger.info(
            f"Starting process-based evolution from iteration {start_iteration} "
            f"for {max_iterations} iterations (total: {total_iterations})"
        )

        # Track pending futures by island to maintain distribution
        pending_futures: Dict[int, Future] = {}
        island_pending: Dict[int, List[int]] = {i: [] for i in range(self.num_islands)}
        # A queued speculative task uses a snapshot from before the preceding
        # evaluation. Keep at most one task per worker so feedback can reach
        # the next generation when running sequential experiments.
        batch_size = min(self.num_workers, max_iterations)

        # Submit initial batch - distribute across islands
        batch_per_island = max(1, batch_size // self.num_islands) if batch_size > 0 else 0
        current_iteration = start_iteration

        if self.island_selector is None:
            # Preserve the original round-robin distribution by default.
            for island_id in range(self.num_islands):
                for _ in range(batch_per_island):
                    if current_iteration < total_iterations:
                        future = self._submit_iteration(current_iteration, island_id)
                        if future:
                            pending_futures[current_iteration] = future
                            island_pending[island_id].append(current_iteration)
                        current_iteration += 1
        else:
            # Keep the original initial batch size, but let the policy place each task.
            initial_slots = min(max_iterations, batch_per_island * self.num_islands)
            for _ in range(initial_slots):
                island_id = self._select_island(current_iteration, island_pending)
                future = self._submit_iteration(current_iteration, island_id)
                if future:
                    pending_futures[current_iteration] = future
                    island_pending[island_id].append(current_iteration)
                current_iteration += 1

        next_iteration = current_iteration
        completed_iterations = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_tokens = 0
        total_llm_calls = 0

        # Early stopping tracking
        early_stopping_enabled = self.config.early_stopping_patience is not None
        if early_stopping_enabled:
            best_score = float("-inf")
            iterations_without_improvement = 0
            if self.config.early_stopping_patience < 0:
                logger.info(
                    f"Early stopping patience is set to a negative value, running event-based early-stopping, "
                    f"Early stop when metric '{self.config.early_stopping_metric}' reaches {self.config.convergence_threshold}"
                )
            else:
                logger.info(
                    f"Early stopping enabled: patience={self.config.early_stopping_patience}, "
                    f"threshold={self.config.convergence_threshold}, "
                    f"metric={self.config.early_stopping_metric}"
                )
        else:
            logger.info("Early stopping disabled")

        # Process results as they complete
        while (
            pending_futures
            and completed_iterations < max_iterations
            and not self.shutdown_event.is_set()
        ):
            # Find completed futures
            completed_iteration = None
            for iteration, future in list(pending_futures.items()):
                if future.done():
                    completed_iteration = iteration
                    break

            if completed_iteration is None:
                await asyncio.sleep(0.01)
                continue

            # Process completed result
            future = pending_futures.pop(completed_iteration)

            try:
                # Use evaluator timeout + buffer to gracefully handle stuck processes
                timeout_seconds = self.config.evaluator.timeout + 30
                result = future.result(timeout=timeout_seconds)

                token_str = ""
                if result.token_usage:
                    pt = result.token_usage.get("prompt_tokens", 0)
                    ct = result.token_usage.get("completion_tokens", 0)
                    tt = result.token_usage.get("total_tokens", 0)
                    total_prompt_tokens += pt
                    total_completion_tokens += ct
                    total_tokens += tt
                    total_llm_calls += 1
                    token_str = f" | tokens: {tt} (prompt: {pt}, completion: {ct})"

                record = {"iteration": completed_iteration,
                          "parent_id": result.parent_id,
                          "prompt": result.prompt,
                          "llm_response": result.llm_response,
                          "token_usage": result.token_usage,
                          "stages": list(result.stages or []),
                          "artifacts": result.artifacts}

                if result.error:
                    self.recent_iteration_errors.append({
                        "iteration": completed_iteration,
                        "error": result.error[:500],
                    })
                    self._record_iteration({**record, "status": "rejected",
                                            "error": result.error,
                                            "error_code": result.error_code or "worker_error"})
                    logger.warning(
                        f"Iteration {completed_iteration} error: {result.error}{token_str}"
                    )
                    if self.config.stop_on_llm_error and result.error.startswith(
                        "LLM generation failed:"
                    ):
                        logger.error("Stopping after model generation failed")
                        self.shutdown_event.set()
                    self._checkpoint_if_due(completed_iteration, checkpoint_callback)
                elif result.child_program_dict:
                    # Reconstruct program from dict
                    child_program = Program(**result.child_program_dict)
                    rejection = candidate_failure_reason(child_program.metrics, result.artifacts)
                    record["child_code"] = child_program.code
                    record["program_id"] = child_program.id
                    record["metrics"] = child_program.metrics
                    parent_program = (
                        self.database.get(result.parent_id) if result.parent_id else None
                    )
                    if parent_program:
                        record["parent_metrics"] = parent_program.metrics
                        record["change_summary"] = _change_summary(
                            parent_program.code, child_program.code
                        )
                        record["source_diff"] = "".join(difflib.unified_diff(
                            parent_program.code.splitlines(keepends=True),
                            child_program.code.splitlines(keepends=True),
                            fromfile="parent.py", tofile="candidate.py",
                        ))
                    record["changes_description"] = child_program.metadata.get("changes", "")
                    if rejection:
                        self.recent_iteration_errors.append({
                            "iteration": completed_iteration, "error": rejection[:500]})
                        record["stages"].append({"stage": "candidate_selection",
                                                 "status": "rejected",
                                                 "error_code": "evaluation_failure",
                                                 "seconds": 0.0})
                        self._record_iteration({**record, "status": "rejected",
                                                "error": rejection,
                                                "error_code": "evaluation_failure"})
                        raise _CandidateRejected(child_program.id)

                    # Add to database with explicit target_island to ensure proper island placement
                    # This fixes issue #391: children should go to the target island, not inherit
                    # from the parent (which may be from a different island due to fallback sampling)
                    admitted_id = self.database.add(
                        child_program,
                        iteration=completed_iteration,
                        target_island=result.target_island,
                    )
                    if admitted_id is None:
                        record["stages"].append({"stage": "candidate_selection",
                                                 "status": "rejected",
                                                 "error_code": "admission_rejected",
                                                 "seconds": 0.0})
                        self._record_iteration({**record, "status": "rejected",
                                                "error": "population admission rejected candidate",
                                                "error_code": "admission_rejected"})
                        raise _CandidateRejected(child_program.id)

                    record["stages"].append({"stage": "candidate_selection",
                                             "status": "passed", "seconds": 0.0})
                    self._record_iteration({**record, "status": "admitted"})

                    # Store artifacts
                    if result.artifacts:
                        self.database.store_artifacts(child_program.id, result.artifacts)

                    # Log evolution trace
                    if self.evolution_tracer:
                        # Retrieve parent program for trace logging
                        parent_program = (
                            self.database.get(result.parent_id) if result.parent_id else None
                        )
                        if parent_program:
                            # Determine island ID
                            island_id = child_program.metadata.get(
                                "island", self.database.current_island
                            )

                            self.evolution_tracer.log_trace(
                                iteration=completed_iteration,
                                parent_program=parent_program,
                                child_program=child_program,
                                prompt=result.prompt,
                                llm_response=result.llm_response,
                                artifacts=result.artifacts,
                                island_id=island_id,
                                metadata={
                                    "iteration_time": result.iteration_time,
                                    "changes": child_program.metadata.get("changes", ""),
                                    "token_usage": result.token_usage,
                                },
                            )

                    # Log prompts
                    if result.prompt:
                        self.database.log_prompt(
                            template_key=(
                                "full_rewrite_user"
                                if not self.config.diff_based_evolution
                                else "diff_user"
                            ),
                            program_id=child_program.id,
                            prompt=result.prompt,
                            responses=[result.llm_response] if result.llm_response else [],
                            token_usage=result.token_usage,
                        )

                    # Island management
                    # get current program island id
                    island_id = child_program.metadata.get("island", self.database.current_island)
                    # use this to increment island generation
                    self.database.increment_island_generation(island_idx=island_id)

                    # Check migration
                    if self.database.should_migrate():
                        logger.info(f"Performing migration at iteration {completed_iteration}")
                        self.database.migrate_programs()
                        self.database.log_island_status()

                    # Log progress
                    logger.info(
                        f"Iteration {completed_iteration}: "
                        f"Program {child_program.id} "
                        f"(parent: {result.parent_id}) "
                        f"completed in {result.iteration_time:.2f}s{token_str}"
                    )

                    if child_program.metrics:
                        metrics_str = ", ".join(
                            [
                                f"{k}={v:.4f}" if isinstance(v, (int, float)) else f"{k}={v}"
                                for k, v in child_program.metrics.items()
                            ]
                        )
                        logger.info(f"Metrics: {metrics_str}")

                        # Check if this is the first program without combined_score
                        if not hasattr(self, "_warned_about_combined_score"):
                            self._warned_about_combined_score = False

                        if (
                            "combined_score" not in child_program.metrics
                            and not self._warned_about_combined_score
                        ):
                            avg_score = safe_numeric_average(child_program.metrics)
                            logger.warning(
                                f"⚠️  No 'combined_score' metric found in evaluation results. "
                                f"Using average of all numeric metrics ({avg_score:.4f}) for evolution guidance. "
                                f"For better evolution results, please modify your evaluator to return a 'combined_score' "
                                f"metric that properly weights different aspects of program performance."
                            )
                            self._warned_about_combined_score = True

                    # Check for new best
                    if self.database.best_program_id == child_program.id:
                        logger.info(
                            f"🌟 New best solution found at iteration {completed_iteration}: "
                            f"{child_program.id}"
                        )

                    self._checkpoint_if_due(completed_iteration, checkpoint_callback)

                    # Check target score
                    if target_score is not None and child_program.metrics:
                        if (
                            "combined_score" in child_program.metrics
                            and child_program.metrics["combined_score"] >= target_score
                        ):
                            logger.info(
                                f"Target score {target_score} reached at iteration {completed_iteration}"
                            )
                            break

                    # Check early stopping
                    if early_stopping_enabled and child_program.metrics:
                        if child_program.metrics.get(
                            "error"
                        ) is not None or child_program.metrics.get("timeout"):
                            # Failed or timed-out evaluations carry no score. Letting them
                            # into the counter below would poison the best-score baseline
                            # with 0.0 on the first failure and then count every subsequent
                            # failure as "no improvement", so a run that never succeeded
                            # once would exit through the successful-plateau path
                            # (issue #294). Skip them: early stopping only counts
                            # evaluations that actually produced a score. The "error" check
                            # is presence-based (is not None) because evaluators signal
                            # failures both with numeric ({"error": 0.0}) and string values.
                            logger.debug(
                                "Skipping failed evaluation from early stopping count at iteration %s",
                                completed_iteration,
                            )
                        else:
                            # Get the metric to track for early stopping
                            current_score = None
                            if self.config.early_stopping_metric in child_program.metrics:
                                current_score = child_program.metrics[
                                    self.config.early_stopping_metric
                                ]
                            elif self.config.early_stopping_metric == "combined_score":
                                # Default metric not found, use safe average (standard pattern)
                                current_score = safe_numeric_average(child_program.metrics)
                            else:
                                # User specified a custom metric that doesn't exist
                                logger.warning(
                                    f"Early stopping metric '{self.config.early_stopping_metric}' not found, using safe numeric average"
                                )
                                current_score = safe_numeric_average(child_program.metrics)

                            if current_score is not None and isinstance(
                                current_score, (int, float)
                            ):
                                # Check for improvement
                                if self.config.early_stopping_patience > 0:
                                    improvement = current_score - best_score
                                    if improvement >= self.config.convergence_threshold:
                                        best_score = current_score
                                        iterations_without_improvement = 0
                                        logger.debug(
                                            f"New best score: {best_score:.4f} (improvement: {improvement:+.4f})"
                                        )
                                    else:
                                        iterations_without_improvement += 1
                                        logger.debug(
                                            f"No improvement: {iterations_without_improvement}/{self.config.early_stopping_patience}"
                                        )

                                    # Check if we should stop
                                    if (
                                        iterations_without_improvement
                                        >= self.config.early_stopping_patience
                                    ):
                                        self.early_stopping_triggered = True
                                        logger.info(
                                            f"🛑 Early stopping triggered at iteration {completed_iteration}: "
                                            f"No improvement for {iterations_without_improvement} iterations "
                                            f"(best score: {best_score:.4f})"
                                        )
                                        break

                                else:
                                    # Event-based early stopping
                                    if current_score == self.config.convergence_threshold:
                                        best_score = current_score
                                        logger.info(
                                            f"🛑 Early stopping (event-based) triggered at iteration {completed_iteration}: "
                                            f"Task successfully solved with score {best_score:.4f}."
                                        )
                                        self.early_stopping_triggered = True
                                        break

            except _CandidateRejected as rejected:
                logger.info("Admission strategy rejected program %s", rejected)
                try:
                    self._checkpoint_if_due(completed_iteration, checkpoint_callback)
                except Exception as e:
                    if getattr(e, "_openevolve_strategy_error", False):
                        raise
                    logger.error(
                        f"Error processing result from iteration {completed_iteration}: {e}"
                    )
            except FutureTimeoutError as e:
                if getattr(e, "_openevolve_strategy_error", False):
                    raise
                logger.error(
                    f"⏰ Iteration {completed_iteration} timed out after {timeout_seconds}s "
                    f"(evaluator timeout: {self.config.evaluator.timeout}s + 30s buffer). "
                    f"Canceling future and continuing with next iteration."
                )
                # Cancel the future to clean up the process
                future.cancel()
            except Exception as e:
                if getattr(e, "_openevolve_strategy_error", False):
                    raise
                logger.error(f"Error processing result from iteration {completed_iteration}: {e}")

            completed_iterations += 1

            # Remove completed iteration from island tracking
            for island_id, iteration_list in island_pending.items():
                if completed_iteration in iteration_list:
                    iteration_list.remove(completed_iteration)
                    break

            # Submit one replacement task per completion. Custom policies control
            # placement; the default path retains the original balancing logic.
            if self.island_selector is not None:
                if next_iteration < total_iterations and not self.shutdown_event.is_set():
                    island_id = self._select_island(next_iteration, island_pending)
                    future = self._submit_iteration(next_iteration, island_id)
                    if future:
                        pending_futures[next_iteration] = future
                        island_pending[island_id].append(next_iteration)
                        next_iteration += 1
            else:
                for island_id in range(self.num_islands):
                    if (
                        len(island_pending[island_id]) < batch_per_island
                        and next_iteration < total_iterations
                        and not self.shutdown_event.is_set()
                    ):
                        future = self._submit_iteration(next_iteration, island_id)
                        if future:
                            pending_futures[next_iteration] = future
                            island_pending[island_id].append(next_iteration)
                            next_iteration += 1
                            break  # Only submit one iteration per completion to maintain balance

        # Handle shutdown
        if self.shutdown_event.is_set():
            logger.info("Shutdown requested, canceling remaining evaluations...")
            for future in pending_futures.values():
                future.cancel()

        # Log completion reason
        if self.early_stopping_triggered:
            logger.info("✅ Evolution completed - Early stopping triggered due to convergence")
        elif self.shutdown_event.is_set():
            logger.info("✅ Evolution completed - Shutdown requested")
        else:
            logger.info("✅ Evolution completed - Maximum iterations reached")

        if total_llm_calls > 0:
            logger.info(
                f"📊 Total LLM Token Usage ({total_llm_calls} calls): "
                f"total_tokens={total_tokens} "
                f"(prompt_tokens={total_prompt_tokens}, completion_tokens={total_completion_tokens})"
            )

        return self.database.get_best_program()

    def _submit_iteration(
        self, iteration: int, island_id: Optional[int] = None
    ) -> Optional[Future]:
        """Submit an iteration to the process pool, optionally pinned to a specific island"""
        try:
            # Use specified island or current island
            target_island = island_id if island_id is not None else self.database.current_island

            # Use thread-safe sampling that doesn't modify shared state
            # This fixes the race condition from GitHub issue #246
            # Inspirations are the diverse/creative examples; size them by
            # num_diverse_programs (not num_top_programs) so the config parameter
            # actually controls the inspiration count (GitHub issue #452).
            parent, inspirations = self.database.sample_from_island(
                island_id=target_island,
                num_inspirations=self.config.prompt.num_diverse_programs,
            )

            # Create database snapshot
            db_snapshot = self._create_database_snapshot()
            db_snapshot["sampling_island"] = target_island  # Mark which island this is for

            # Submit to process pool
            future = self.executor.submit(
                _run_iteration_worker,
                iteration,
                db_snapshot,
                parent.id,
                [insp.id for insp in inspirations],
            )

            return future

        except Exception as e:
            logger.error(f"Error submitting iteration {iteration}: {e}")
            return None
