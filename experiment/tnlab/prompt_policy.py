"""Canonical, replaceable prompt-context policies for the formal experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_SCHEMA_VERSION = 1

# This is the policy actually used by the registered experiment.  The IDs are
# semantic names, while the source hashes below bind them to implementation.
FORMAL_POLICY: dict[str, Any] = {
    "policy_schema_version": POLICY_SCHEMA_VERSION,
    "history_policy": {
        "id": "oe_history_v1",
        "parent_mode": "single_parent_mutation",
        "num_top_programs": 2,
        "num_diverse_programs": 2,
        "inspiration_count": 2,
        "previous_attempt_limit": 3,
        "selection_order": "database_combined_score_descending",
        "diverse_selection": "sampler_random_sample",
        "deduplication": "inspirations_against_top_and_diverse_only",
    },
    "failure_feedback_policy": {
        "id": "openevolve_recent_v1",
        "config_name": "openevolve_recent",
        "limit": 2,
        "evidence": "failure_evidence_ids_and_records",
    },
    "pipeline_feedback_policy": {
        "id": "append_recent_pipeline_v1",
        "limit": 3,
        "ordering": "last_three_in_iteration_order",
    },
    "experience_policy": {
        "id": "experience_none_v1",
        "mode": "validation_only",
        "prompt_injection": False,
    },
    "cross_run_policy": {
        "id": "cross_run_audit_only_v1",
        "prompt_injection": False,
        "artifact": "previous_run_summary.json",
    },
    "heldout_prompt_sources": [],
    "parallel_evaluations": 1,
}

TEMPLATE_DEPENDENCIES = (
    "prompts/diff_user.txt",
    "../openevolve/openevolve/prompts/defaults/diff_user.txt",
    "../openevolve/openevolve/prompts/defaults/evolution_history.txt",
    "../openevolve/openevolve/prompts/defaults/previous_attempt.txt",
    "../openevolve/openevolve/prompts/defaults/top_program.txt",
    "../openevolve/openevolve/prompts/defaults/inspirations_section.txt",
    "../openevolve/openevolve/prompts/defaults/inspiration_program.txt",
    "../openevolve/openevolve/prompts/defaults/system_message.txt",
    "../openevolve/openevolve/prompts/defaults/system_message_changes_description.txt",
    "../openevolve/openevolve/prompts/defaults/system_message_with_changes_description.txt",
    "../openevolve/openevolve/prompts/defaults/user_message_with_changes_description.txt",
    "../openevolve/openevolve/prompts/defaults/full_rewrite_user.txt",
    "../openevolve/openevolve/prompts/defaults/evaluation.txt",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_policy_manifest() -> dict[str, Any]:
    """Return the canonical policy plus exact hashes of loaded templates."""
    manifest = json.loads(json.dumps(FORMAL_POLICY, sort_keys=True))
    manifest["template_dependencies"] = {
        name: _sha256(ROOT / name) for name in TEMPLATE_DEPENDENCIES
    }
    return manifest


def prompt_policy_sha256(manifest: dict[str, Any] | None = None) -> str:
    """Hash a canonical policy manifest for run identity and resume checks."""
    payload = manifest if manifest is not None else prompt_policy_manifest()
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
