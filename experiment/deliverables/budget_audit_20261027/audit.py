"""Offline response budget audit. Pure validation/counting functions + Linux CLI.

No provider imports, network count APIs, config, data splits, or request ledger.
Exactness of an injected tokenizer/receipt remains the caller's responsibility.
"""
from __future__ import annotations

import hashlib
import json
import re

CAPS = (2048, 4096, 8192)
SCOPE = "utf8-response-text-only:no-special-tokens"
DECLARATION = "model-native-tokenizer:no-estimates:no-proxy-conversions"
ROUTES = ("partition", "tree", "beam")
KINDS = ("local_decision", "replace_search_function", "replace_entire_region")
EXPECTED_IDS = {f"{route}/{kind}" for route in ROUTES for kind in KINDS}
IDENTITY_TEXT = ("provider", "model", "model_revision", "tokenizer", "tokenizer_revision",
                 "model_tokenizer_binding", "provenance")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name):
    require(type(value) is int and value >= 0, f"{name}: nonnegative integer required (not bool)")
    return value


def digest(value, name):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
            f"{name}: lowercase SHA256 required")
    return value


def identity(value):
    require(type(value) is dict, "explicit model/tokenizer identity required")
    for key in IDENTITY_TEXT:
        require(type(value.get(key)) is str and bool(value[key].strip()), f"missing identity: {key}")
    for key in ("tokenizer_sha256", "adapter_sha256"):
        digest(value.get(key), key)
    require(value.get("counting_scope") == SCOPE, "unsupported counting scope")
    require(value.get("exactness_declaration") == DECLARATION, "estimates/proxy counts forbidden")
    require(type(value.get("test_only")) is bool, "test_only must be explicit boolean")
    return dict(value)


def response_inventory(summary):
    """Recompute exact UTF-8 bytes/lines/hash; do not trust saved dimensions."""
    require(summary.get("purpose") == "public-offline-patch-compatibility", "wrong public summary")
    require(summary.get("status") == "passed", "public patch summary did not pass")
    rows = {}
    for item in summary["examples"]:
        name = f"{item['route']}/{item['kind']}"
        require(name in EXPECTED_IDS and name not in rows, "unknown/duplicate response")
        text = item["response"]
        require(type(text) is str and bool(text), "missing exact response")
        raw = text.encode("utf-8")
        measured = {"response_id": name, "response_sha256": sha(raw),
                    "utf8_bytes": len(raw), "lines": len(text.splitlines()), "text": text}
        for saved, computed in (("response_sha256", "response_sha256"),
                                ("response_utf8_bytes", "utf8_bytes"), ("response_lines", "lines")):
            require(item[saved] == measured[computed], f"public response mismatch: {name}/{saved}")
        rows[name] = measured
    require(set(rows) == EXPECTED_IDS, "omitted public responses")
    return rows


def classify_cap(count, cap):
    integer(count, "count")
    integer(cap, "cap")
    require(cap > 0, "cap must be positive")
    return "fits" if count <= cap else "overflow"


def import_receipt(receipt, rows, selected_identity):
    """Integrity/schema validation, never authentication or proof of exactness."""
    chosen = identity(selected_identity)
    require(type(receipt) is dict and type(receipt.get("schema_version")) is int
            and receipt["schema_version"] == 1, "receipt schema_version must be 1")
    require(receipt.get("kind") == "external-exact-token-counts", "wrong receipt kind")
    require(identity(receipt.get("identity")) == chosen, "receipt differs from explicit selected identity")
    require(type(receipt.get("caps")) is list and all(type(x) is int for x in receipt["caps"])
            and receipt["caps"] == list(CAPS), "receipt budget caps mismatch")
    require(type(receipt.get("counts")) is list, "receipt counts must be list")
    counts = {}
    for item in receipt["counts"]:
        require(type(item) is dict, "receipt count object required")
        name = item.get("response_id")
        require(type(name) is str and name in rows and name not in counts,
                "unknown/duplicate receipt response")
        require(item.get("response_sha256") == rows[name]["response_sha256"], "receipt response hash mismatch")
        counts[name] = integer(item.get("exact_tokens"), "exact_tokens")
    require(set(counts) == set(rows), "omitted receipt responses")
    return {"method": "external-exact-receipt", "identity": chosen, "counts": counts,
            "authentication": "none; hashes bind bytes, not truth or model/tokenizer compatibility"}


def measure_local(rows, selected_identity, encode_exact):
    """Inject exact native encoding; token IDs, never character/token ratios.

    Callable contract: encode_exact(text: str) -> list[int]. It must implement
    the declared model-native tokenizer with no special tokens. Provenance and
    hashes are required, but cannot prove arbitrary adapter semantics.
    """
    chosen = identity(selected_identity)
    require(callable(encode_exact), "exact local tokenizer callable required")
    counts = {}
    for name, row in rows.items():
        tokens = encode_exact(row["text"])
        require(type(tokens) is list and all(type(x) is int and x >= 0 for x in tokens),
                "exact tokenizer must return nonnegative integer token IDs")
        counts[name] = len(tokens)
    return {"method": "local-exact-tokenizer", "identity": chosen, "counts": counts,
            "authentication": "none; caller asserts tokenizer/model compatibility and adapter exactness"}


