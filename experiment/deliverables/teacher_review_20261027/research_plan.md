# Assistant work plan for teacher review

Date: 2026-10-27. Status: assistant-proposed research design, not an approved registration or execution authority.

This stage concerns engineering validation of three path-search prototypes on public, hand-written synthetic structures. It does not establish performance on the proposed circuit or lattice distributions. All counts, probabilities, limits and allocations below are assistant design decisions for review, not values justified by completed pilot measurements. This document specifies subsequent work; it does not claim that generation, topology auditing, resource calibration or formal experiments have occurred.

## 1. Question and scope

Primary question: under one declared search budget, can program evolution improve a human-designed reusable contraction-path search program on development instances, and does the development-selected program retain its behavior on different circuit topologies at the same size-depth cells?

Larger circuit sizes and lattice networks are separate transfer questions. Differences among the three startpoint families are exploratory: three model runs per family constitute a feasibility/search-behavior pilot, not a powered comparison. No primary-test or transfer result may enter evolution, feedback, configuration changes or candidate selection.

The scientific object is a reusable path-search program, not an instance-specific path. A candidate receives `find_path(inputs, output, sizes, seed=0)` and returns exactly n-1 dynamic-position binary merges for n input tensors. Scoring is symbolic and independent of candidate code. The proposed tasks use no slicing, truncation, explicit tensor preprocessing or numerical tensor contraction. The pinned cotengra 0.8.3 binary-tree FLOPs convention excludes unary local reductions as preprocessing; this limitation is disclosed rather than counted as arithmetic performed by the candidates. Raw input sizes still contribute to peak elements. FLOPs/path results alone establish neither numerical contraction speed nor algorithm novelty.

## 2. Instance design and proposed topology rules

| Split | Proposed family and size-depth cells | Cases per cell | Total | Role |
| --- | --- | ---: | ---: | --- |
| Development | 1D circuits: qubits {8, 12} x depths {4, 8} | 4 | 16 | Evolution feedback and selection |
| New-topology primary test | Same 1D family and exactly the same qubits {8, 12} x depths {4, 8}; structurally disjoint from development subject to graph-equivalence review | 6 | 24 | One-time same-scale generalization report |
| Scale transfer | Same 1D family: qubits {16, 20} x depths {8, 12} | 4 | 16 | Separately reported size extrapolation |
| Lattice transfer | Connected random subgraphs of 4x4 and 5x5 square grids | 6 | 12 | Separately reported cross-family transfer |
| Engineering anchors | Existing public hand-written small chain/grid structures | Existing fixed cases | Outside scientific splits | Prototype correctness checks only |

The development and primary distributions therefore differ in sampled topology, not in their size-depth grid. The 16/24 allocations mean 4/6 cases in each of four cells; scale transfer has four cells with four cases each. These are practical allocations to be tested for feasibility, not a power calculation.

**Proposed circuit generator.** Number qubits from 0 to q-1. Depth d means d two-qubit placement layers. Start with one rank-one dimension-2 input-state tensor per qubit. In layer l, the eligible pairs are (0,1), (2,3), ... when l is even and (1,2), (3,4), ... when l is odd. Independently retain each eligible two-qubit gate with probability p=0.75; omit it otherwise. Retained gates have four dimension-2 ports, with input/output wires connected in layer order. An omitted gate leaves its wires unchanged and introduces no identity tensor. Keep every terminal qubit wire in the full-state output. Do not simplify or fuse tensors before scoring.

Use a pinned PRNG, a documented ordering of draws, and separately recorded topology RNG seeds for split/cell/attempt reproducibility. The random draws must change which gate tensors and wire connections exist; changing gate entries or numeric-value seeds is insufficient. Reject a circuit draw with no retained two-qubit gate. Duplicate structural draws are rejected by the equivalence rule below. This is an explicit proposed generator, not a claim that an existing `circ_ansatz_1D_brickwork` implementation already has these semantics.

**Proposed lattice generator.** Begin with the nearest-neighbor edge set of the specified square grid. Independently retain each possible edge with p=0.75 and reject the whole draw unless all grid vertices remain connected. Put one tensor at each vertex, one contracted dimension-2 bond per retained edge, and one open dimension-2 physical index per vertex; output all physical indices. Reject equivalent accepted graphs. This gives a random connected grid-subgraph family with six intended distinct structures per size. A fixed square lattice with different numeric seeds is one structure, not six. Whether the existing lattice-equation implementation can express this proposed family remains to be checked.

**Finite generation and equivalence.** Visit each cell in a fixed documented order and accept the first required number of valid, structurally distinct draws. Allow at most 1,000 attempted draws per cell. Each attempted draw has at most five seconds for its complete equivalence comparison against accepted structures and the available historical reference set; a comparison timeout is unresolved and the draw is not accepted. These are proposed bounds whose practicality still needs a structure-only pilot. A short cell means incomplete generation: stop and revise the design version before solver scoring, rather than filling it after seeing outcomes.

