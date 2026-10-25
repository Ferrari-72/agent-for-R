# Tensor-Network Contraction-Path Discovery

This repository contains the reproducible implementation for a tensor-network contraction-path discovery study. The registered protocol uses OpenEvolve, five independent 15-iteration discovery runs, a persistent request ledger with per-run attribution, deterministic selection, and one isolated final/transfer evaluation.

The latest local fake-provider drill closed the offline evidence chain for calibration, five runs, checkpoint/resume, selection, and final evaluation. It does not establish a real-model result. Historical real runs remain separate because their original source and runner image were incomplete.

## Layout

- `experiment/`: experiment code, frozen data, prompts, tests, and run scripts.
- `openevolve/`: the maintained OpenEvolve source used by the experiment.
- `experiment/results/`: local run artifacts; ignored and not published.
- Research notes and advisor material remain outside this public checkout.

## Formal run

From the repository root, prepare the locked environment and runner image:

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\setup.ps1"
```

Run the registered orchestration only after all admission gates pass:

```powershell
powershell -ExecutionPolicy Bypass -File ".\experiment\run.ps1"
```

The formal study uses research ID `tensor-path-discovery-2026-10`, model `deepseek-ai/DeepSeek-V3.2`, development set `develop_v2.json`, final set `final_v3.json`, transfer set `transfer_v3.json`, and a new 100-reservation request ledger. Do not place API keys in source, arguments, logs, or Git. Candidate code runs in a network-disabled, read-only, low-privilege container without credentials or benchmark data.

The formal prompt policy is frozen: single-parent mutation with top/diverse/inspiration context, `openevolve_recent` failure feedback, recent pipeline feedback, and no experience retrieval. `tnlab/experience.py` validates future records only; experience retrieval is not connected to the registered Agent and must be studied separately.

## Evidence requirements

Each run records registration and frozen-source copies, prompt-policy hashes, initial-program identity, per-iteration prompts/responses/diffs/candidates/artifacts, failure feedback, checkpoints, and request attribution. The 15-iteration count is separate from model requests, generation attempts, completed evaluations, valid candidates, and admission counts.

Discovery uses only the development set. Final and transfer results are evaluated once after deterministic selection and never enter prompts, feedback, or experience. Selection independently recomputes development scores and baselines, orders by the registered primary metric, and uses candidate SHA-256 as the tie-breaker. Missing evidence makes a run inconclusive.

## Local verification

From `experiment/`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe verify_container.py
.\.venv\Scripts\python.exe fake_full_drill.py
```

`fake_full_drill.py` uses only a local fake provider and a new isolated ledger. Its completion record must contain the frozen manifest hash, selection hashes before and after final evaluation, successful selection revalidation, the final report path, and actual ledger/server request counts. This is an offline workflow check, not a model-performance claim.

Reports must distinguish directly verified facts, limited inferences, and unverified conditions. Failure to beat the strongest baseline is a valid result; missing source, runner, ledger, or per-case evidence is reported as inconclusive.