def build_report(rows, measurement=None):
    usable = measurement is not None and not measurement["identity"]["test_only"]
    external = usable and measurement["method"] == "external-exact-receipt"
    status = ("reported_exact_unverified" if external else "measured_local_declared_exact") if usable else "blocked_unmeasured"
    if usable:
        require(set(measurement["counts"]) == set(rows), "omitted measurement responses")
        for count in measurement["counts"].values():
            integer(count, "exact_tokens")
    result = {"schema_version": 1, "purpose": "decoupled-public-offline-response-budget-audit",
              "status": status, "tokenizer_measured_locally": usable and not external,
              "measurement": measurement if usable else None,
              "synthetic_measurement_ignored": measurement is not None and not usable,
              "caps": list(CAPS), "counting_scope": SCOPE, "responses": [], "cap_assessments": {},
              "model_requests": 0, "network_count_requests": 0,
              "input_context_tokens": None, "api_serialization_tokens": None,
              "full_request_budget_feasibility": "blocked_unmeasured",
              "limitations": ["Only exact saved response text is in scope; no prompts/messages/API framing, stop/EOS, reasoning or context-window accounting.",
                              "Local exactness is a caller contract; external receipts are unverified claims, not authenticated measurements.",
                              "No estimates, character/token conversions, automatic model selection, or budget changes."]}
    for name in sorted(rows):
        row = {key: value for key, value in rows[name].items() if key != "text"}
        row["exact_tokens"] = measurement["counts"][name] if usable else None
        row["cap_status"] = {str(cap): classify_cap(row["exact_tokens"], cap) if usable else "unmeasured"
                             for cap in CAPS}
        result["responses"].append(row)
    for cap in CAPS:
        overflow = [x["response_id"] for x in result["responses"] if x["cap_status"][str(cap)] == "overflow"]
        result["cap_assessments"][str(cap)] = {
            "status": ("reported_" if external else "") + ("overflow" if overflow else "fits_all_saved_examples") if usable else "unmeasured",
            "overflow_response_ids": overflow if usable else None,
            "covers": "nine saved examples only; not arbitrary future responses"}
    result["blockers"] = ([] if usable else ["No explicit selected provider/model and verified exact tokenizer or complete bound receipt supplied."])
    result["blockers"].append("Input prompt/message serialization and full API budget not measured.")
    return result


def linux_main():
    import importlib.metadata
    import importlib.util
    from pathlib import Path
    import platform
    import sys

    require(platform.system() == "Linux", "business audit must run in Linux")
    base = Path(__file__).resolve().parent
    public = json.loads((base / "patch_summary.json").read_bytes())
    rows = response_inventory(public)
    # Only this explicit standalone public exporter is executed; no solver/provider runs.
    exporter_bytes = (base / "export_candidates.py").read_bytes()
    heuristics_bytes = (base / "heuristics.py").read_bytes()
    require(sha(exporter_bytes) == public["source_sha256"]["export_candidates.py"], "exporter hash mismatch")
    require(sha(heuristics_bytes) == public["source_sha256"]["heuristics.py"], "teacher source hash mismatch")
    namespace = {"__name__": "public_candidate_exporter"}
    exec(compile(exporter_bytes, "export_candidates.py", "exec"), namespace)
    exported = namespace["export"](heuristics_bytes.decode("utf-8"))
    candidate_rows = []
    for route in ROUTES:
        raw = exported[route].encode("utf-8")
        expected = public["exports"][route]
        require(sha(raw) == expected["source_sha256"], "teacher candidate export mismatch")
        require(len(raw) == expected["source_utf8_bytes"]
                and len(exported[route].splitlines()) == expected["source_lines"], "teacher export dimensions mismatch")
        candidate_rows.append({"route": route, "sha256": sha(raw), "utf8_bytes": len(raw),
                               "lines": len(exported[route].splitlines()), "tokens": None})
    measurement = None
    options = json.loads((base / "options.json").read_bytes())
    if options["mode"] != "unmeasured":
        selected = identity(json.loads((base / "identity.json").read_bytes()))
        if options["mode"] == "receipt":
            measurement = import_receipt(json.loads((base / "receipt.json").read_bytes()), rows, selected)
        else:
            adapter = (base / "adapter.py").read_bytes()
            artifact = base / "tokenizer.artifact"
            require(sha(adapter) == selected["adapter_sha256"], "local adapter hash mismatch")
            require(sha(artifact.read_bytes()) == selected["tokenizer_sha256"], "local tokenizer artifact hash mismatch")
            adapter_ns = {"__name__": "injected_exact_local_tokenizer", "__file__": str(base / "adapter.py")}
            exec(compile(adapter, "adapter.py", "exec"), adapter_ns)
            encoder = adapter_ns["create_encoder"](str(artifact), dict(selected))
            measurement = measure_local(rows, selected, encoder)
    report = build_report(rows, measurement)
    packages = {}
    for name in ("tiktoken", "tokenizers", "transformers", "sentencepiece"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    report["tokenizer_package_inventory"] = packages
    report["candidate_exports"] = candidate_rows
    report["environment"] = {"system": platform.system(), "python": sys.version}
    report["source_sha256"] = {p.name: sha(p.read_bytes()) for p in sorted(base.iterdir()) if p.is_file()}
    report["public_model_clues"] = {
        "run_experiment.py": {"legacy_report_default_present": '"deepseek-ai/DeepSeek-V3.2"' in (base / "public_run_experiment.txt").read_text(),
                              "TN_MODEL_override_present": 'os.environ.get("TN_MODEL")' in (base / "public_run_experiment.txt").read_text()},
        "interpretation": "Legacy report default and optional environment override are clues only; real config/environment selection is deliberately not read; no provider/model chosen.",
        "selected_provider": measurement["identity"]["provider"] if measurement else None,
        "selected_model": measurement["identity"]["model"] if measurement else None}
    if all(value is None for value in packages.values()):
        report["blockers"].insert(0, "No tiktoken/tokenizers/transformers/sentencepiece distribution installed in pinned image; no selected model-native tokenizer artifact supplied.")
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    linux_main()
