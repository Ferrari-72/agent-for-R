# Read-only experiment visualization

This optional presentation layer is deliberately separate from solver execution, scoring, selection, and research-data admission.

- `resource_pilot_data.py` validates the versioned row contract and computes descriptive successful-row summaries. It imports no plotting or solver modules.
- `resource_pilot_report.py` reads a saved public resource-pilot JSON and writes a standalone HTML report. It does not execute candidate code, update the source JSON, choose a solver, or send network requests.
- Tests cover failure retention, validation of missing/invalid metrics, HTML escaping, and report rendering.

Run the tests from the repository root:

```sh
python -I -B -m unittest discover -s experiment/visualization -p 'test_*.py' -v
```

Render an existing resource-pilot summary to a new HTML path:

```sh
python -I -B experiment/visualization/resource_pilot_report.py \
  experiment/deliverables/resource_pilot_20261027/summary.json \
  experiment/results/resource_pilot_report.html
```

The report facets by structure so different sizes are not silently pooled into one ranking. It shows one metric per chart, direct solver labels, independent zero-based axes, and the exact per-run table including failures. Medians are descriptive summaries of successful repeats only; they do not replace the complete denominator. Peak tensor elements are separate from process RSS. Texture is opt-in and the report includes light/dark themes, keyboard-focus tooltips, and a table.

All structures in an engineering resource pilot are exposed. The report labels them accordingly and does not certify held-out status or research eligibility. The visualization code is optional; the benchmark runner does not import it.

## Verified delivery on 2026-10-27

The saved report is `../deliverables/resource_pilot_20261027/report.html`. It uses the final 12-structure, 168-row summary, with 36 charts and 252 metric marks. Both `success` (the resource-pilot result contract) and `ok` (legacy input fixtures) count as successful statuses; original row statuses remain visible.

Eight tests passed in the pinned network-disabled Linux image. Linux CLI rendering and static HTML parsing confirmed the 12 structure options, all 168 execution rows, and exact equality of the embedded summary with the unchanged input JSON. The report and source hashes are recorded in `../deliverables/resource_pilot_20261027/visualization_validation.json`. Light and dark palette validation was executed through the validator's exported `validate` function; both returned `ok: true` (the earlier renamed `.mjs` CLI invocation did not run its filename-gated entrypoint).

Browser interaction and screenshot review remain unverified. Automatic approval rejected the Chrome invocation with `--no-sandbox` and also rejected the retry after that flag was removed. No sandbox setting or permission rule was changed. Static parsing and unit tests do not establish rendered layout or interaction correctness.
