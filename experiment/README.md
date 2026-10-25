# Tensor-Network Experiment

This directory contains the registered tensor-network contraction-path experiment. A candidate implements:

```python
def find_path(inputs, output, sizes, seed=0):
    ...
```

The path uses current tensor-list positions; each step removes two positions and appends the merged tensor.

## Admission before real requests

The registered study ID is `tensor-path-discovery-2026-10`. It uses SiliconFlow's `deepseek-ai/DeepSeek-V3.2`, one calibration phase, five independent 15-iteration discovery runs, deterministic selection, and one final/transfer evaluation. Model-list, probe, calibration, discovery, failed, and retry requests share a persistent 100-reservation ledger and are attributed by `run_id`.

Before the first real request, the same frozen identity must cover source, dependency lock, configuration, v3 benchmark manifests, prompt templates, registration, runner image, and archive. Candidate code runs only in the isolated container: no network, credentials, benchmark data, or held-out data. The formal prompt policy uses OpenEvolve parent/top/diverse/inspiration context and `openevolve_recent` feedback. Experience retrieval is disabled; `tnlab/experience.py` validates future records but is not connected to the Agent.

The local fake drill proves only that the offline evidence chain can close. It does not prove a real-model result. Its `drill_completion.json` must link the frozen discovery manifest, selection hashes, successful revalidation, final report, and actual request counts. Results and ledgers stay local.

## Running

Prepare dependencies and the runner image from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\setup.ps1"
```

Then run the registered orchestration:

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"
```

Do not put API keys in source, command-line arguments, logs, or Git. Use the local protected secret mechanism or a process-only environment variable. `-ResumeRun <directory>` resumes the original run identity only after rechecking registration, source hashes, and ledger identity.

## Evidence and metrics

Every discovery run saves registration and frozen-source evidence, prompt-policy identity, initial-program hash, per-iteration journal, prompts, responses, diffs, candidates, artifacts, failure feedback, checkpoints, and request attribution. Fifteen journal iterations are distinct from model requests, generation attempts, completed evaluations, valid candidates, admissions, and rejections.

Search uses `develop_v2.json` only. `final_v3.json` (12 cases, SHA-256 `e1f77dae9c7e8baa5a6e1baf6927b1ac1acf5e486d30c1ccfb627d05b8d8b3d9`) and `transfer_v3.json` (6 cases, SHA-256 `4c643d7bf84118bc1f0c4ff6d47362d973a1e5318c39aeca37ad9f351fab0806`) are evaluated once after selection and never flow back into prompts, feedback, or experience. Selection independently recomputes each run and its predefined baselines, ranks by the registered geometric cost ratio, and breaks ties by candidate SHA-256. An evidence-incomplete run is inconclusive and cannot be promoted.

## Local checks

From this directory:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe verify_container.py
.\.venv\Scripts\python.exe fake_full_drill.py
```

The fake drill sends requests only to its local fake provider. Docker isolation, PowerShell resume behavior, archive load/replay, and the complete fake drill are separate checks; a pass in one environment does not replace a failed or unavailable check in another environment.

## Reporting limits

Reports separate directly verified facts, bounded inferences, and unverified conditions. Not beating the strongest baseline is a valid result. Missing request attribution, runner identity, source freeze, or per-case evidence is reported as inconclusive. Historical cumulative ledger totals are not single-run request counts, and score-only replay without the historical runner is not full execution reproduction.
