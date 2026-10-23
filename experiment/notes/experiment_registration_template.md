# Experiment Registration

Complete this record before starting a model-backed run. Keep one copy with the run artifacts and do not revise the preregistered fields after seeing results; record deviations separately.

## Run Identity

- Planned run ID:
- Date/time (UTC):
- Responsible researcher:
- Intended output directory:
- Model and provider:
- Request budget and database:
- Request database identity/hash and request ID at start:
- Development-set manifest/hash:
- Code/config revision or hashes:
- Experience repository version/hash (or `none`):

## Research Question

State one question this run is designed to answer:

## Hypothesis

State a falsifiable expected outcome, including the metric and direction. Avoid claiming that a single run establishes general performance:

## Model Capability Calibration

Complete before interpreting search failures. Use a fixed, non-held-out calibration set with machine-checkable outcomes; calibration requests must be included in the registered budget.

- Calibration suite/version/hash:
- Diff-format compliance threshold and observed result:
- API-contract task threshold and observed result:
- Basic path-legality threshold and observed result:
- Controlled local-improvement threshold and observed result:
- Interpretation if calibration is below threshold (limit claims; do not relax correctness gates):

## Failure Attribution

Record observations separately from causal explanations. A model-generated explanation is a hypothesis unless independently verified.

- Observed failure classes and counts:
- Request/service failures:
- Output protocol failures:
- API/knowledge failures:
- Syntax/interface failures:
- Path-semantic failures:
- Resource/determinism failures:
- Objective regressions:
- Evidence/protocol failures:
- Causal hypotheses and evidence needed to test each:

## Single Changed Variable

Name exactly one planned factor that differs from the comparison run:

- Factor:
- Treatment value:
- Control value:
- Why other settings remain fixed:

If more than one factor changes, split the work into separate runs or label it exploratory and do not attribute the result to one factor.

## Fixed Conditions

- Initial candidate and SHA-256:
- Prompt template and SHA-256:
- System prompt/config SHA-256:
- OpenEvolve selection/evolution settings:
- Development-set name and manifest SHA-256:
- Maximum iterations:
- Request/token budget:
- Candidate evaluation repeats, timeout, and resource limits:
- Execution mode and runner image ID:
- Random seeds and determinism policy:

## Outcomes and Decision Rules

Specify before the run:

- Primary outcome and calculation:
- Secondary outcomes:
- Invalid-run criteria (for example missing iteration journal or mismatched independent score):
- Rule for deciding whether the hypothesis is supported, not supported, or inconclusive:
- Whether this is exploratory or part of a repeated-run protocol:

## Results (Complete After Run)

- Actual run ID/output directory:
- Start/end time (UTC):
- Completed iterations and rejected attempts:
- Candidate admission rate:
- Best development score and independent recheck:
- Baseline comparison:
- Prompt/request/token totals:
- Experience entries exposed to the model (IDs and version):
- Model calibration result and interpretation boundary:
- Deviations from preregistered settings:
- Outcome: supported / not supported / inconclusive:
- Interpretation and limits:
- Follow-up question:

## Evidence Checklist

- [ ] `iteration_journal.jsonl`
- [ ] `process_summary.json`
- [ ] `experiment_process.md`
- [ ] Per-iteration prompt and model response artifacts
- [ ] Per-iteration `source_diff.patch` and candidate source
- [ ] Evaluation artifacts and stage records
- [ ] `development_report.json`
- [ ] Frozen code, config, benchmark, and runner hashes
- [ ] Independent best-candidate recheck

Do not use final or transfer-set results to modify prompts, candidates, or the preregistered protocol. Any change prompted by held-out results requires a new protocol and a new untouched evaluation set.
