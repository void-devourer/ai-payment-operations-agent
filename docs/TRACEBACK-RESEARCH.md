# TraceBack: independent feasibility and prior-art assessment

Date: 2026-10-10. Status: research note, not an approved project or implementation plan. The payment project remains separate; this note creates no TraceBack implementation.

## Assessment

TraceBack is a credible direction for a bounded software-engineering investigation. Its broad idea is established: compare executions, vary inputs or transformations, replay, and minimize a failure-inducing difference. A defensible contribution would be a measured improvement or a useful, carefully constrained implementation. Neither originality nor hiring impact has been demonstrated.

The pasted recommendation's DataHub/OpenRCA/RCAEval comparisons do not establish a technical gap. A lineage display and an observational telemetry diagnosis task are weaker direct comparisons than the intervention and minimization systems below.

## Closer primary sources

| Existing approach | Established capability | Consequence for TraceBack |
| --- | --- | --- |
| [Delta debugging, described by its author](https://www.debuggingbook.org/html/DeltaDebugger.html) and [change isolation](https://www.debuggingbook.org/html/ChangeDebugger.html) | Repeated tests reduce failure-inducing inputs or differences. `ddmin` finds a **1-minimal** set: removing any one remaining element no longer reproduces the target failure. That is not a guarantee of globally minimum cardinality. Outcomes include unresolved tests. | Plain delta debugging is an essential baseline. Calling intervention itself novel would be inaccurate. Interactions and masking require more than testing candidates individually. |
| [BugDoc, SIGMOD 2020](https://arxiv.org/pdf/2004.06530) | Uses provenance and iterative new pipeline executions to infer concise explanations of computational failures; evaluates cost, precision, and recall. Its search considers parameter combinations and expensive execution costs. | This is direct related work. Review its assumptions and runnable artifact before claiming a new diagnosis algorithm. A two-version change set is a possible scope difference, not automatically a new contribution. |
| [mlwhatif, VLDB 2023](https://www.vldb.org/pvldb/vol16/p4002-grafberger.pdf), [source](https://github.com/stefan-grafberger/mlwhatif) | Generates data, operator, and model patches for Python ML pipelines, executes variants, and optimizes shared work with a joint execution plan. | Selective reruns and reuse across interventions already exist. Compare optimization choices or reuse infrastructure; do not claim caching alone as the insight. Its analysis task is adjacent, not identical to finding a minimal regression-inducing change set. |
| [Differential Provenance, HotNets 2015](https://haeberlen.cis.upenn.edu/papers/diffprov-hotnets2015.pdf) | Compares faulty and reference network events, modifies base facts, and replays to explain differences. It discusses why naive graph differences include consequences as well as causes. | Good/bad execution comparison plus replay has clear precedent, albeit in a different domain. The choice of reference and allowed changes matters. |
| [DVC reproduction](https://doc.dvc.org/command-reference/repro) | Tracks declared stage dependencies and outputs, caches artifacts, and reruns affected stages in dependency order. | A fair performance baseline includes dependency-aware caching. Full rerun is useful for correctness and cost accounting, but is insufficient as the only competitor. |
| [Git bisect](https://git-scm.com/docs/git-bisect) | Tests revisions to locate a change in good/bad status in repository history. Supports automated tests and skipped revisions. | Useful when a suitable revision history exists; does not directly solve arbitrary subsets of simultaneous data and code changes. Do not describe TraceBack as merely faster bisect. |
| [Query causality and responsibility](https://www.vldb.org/pvldb/vol4/p34-meliou.pdf) | Distinguishes provenance from causes of query answers and studies the complexity of causal responsibility. | Dependency membership does not establish causal responsibility. Terms such as cause, contingency, and minimality need a precise experimental definition. |

## Correct the problem definition first

Different final outputs do not automatically mean a regression. Suppose the old total is 100. Valid new rows should raise it to 120, but a faulty transformation produces 90. Repairing the transformation should give 120, not restore 100. An oracle that rewards matching the previous total could prefer deleting valid data.

Require an explicit regression predicate: a violated invariant, expected labelled output, or a trusted reference implementation run on the **same** input. Specify whether exact equality or a tolerance is appropriate. Without a trustworthy oracle, report an observed influence on output rather than a verified bug cause.

Keep three questions distinct:

1. **Failure-inducing set:** Which subset of new changes, applied to the old configuration, reproduces the specified failure?
2. **Repair set:** Which changes reverted from the new configuration make the predicate pass?
3. **Historical cause:** Why did a real incident happen, including environmental and human factors?

These need not have the same answer. Replay supports statements about the tested configurations and recorded dependencies. It cannot establish unrecorded real-world causes.

Hybrid versions can be invalid: a new function may require a new schema. Such combinations are **UNRESOLVED**, not healthy or reproductions of the target regression. State change granularity (whole stage version, parameter, file, or row group), compatibility constraints, and the search budget. Report a verified witness and its achieved minimality, not “the smallest cause” without exhaustive certification. Several valid explanations may exist.

## A feasible research question

**Proposed hypothesis, not a result:** For declared, deterministic Python pipeline DAGs with expensive shared stages, can cost-aware ordering of change-set tests and reuse of identical intermediate artifacts reduce end-to-end diagnosis cost versus ordinary delta debugging with the same cache, while preserving verified explanations?

This has concrete design choices: cost estimation, test ordering, cache identity, invalid combination handling, interaction coverage, and stopping rules. A negative result is valuable if it explains where the extra machinery does not help.

For 4–8 weeks, constrain the prototype to local, trusted, explicitly registered stages; frozen input artifacts; unchanged DAG topology; compatible old/new stage interfaces; and a declared environment. Use explicit manifests before attempting automatic dependency discovery or arbitrary Python instrumentation. Start with stage and configuration changes, then add versioned input partitions only if the experiment warrants it. No distributed deployment, external API replay, or generative UI is needed to answer the question.

Cache keys must cover all declared inputs, code/version, parameters, and environment. Compare selective execution with clean execution. Repeated identical results are a useful check, not proof of determinism or dependency completeness. Missing dependencies and stochastic stages should test detection/abstention limits; do not promise automatic discovery of either.

## Fair evaluation

Use the same oracle, change units, compatibility constraints, and budget for every method:

- Single-change testing: simple and interpretable, with known limitations for interactions.
- Plain delta debugging with clean reruns.
- Plain delta debugging with dependency-aware caching.
- Proposed ordering/reuse policy using that same execution substrate.
- Exhaustive enumeration for small change sets, to establish all valid witnesses and minimum cardinality. Use Git bisect additionally when the task supplies comparable revision history.

Dependency reachability is a candidate-filter ablation; final-output comparison is a detector. Neither should be the main opponent of a diagnosis algorithm. A dependency slice should be conservative: pruning from one run's observed path can lose changes that alter control flow.

Measure reproduced-witness validity, verified 1-minimality, global-minimum gap where enumeration is feasible, unresolved/abstention rate, stage executions, wall time, memory/storage, and cache/registration overhead. Top-1/top-3 rankings are secondary: interactions require sets, and multiple valid explanations make one injected label an incomplete oracle. Include masking, cancelling effects, two necessary changes, alternative causes, invalid hybrids, and irrelevant changes. Count hashing, serialization, and failed experiments in cost.

Public data provides inputs, not labelled regressions or validated user demand. Separate injected benchmark cases from genuine historical bugs; hold out pipeline families, not merely random variants of the same template. ML relevance follows from evaluating ML preprocessing failures; the core system does not itself demonstrate training, generalization, or model-serving expertise. Add learned ranking only if enough independent examples and a clear baseline weakness exist.

## Proposed one-week go/no-go experiment

This is a recommendation for a later decision, not work started now.

1. Define the oracle and change semantics for three small explicit pipelines. Reproduce a genuine open-source regression if one is available, otherwise label all cases synthetic.
2. Build roughly a dozen cases covering single causes, interactions, legitimate data changes, invalid hybrids, and hidden-state failure. Keep candidate sets small enough for exhaustive checks.
3. Run single-change testing and delta debugging with and without caching. Confirm clean/selective execution agreement and inspect where time actually goes.
4. Try one cost-aware scheduling idea. Report every case, including regressions and setup cost; reserve some cases before tuning.
5. Continue only if there is a repeatable, useful limitation and a plausible improvement under equal budgets, or direct user evidence that the constrained tool is useful. Otherwise narrow the hypothesis, contribute to an existing tool, or stop the experiment. A large application should not be the default next step.

All scope, timeline, metric, and go/no-go proposals above are engineering judgments. No benchmark has been run for TraceBack, no performance gains are claimed, and no new project has been approved by this note.