Compare tensor-index incidence graphs with tensor arity/role, index dimension and open/contracted status preserved. Index names, tensor listing order, arbitrary qubit/vertex IDs, topology seeds, gate values and file hashes cannot establish distinctness. Review equivalence under relabeling, including lattice symmetries; store the equivalence method and its result, not just a hash. Hashes may identify artifacts or accelerate screening, but a different hash does not prove a different graph. Accepted primary cases must pass comparison against all development cases as well as within-split duplicates. Claims of being previously unexposed additionally require an independent custodian/reviewer to assess historical exposure and the adequacy of this equivalence definition. That independent review and custody arrangement remain pending; “new-topology” in the table is an intended test condition, not a verified unseen label.

## 3. Comparators, scores and failures

Predeclare four executable comparators: Greedy, RandomGreedy, serial cotengra simulated annealing, and the fixed OMECO TreeSA adapter. Pin one configuration per comparator before formal scoring; do not tune against test outcomes. The baseline envelope is the per-instance minimum FLOPs across the four successful baseline slots. It is a descriptive oracle, not a fifth runnable solver, and its four executions are charged to the budget.

- Development fitness is the geometric mean of candidate FLOPs / baseline-envelope FLOPs over all 16 development instances, equally weighted. It is finite only when all required baseline and candidate slots are complete and valid.
- Select among candidates with complete development evidence, valid paths, no resource-limit violation and matching deterministic repeats. Rank by that same full-development geometric mean; candidate source hash, family identifier and run identifier give a fixed tie-break order. Beating a baseline is not an eligibility requirement.
- The main test display is candidate/OMECO FLOPs, with geometric means only over the complete declared split when all required slots succeed. Also report each comparator, the envelope, per-instance status/path, peak elements and trusted runtime. Show candidate/generation-zero changes for development search behavior.

With fixed positive complete baseline values and the same equally weighted instances, changing the denominator from envelope to OMECO multiplies every candidate geometric mean by the same constant and does not change ranking. This fact does not justify changing included rows, handling failures differently or sampling cases by score.

Keep every declared slot. Malformed/partial path, exception, timeout, memory kill, peak-cap breach and nonrepeatable output retain distinct statuses and counts. A failed candidate slot makes complete-set fitness infeasible (+infinity for ordering), not a finite survivor-only geometric mean. A failed baseline slot leaves the reference incomplete and must be resolved through a documented protocol decision before ranking, not by omitting that row or comparator. Failure reporting always uses the full split denominator. Do not retry until success or substitute an external solver to hide failure. Any fallback implemented inside the candidate belongs to that candidate and its time budget; tag it in diagnostics where possible.

## 4. Seeds, repeats and selection units

Topology RNG seeds drive the retain/delete decisions and identify reproducible draws; graph-equivalence review determines structural distinctness. They are separate from the candidate algorithm seed, fixed at 0 in the proposed study. Use baseline seed 0 only where the pinned API actually accepts it. The OMECO adapter requires caller seed None; its internal randomness is not controlled by pretending to pass 0. RandomGreedy likewise requires its documented internal-trial configuration rather than an unsupported caller seed. Record these limitations and each baseline's exact randomness configuration. An algorithm seed never changes the case topology.

For every candidate-instance slot, run the same candidate bytes, case, algorithm seed 0 and pinned image twice in fresh processes. Require byte-for-byte identical validated paths; keep the first path/score only after both pass. A mismatch makes that slot nonrepeatable and the candidate ineligible. Repeats are engineering checks and cannot be selected by taking the better score. Baselines have one execution per comparator-instance slot; any development-only variability profiling before freeze is additional, separately recorded pilot work.

The 3 runs within each of 3 startpoint families use independently recorded model-run seeds where supported, separate evolution histories and equal request budgets. If the provider cannot enforce such seeds, record that limitation and do not claim seed-controlled independence. These model-run replicates study search variability; they are different from solver seed 0 and deterministic process repeats. Structurally distinct cases are the instance-level units for generalization, subject to their generator/split dependence. Neither two repeats nor 99 candidate evaluations create additional independent test instances.

Preserve the best eligible development candidate from each of the nine runs for descriptive run-level reporting. Nominate one overall program by the same development-only ranking and fixed tie-break before accessing test results; do not build a per-instance portfolio. Independently replay that nominated program on the full development set with two fresh executions per instance under the frozen artifacts. A replay failure is reported and blocks the proposed later test; it does not trigger selection using test results or an uncharged replacement search. Testing every run-best program would be a different, explicitly rebudgeted design.

## 5. Search allocation, execution counts and cost accounting

Each of 3 startpoint families receives 3 model runs and 10 proposal rounds per run: 3 x 3 x 10 = **90 proposals total**, not 90 per family. There is one model request and at most one SEARCH/REPLACE patch per round. Generation zero is evaluated once per run, so 3 x 3 = **9 generation-zero evaluations** without proposal requests. Total reserved candidate evaluations are 90 + 9 = **99**. Every proposal, including a rejected patch, failed parse, invalid candidate or timeout, consumes its round; there are no hidden repair requests or free retries.

