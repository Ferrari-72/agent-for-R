# Framework Concepts: Parents and Inspirations

Use this note when describing parent selection or multi-parent evolution in an evolutionary coding framework. Verify the implementation before labeling a framework.

## Parent

A **parent** is the program selected as the direct starting point for one offspring. In diff-based evolution, the model receives this program as the current code, and the resulting patch is applied to it. Unless the implementation says otherwise, one iteration with one `parent_id` is a single-parent mutation, even if other programs are also shown in the prompt.

## Reference programs

Frameworks may also show **top programs**, **elite/archive members**, **previous attempts**, or **inspirations**. These can provide code examples, performance context, or alternative ideas. They are prompt context, not additional genetic parents, unless the framework explicitly combines their code or representations to construct the offspring.

For this OpenEvolve integration, `sample_from_island()` returns one parent and a list of inspirations. `_run_iteration_worker()` uses `parent.code` as both `current_program` and `parent_program`; generated diffs are applied against that code, and the child records that parent's ID. Top programs and inspirations are separately passed to prompt construction. Therefore the current flow is **single-parent mutation with multi-program prompt context**, not multi-parent code crossover.

External framework comparisons must keep three claims separate:

- **Capability**: a framework has a diff, full-rewrite, crossover, or prompt-evolution implementation somewhere in its source.
- **Configuration**: a particular run enables one of those mechanisms, with explicit probabilities, inspiration counts, history depth, and budgets.
- **Observed offspring construction**: the run actually applied the enabled mechanism, and its parent identities/contributions are recorded.

The source survey verified that ShinkaEvolve has separate `diff`, `full`, and `cross` prompt modes at commit `8adc053a2ce4511ad2ac310e004c530a73fb974a`; CodeEvolve has inspiration-aware prompting, lineage history, and meta-prompting at commit `c077959e1ab24b060aaa6d4c563bca2e9cbe8617`. These findings establish framework capability, not that every configuration or every offspring is multi-parent. The current tensor-network experiment remains single-parent unless a registered treatment enables and records an explicit recombination operator.

## Multi-parent recombination

Call a method **multi-parent** only when two or more selected parents make a defined, implementation-level contribution to the offspring, for example by merging code blocks, combining structured plans, or applying a crossover operator. A prompt that merely displays several candidate programs does not establish recombination.

A reproducible multi-parent description should state:

- how many parents contribute and how they are selected;
- how conflicts, incompatible interfaces, and duplicate changes are resolved;
- how parent identities and contributions are recorded;
- what single-parent control receives the same model, prompt budget, evaluation budget, and selection opportunities.

## Reporting template

> Each offspring is initialized from **[one/multiple]** selected parent program(s). The selection rule is **[rule]**. Other programs included in the prompt are used as **[references/inspirations]** and **[do/do not]** contribute code directly. Offspring construction is **[mutation/crossover/other]**, implemented by **[mechanism]**. We record **[parent IDs and contribution metadata]**. The comparison against **[control]** holds **[model, request budget, evaluation budget, and other controls]** fixed.

Avoid calling a system "multi-parent" based only on the number of programs displayed to the model. Also distinguish a framework's capability from the behavior enabled in a particular experiment configuration.
