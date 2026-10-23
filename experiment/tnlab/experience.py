"""Auditable failure labels and experience-record validation."""

from collections.abc import Mapping

FAILURE_CLASSES = {
    "request_service",
    "output_protocol",
    "api_knowledge",
    "syntax_interface",
    "path_semantics",
    "resource",
    "nondeterminism",
    "objective_regression",
    "evidence_protocol",
    "unknown",
}

_STATUS = {"hypothesis", "single_run", "replicated", "contradicted", "retired"}
_HELD_OUT_NAMES = {"final", "transfer", "final_v2.json", "transfer_v2.json"}


def classify_failure(error_code=None, message="", stage=""):
    """Classify observable evidence without inferring a causal explanation."""
    code = str(error_code or "").strip().lower()
    text = f"{message} {stage}".lower()
    if "nondetermin" in text or "different path" in text:
        return "nondeterminism"
    if any(token in text for token in ("model http", "llm", "api request", "provider")):
        return "request_service"
    if any(token in code for token in ("http", "request", "rate_limit", "auth", "timeout_llm")):
        return "request_service"
    if any(token in code for token in ("diff", "parse", "format", "delimiter", "protocol")):
        return "output_protocol"
    if any(token in code for token in ("api", "attribute", "argument", "import")):
        return "api_knowledge"
    if any(token in code for token in ("syntax", "interface")):
        return "syntax_interface"
    if any(token in code for token in ("invalid_path", "path", "case_failure")):
        return "path_semantics"
    if any(token in code for token in ("timeout", "resource", "memory")):
        return "resource"
    if any(token in code for token in ("nondetermin", "repeatability")):
        return "nondeterminism"
    if any(token in code for token in ("score", "regression", "no_improvement")):
        return "objective_regression"
    if any(token in code for token in ("evidence", "snapshot", "budget", "hash", "protocol_invalid")):
        return "evidence_protocol"

    if "nondetermin" in text or "different path" in text:
        return "nondeterminism"
    if "timeout" in text or "memory limit" in text or "resource" in text:
        return "resource"
    if "syntaxerror" in text or "find_path function is missing" in text:
        return "syntax_interface"
    if any(token in text for token in ("indexerror", "path must", "invalid path", "pairwise")):
        return "path_semantics"
    if any(token in text for token in ("unexpected keyword", "has no attribute", "no module named")):
        return "api_knowledge"
    if any(token in text for token in ("search/replace", "diff block", "delimiter", "no valid diffs")):
        return "output_protocol"
    if any(token in text for token in ("http 4", "http 5", "rate limit", "authentication")):
        return "request_service"
    return "unknown"


def validate_experience(record):
    """Return validation errors for one evidence-linked experience record."""
    errors = []
    if not isinstance(record, Mapping):
        return ["record must be a mapping"]
    required = ("experience_id", "status", "scope", "observation", "interpretation",
                "recommendation", "source", "counterexamples", "validation_runs",
                "last_reviewed")
    for key in required:
        if key not in record:
            errors.append(f"missing {key}")
    if errors:
        return errors

    if not isinstance(record["experience_id"], str) or not record["experience_id"].strip():
        errors.append("experience_id must be a non-empty string")
    status = record["status"]
    if status not in _STATUS:
        errors.append("status is not recognized")
    for key in ("observation", "interpretation", "recommendation", "last_reviewed"):
        if not isinstance(record[key], str) or not record[key].strip():
            errors.append(f"{key} must be a non-empty string")
    if not isinstance(record["scope"], Mapping):
        errors.append("scope must be a mapping")
    if not isinstance(record["source"], Mapping):
        errors.append("source must be a mapping")
        source = {}
    else:
        source = record["source"]
    for key in ("run_id", "artifact_path", "artifact_sha256"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            errors.append(f"source.{key} must be a non-empty string")
    dataset = str(source.get("dataset", "")).strip().lower()
    if dataset in _HELD_OUT_NAMES or dataset.startswith(("final_", "transfer_")):
        errors.append("held-out final/transfer results cannot source experience records")
    if not isinstance(record["counterexamples"], list):
        errors.append("counterexamples must be a list")
    runs = record["validation_runs"]
    if not isinstance(runs, list) or any(not isinstance(run, str) or not run.strip()
                                         for run in runs):
        errors.append("validation_runs must be a list of run IDs")
    elif len(set(runs)) != len(runs):
        errors.append("validation_runs must contain unique run IDs")
    elif status == "replicated" and len(runs) < 2:
        errors.append("replicated status requires at least two distinct validation runs")
    elif status == "single_run" and len(runs) < 1:
        errors.append("single_run status requires at least one validation run")
    if status == "hypothesis" and not source.get("run_id"):
        errors.append("hypothesis must retain a source run or observation origin")
    return errors
