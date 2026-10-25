# Formal Registration: Tensor-Network Path Discovery

This file is frozen before any new model request. Result fields are appended only after the study; deviations are recorded separately.

## Run Identity

- Research ID: `tensor-path-discovery-2026-10`
- Planned protocol: one calibration phase, then five independent 15-iteration discovery runs
- Model/provider: `deepseek-ai/DeepSeek-V3.2` through SiliconFlow OpenAI-compatible API
- New request budget: 100 reservations in `results/model_request_budget_100.sqlite3`
- Historical request databases: excluded; their recorded 45 requests are not part of this budget
- Development set: `develop_v2.json`, manifest `data/manifest_v2.json`
- Final set: `final_v3.json`, 12 cases, SHA-256 `e1f77dae9c7e8baa5a6e1baf6927b1ac1acf5e486d30c1ccfb627d05b8d8b3d9`
- Transfer set: `transfer_v3.json`, 6 cases, SHA-256 `4c643d7bf84118bc1f0c4ff6d47362d973a1e5318c39aeca37ad9f351fab0806`
- Held-out manifest: `data/manifest_v3.json`; final and transfer sets are evaluated once after selection and never used for search, feedback, or experience
- Source/config identity: captured per run in `frozen_source_manifest.json`
- Experience repository: none exposed to the model; `tnlab/experience.py` is validation-only

## Research Question

Under a fixed single-island OpenEvolve configuration, can model-generated deterministic changes to the tensor-network contraction path search reduce development-set contraction cost relative to the fixed initial candidate and the strongest predefined per-case baseline?

## Falsifiable Hypothesis

At least one of five independent 15-iteration discovery runs will produce an admitted candidate whose complete development-set geometric cost ratio to the strongest predefined baseline is lower than the initial candidate's ratio, with zero evaluator failures and reproducible paths. If no eligible run satisfies this rule, the hypothesis is not supported. A result with missing evidence or fewer than 15 recorded iterations is inconclusive and is not promoted to final evaluation.

## Single Planned Factor

- Factor: OpenEvolve model-generated algorithm changes during discovery
- Treatment: five independent runs using the frozen configuration below
- Control: the unchanged `initial_program.py`, evaluated with the same evaluator and development cases
- No prompt, evaluator, data, resource, model, or selection setting may be changed after the first calibration request.

## Fixed Conditions

- Initial candidate: `initial_program.py`; SHA-256 is captured at run creation
- Model: `deepseek-ai/DeepSeek-V3.2`; temperature and token limits are frozen in `config.yaml`
- Selection: one island, one parent mutation, two top programs, two inspirations, one worker
- Feedback: `openevolve_recent`; no experience retrieval; final and transfer data are never prompt inputs
- Evolution: diff-based, EVOLVE blocks enforced, max code length 12000, random seed 42
- Evaluation: development v2 only during search; three deterministic repeats per case; 10 second case limit; peak limit `2**20`
- Baselines: run `run_baselines.py --set develop_v2.json` for discovery and independently run `--set final_v3.json` and `--set transfer_v3.json` only for post-selection reporting; v3 held-out outputs never enter search
- Search budget: 15 iterations per run; total discovery request ceiling 75, with at most 20 requests reserved for probe/calibration/abnormal termination inside the 100-request ledger
- Calibration ceiling: 5 total reservations including model listing and probe; one calibration completion returns one diff and is checked for delimiters, interface contract, path legality/determinism, and a **strictly lower-cost controlled improvement on the fixed `PREFLIGHT_CASE`**
- Runner: container mode only for formal evaluation; image source and dependency hashes are captured and runner archive is required
- Primary outcome: development-set geometric cost ratio to strongest predefined baseline among valid candidates
- Secondary outcomes: initial-relative score, valid-candidate rate, failure classes, request and token totals, prompt hashes, parent/inspiration IDs, peak elements, search and wall time

## Calibration Rule

Calibration must pass all machine-checkable tasks before discovery. The model must produce parseable one-block diffs for the protocol task, preserve `find_path(inputs, output, sizes, seed=0)` for the interface task, return a legal deterministic path for the legality task, and make a **strictly lower-cost controlled improvement on the fixed `PREFLIGHT_CASE`**. Equal cost, regression, malformed output, or any failed task stops the study. Calibration does not use the development-set aggregate as its improvement criterion; discovery candidates are evaluated independently on the full `develop_v2.json` set. Correctness gates are never relaxed.

## Failure Attribution

Only observed evidence is recorded as fact. Error classes are request/service, output protocol, API/knowledge, syntax/interface, path semantics, resource, nondeterminism, objective regression, evidence/protocol, or unknown. Model explanations are hypotheses and are not promoted to experience without independent evidence. No final or transfer result is used for prompt feedback or experience.

## Invalid-Run Criteria

A run is invalid for the primary comparison if its registration copy or frozen manifest is missing, the request ledger cannot attribute its requests by run ID, the iteration journal is missing, fewer than 15 iterations are recorded, the independent best-candidate score differs from the framework score, the runner/source freeze cannot be verified, or any final/transfer result entered search context.

## Decision Rule

Select the best eligible discovery candidate by development primary outcome. Ties are resolved by candidate code SHA-256. Run final and transfer evaluation once for that selected frozen candidate, without returning results to search. Report supported, not supported, or inconclusive together with deviations and evidence gaps.

## Results

- Calibration: pending
- Discovery runs: pending
- Selected candidate: pending
- Final/transfer evaluation: pending
- Deviations and interpretation: pending

## Evidence Checklist

- [ ] Calibration request records and machine-checkable outputs
- [ ] Five run IDs and per-run request attribution
- [ ] Registration copy and hash in every run directory
- [ ] Iteration journals, prompts, responses, diffs, candidates, artifacts, and checkpoints
- [ ] Frozen source, dependency, data, and runner image manifests
- [ ] Independent development recheck
- [ ] One-time final and transfer report for the selected candidate
