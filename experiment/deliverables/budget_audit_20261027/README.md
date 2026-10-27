# Offline response budget audit

Windows is the orchestrator. It uses the already-installed Linux image `sha256:ad059619f459c42aded047c343847fc4fc7fd9e025b3993b687768c9f549d5b3`; it never pulls or builds an image. Linux performs the audit with network disabled, read-only root, and without provider/model, config, credentials, request ledger, formal benchmark, held-out/final, or transfer data. No model request or count API is used.

From the repository root:

```powershell
python experiment/deliverables/budget_audit_20261027/run_audit.py
python experiment/deliverables/budget_audit_20261027/run_audit.py --test
```

The first command writes its full result and process evidence to `experiment/.tmp/results/budget_audit_20261027/run_<id>/`. The second runs synthetic contract tests in the same pinned Linux image. Synthetic counters are test fixtures only, are ignored in reports, and cannot become a budget measurement.

## What is measured now

The audit verifies all nine exact saved responses from `patch_compatibility_20261027/patch_compatibility_summary.json` and recomputes SHA256, UTF-8 bytes, and line counts. It also deterministically re-exports all three public teacher candidates, checks their source hashes and dimensions against the public summary, and records their bytes/lines. These structural dimensions are not token counts.

The public experiment code has a legacy DeepSeek report default and supports `TN_MODEL` override, but neither identifies the provider/model selected for a future run. This audit reads neither actual environment nor `config.yaml` and selects no provider/model. The audit does not touch configuration.

## Exact measurement inputs

No tokenizer or provider SDK is bundled. If the pinned image lacks a tokenizer exactly compatible with the explicitly selected provider/model, the correct state is `blocked_unmeasured`. Do not substitute a general tokenizer, approximate tokens from bytes/characters, download artifacts, or infer compatibility from a package name.

An external offline counter may provide a receipt, without credentials or a network count API. First prepare nonsecret `identity.json` and `receipt.json` files within this deliverables folder or its `experiment/.tmp/results/` subfolder, then invoke Windows orchestration with `--identity ... --receipt ...`. The receipt schema is:

```json
{
  "schema_version": 1,
  "kind": "external-exact-token-counts",
  "caps": [2048, 4096, 8192],
  "identity": {
    "provider": "explicit provider identifier",
    "model": "explicit model identifier",
    "model_revision": "immutable revision or documented API model version",
    "tokenizer": "exact tokenizer identifier",
    "tokenizer_revision": "immutable revision",
    "tokenizer_sha256": "64 lowercase hex digits",
    "adapter_sha256": "64 lowercase hex digits",
    "model_tokenizer_binding": "documented exact model/tokenizer binding",
    "provenance": "counter version, invocation and no-special-token policy",
    "counting_scope": "utf8-response-text-only:no-special-tokens",
    "exactness_declaration": "model-native-tokenizer:no-estimates:no-proxy-conversions",
    "test_only": false
  },
  "counts": [
    {"response_id": "partition/local_decision", "response_sha256": "exact public response hash", "exact_tokens": 123}
  ]
}
```

There must be one row for each of the nine exact response IDs. Each SHA256 must match the saved response; counts must be nonnegative JSON integers (booleans are rejected). The identity is required from the operator, and the receipt must bind to it exactly. This is structural validation only: SHA256 is not a signature, receipt authenticity is not established, and the audit cannot independently prove that a claimed tokenizer is model-native. Externally receipted counts are labelled `reported_exact_unverified`, not local measurements.

Alternatively, `--identity` with `--adapter path --artifact path` accepts an explicitly supplied local exact tokenizer. The adapter must be a small Python source file in the audit input area that implements `create_encoder(artifact_path, identity)` and returns `encode_exact(text) -> list[int]`; the exact artifact and adapter hashes must match the identity. The adapter is executed only inside the network-disabled Linux container and must perform no downloads. The caller is responsible for declaring and verifying the exact model/tokenizer binding. Such output is labelled `measured_local_declared_exact`, not independently authenticated. No package is installed by the runner.

## Current decision

The only established budget feasibility is for exact response text shape, not token counts. 2048, 4096, and 8192 cap statuses therefore remain unmeasured pending exact model/tokenizer counts. Even with response counts, the complete request budget remains blocked until actual serialized messages, input/context, API framing, and provider budget semantics are accounted for. No budget cap is changed or recommended by this audit.