| Development work | Calculation | Reserved solver executions |
| --- | --- | ---: |
| Candidate search, including generation zero | 99 evaluations x 16 cases x 2 deterministic repeats | 3,168 |
| Four fixed baselines, reused by all runs | 4 comparators x 16 cases x 1 execution | 64 |
| Independent replay of the one nominated program | 1 program x 16 cases x 2 fresh executions | 32 |
| Total of these development components | 3,168 + 64 + 32 | **3,264** |

An evaluation reserves 32 candidate executions. A rejected/invalid proposal can fail before workers start, so 3,168 is the planned execution allocation, not a claim that all workers must run; record actual requests, evaluations attempted, executions launched and failures separately. Baseline slots are shared fixed references, not rerun free of charge for each candidate. Additional baseline profiling, prototype/oracle checks, topology-equivalence work and any extra independent replays are outside this table and must be accounted for separately.

For the one nominated program, the proposed later splits would add: primary 24 x 2 candidate executions + 24 x 4 baseline executions = **144**; scale transfer 16 x 2 + 16 x 4 = **96**; lattice transfer 12 x 2 + 12 x 4 = **72**. Thus those later solver components add 312 and the combined allocation would be 3,576. These are future budget arithmetic only, with no authorization to generate or execute those splits now. Trusted scoring processes, orchestration, storage and generation/equivalence review are additional work, not included as solver executions.

Proposed per-invocation solver limits are 10 seconds wall time, 1 CPU, 2 GiB memory, total memory-plus-swap capped at 2 GiB, 64 PIDs and no network, applying to candidates and the four comparators. Imports and conversions count inside solver time. Independent symbolic validation/scoring runs in a separate trusted process with a proposed 10-second/1-CPU/2-GiB limit per invocation; implementation and adequacy need pilot evidence. Candidate peak is capped at 2**30 elements; elements are not bytes, and an earlier actual memory failure remains a failure. These limits are design decisions, not demonstrated feasible settings.

The 3,264 development solver executions imply at most 32,640 seconds (9 hours 4 minutes) of their allocated one-CPU solver time if every slot reaches its 10-second cap. This is not an elapsed-time prediction or a total infrastructure bill: trusted scoring, startup, generation, equivalence checks and pilot work are excluded. Apply the same distinction to later split costs.

Model cost has a separate scope: at most 90 proposal requests, with generation zero and solver repeats making no proposal calls. Sum actual input/output tokens at the chosen provider/model rates for proposal cost; rates, input-token envelope, total monetary cap and stopping rules are still pending. Any tokenizer/provider calibration requests sit **outside** the 90 proposals and require a separately stated pending request/token/money allowance. They are not free, cannot silently consume search rounds, and currently have no paid authorization. No total paid-cost feasibility claim is available yet.

## 6. Three editable startpoints

1. Recursive hypergraph partition construction: dimension-weighted hyperedge partition objective, explicit balance penalty, deterministic seed-0 tie-breaking, recursive stopping and a stated local subproblem method.
2. Whole-tree search: explicit binary reassociation rotations over an incumbent tree, seeded proposals, best-so-far retention and bounded annealing/restart policy. Initialization may be deterministic or partition-based; RandomGreedy is not imposed.
3. Budgeted beam construction: exact leaf-partition state, bounded expansions/width, deterministic scoring/ties and a complete valid incumbent retained throughout; outer-product pairs remain eligible.

All three expose the same dynamic-position interface and permit whole-function replacement. Share correctness-critical boundary/cost/path utilities, not a search loop that forces all families into the same method. Compare each evolved program with its own generation zero and the fixed baseline suite. Hand-calculated/oracle fixtures and independent evaluator checks on the public synthetic anchors support prototype engineering only; they do not establish the proposed workload's resource feasibility or scientific gains.

The existing 2,048-token response ceiling is not presumed sufficient for whole-function replacement. Once a provider/model is identified, the assistant must use its exact tokenizer to measure representative SEARCH/REPLACE rewrites for all three startpoints. If they do not fit, revise the protocol or ceiling before budget registration without giving one family a hidden restriction or bypassing the one-patch rule. Exact-tokenizer access and these measurements remain pending; none are claimed in this package.

## 7. Next evidence and current boundary

The assistant's next deliverable, after the appropriate subsequent work is authorized, is a concise pilot evidence note: exact generator semantics and structural-equivalence results with rejection/time counts; execution/scoring resource observations on permitted development-like synthetic cases; measured rewrite token lengths and a priced request allowance; and the proposed independent custody/exposure-review arrangement. Record negative findings as well as successes. If evidence is absent or a cell cannot be filled, state that plainly and revise the design before registration rather than claiming validation. No power or representativeness claim follows from the chosen sample counts.

Teacher review can assess whether the three editable algorithm families, matched-scale primary question and separately budgeted transfers are suitable for the next stage. Resource feasibility, exact tokenizer fit, independent custody and unseen-status review are unresolved. This document is an assistant work proposal and does not imply teacher approval.

This proposal grants no authority for research-dataset materialization, formal solver experiments, model calls, request-ledger access/creation, paid calibration, held-out/final/transfer access or execution, or research-data publication. The completed stage evidence is limited to public synthetic prototype engineering validation, recorded separately in validation_notes.md and validation_summary.json. The user has authorized uploading this review package; that scope does not extend to formal research data or paid execution.
