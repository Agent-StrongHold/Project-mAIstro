# M8-D5 research note — induction and reuse of successful canonical Graph patterns across Goals

Leaf: #929. Epic: #903. Initiative: #879.

## Hypothesis

Successful Runs can be mined into reusable Graph motifs/templates that improve
future planning speed and reliability without overfitting to one task
instance.

## Canonical seams

The experiment runs on the real execution and template seams, not beside them:

- **Mining reads the canonical spine.** Every historical Run is a real
  `Run` over a `GraphSnapshot` (`GraphSnapshot.from_graph` /
  `snapshot.materialize()`) with `NodeRun`/`Attempt`/`AttemptResult`/
  `AcceptedNodeOutcome` records constructed exactly as
  `maistro.runs.model` validates them (`packages/maistro-core/src/maistro/runs/model.py`):
  a successful Run completes every NodeRun through a terminal physical
  Attempt projected via `AcceptedNodeOutcome`; a failed Run fails exactly one
  NodeRun with no accepted outcome and carries the Run-level error. Mining
  counts only `RunStatus.COMPLETED` records, and clusters by the kind-level
  structural signature of `run.graph.materialize()` — the isomorphism class
  of the topology once node identities are abstracted away. That reduction is
  what makes a motif a *pattern* rather than a replay of one Run.
- **Induced motifs are versioned canonical Graph candidates.** Each motif is
  registered through the real `GraphTemplate.from_graph` into the real
  `InMemoryGraphTemplateStore` (`packages/maistro-core/src/maistro/graph/templates.py`),
  then flipped to ``lifecycle="candidate"``. Per
  [ADR-082926-65bf](../adr/ADR-082926-65bf-template-versions-hold-a-candidate-before-they-become-active.md)
  a candidate stays addressable by exact version but no execution path
  resolves it: unversioned `store.get` ignores it and `require_template` —
  the execution door — refuses it. This is exactly the issue's deliverable
  constraint: reused Graphs remain versioned canonical Graph candidates
  until a human-audited promotion; nothing mined is executable by accident.
- **Reuse produces real Graphs.** Every reused Graph comes from
  `GraphTemplate.instantiate`: fresh node identities, `TemplateProvenance`
  carrying the exact version hash onto the Graph. Templates cite their mined
  evidence by aggregate (support, distinct instances, families) in the Graph
  description; execution identity (`run_id`/`node_run_id`/`attempt_id`) may
  not ride along — the shipped `RUNTIME_STATE_FIELDS` validator
  (SPEC-081226-bb3a R12) refuses such a template at construction, and the
  induction pipeline relies on that guard rather than re-implementing it.

Nothing canonical changed: no planner, no template promotion path, no flag,
no product code. The harness is `scripts/bench_graph_pattern_reuse.py`
(offline, deterministic, no network, no PostgreSQL) and the recorded numbers
live in `docs/benchmarks/graph-pattern-reuse-baseline.json`.

## Method

Four synthetic task families (`research-report`, `code-change`,
`data-extract`, `triage`) over the shipped node vocabulary (`AgentRole` plus
the pipeline kinds `llm.summarize` / `transform.extract_field`). A family's
stated `GoalSpec` names required kinds and orderings; per-instance jitter
relaxes one kind for some instances, so "the same goal" and "the same task
instance" are genuinely different things. Latent world truth scores a
candidate structure by coverage, stated orderings, downstream validation, and
size parsimony — no planner sees the truth function; outcomes are Bernoulli
draws against it, recorded as Runs.

Pipeline per seed (seeds 0–4, 600-run corpus, 400 held-out episodes, common
random numbers across arms so an identical structure yields an identical
outcome):

1. **Cluster + induct.** Successful corpus Runs are clustered by structural
   signature. A signature is inducted only with ≥3 successes across ≥2
   *distinct goal instances* — the anti-overfitting guard: a structure that
   helped one task instance alone is refused as an overfit trap.
2. **Plan held-out Goals three ways.** *scratch* — budgeted enumeration
   scored by a stateless heuristic (coverage, orderings, validation
   preference, parsimony; deliberately blind to history), one scoring
   round-trip per candidate; *reuse-naive* — retrieve by kind-overlap
   Jaccard, adapt by adding missing required kinds and re-chaining to stated
   orderings, fall back to scratch when retrieval or validation fails;
   *reuse-guarded* — identical, plus a trailing-success quarantine
   (window 20, min 8, threshold 0.55) fed by the same Run-completion feedback
   production already records, and a re-mining flywheel (every 50 episodes,
   over every successful Run so far, including successful fallbacks).
   A fourth probe arm (*reuse-transfer*) may only retrieve motifs that never
   observed the goal's own family.
3. **Drift.** At episode 200 the `data-extract` family's latent truth
   quietly tightens: unvalidated structures take a −0.38 penalty while the
   stated specs do not change (lean 0.48 → 0.10 success; the validated
   variant stays 0.46). Pre-drift motifs for that family go stale; only the
   outcomes reveal it.

Planning cost is a declared token-equivalent model calibrated to the shipped
planning seam (`LLMDagSynthesizer`: one fixed-prompt synthesis round-trip per
candidate, completion roughly linear in graph size): scratch pays 850 prompt
+ 60 per candidate explored + 45 per node; reuse pays 120 retrieval + 90 per
adaptation edit (~3 edits per round-trip). The model ships inside every
output payload so the numbers cannot be mistaken for measurements of a live
model.

## Record (seeds 0–4, mean ± std; 400 episodes each)

| arm | success | planning tokens | round-trips | stale-attributable failures | quarantines |
|---|---|---|---|---|---|
| scratch | 0.737 ± 0.017 | 1580.6 ± 4.3 | 10.30 ± 0.08 | 0 (by construction) | — |
| reuse-naive | 0.692 ± 0.016 | 120.0 | 1.00 | 18.6 ± 4.2 | 0 |
| reuse-guarded | 0.717 ± 0.033 | 181.6 ± 86.0 | 1.52 ± 0.73 | 7.4 ± 6.2 | 2.8 ± 2.2 |
| reuse-transfer (probe) | 0.719 ± 0.022 | 622.0 ± 19.0 | 5.35 ± 0.16 | 4.2 ± 2.4 | — |

Findings:

1. **The cost half of the hypothesis is confirmed, decisively.** Guarded
   reuse plans at 11.5% of scratch's token-equivalent cost (8.7×), and naive
   reuse at 7.6% (13.2×). Round-trips fall 10.30 → 1.00–1.52. Adaptation is
   nearly free in the common case (mean 0.002 edits guarded: the retrieved
   motif usually already covers the stated spec).
2. **The reliability half is where naive reuse fails.** Unguarded reuse is
   measurably *less* reliable than planning from scratch on every seed
   (0.692 vs 0.737, −4.5pp), and the loss is attributable: 18.6
   stale-attributable failures per 400 episodes — episodes where the reused
   motif failed while the common-random-number scratch plan succeeded. This
   is the overfitting/staleness failure class the issue warns about, and it
   is real even with the anti-overfit induction bar in place.
3. **A cheap outcome guard bounds most of the damage.** The trailing-success
   quarantine — fed only by Run-completion evidence production already
   records, no new telemetry — recovers ~two thirds of the regression
   (0.717, −2.0pp) and cuts stale-attributable failures 18.6 → 7.4, firing
   2.8 quarantines per run. Honesty note: the guard is not a solved problem.
   Seed 3 is a bad case where the guard's stale (18) matched naive's (16):
   after quarantining the first stale motif, retrieval promoted a second
   pre-drift motif of the same family and the window had to re-fill. Slow
   re-mining (the flywheel) is the corrective path that eventually replaces
   the family's motifs, but its convergence is not measured tightly enough
   here to claim the two mechanisms compose into full recovery.
4. **Transfer across task families is real.** The forced-transfer probe
   served 297/400 held-out Goals from motifs that never observed the goal's
   family, at 0.724 mean cross-family success (scratch: 0.737) with ~103
   honest scratch fallbacks. Structure, not family identity, is what carries
   a Graph — which is what makes cross-Goal reuse a pattern mechanism rather
   than a lookup table.
5. **Human inspectability survives induction.** Mined libraries stay small
   (12 motifs per seed, mean 2.42 nodes, max 4), every template documents
   its evidence (support/instances/families; 100% documented), every
   instantiated Graph carries exact-version `TemplateProvenance`, and every
   mined template sits at ``lifecycle="candidate"`` with the execution door
   (`require_template`) verified closed — checked mechanically per seed in
   the bench's `inspectability` report.

## Disposition: INCUBATE

The bar was: reuse must cut planning cost without an unbounded success
regression, and the guard must bound stale-pattern damage. All three hold
with margin on the cost side (8.7×) and adequately on the reliability side
(−2.0pp vs scratch's ±1.7 std; stale failures 7.4 vs naive 18.6). Not
GRADUATE: production adoption needs an owning milestone, a real Run-corpus
source (the synthetic families here are stand-ins), and the audited
promotion path from candidate to active that ADR-082926-65bf already gates.

What graduation would need, in order:

1. **A real corpus.** Re-run induction over actual completed Runs in a
   Workspace with per-goal provenance (`goal_family`/`goal_instance` are
   provenance keys this prototype had to invent; production would need an
   agreed Goal-structure taxonomy to cluster by).
2. **The guard as a product seam.** The trailing-success quarantine is 15
   lines here; making it production-shaped means deciding where per-motif
   outcome windows live (template metadata vs a separate quality record) and
   who observes them. The quarantine's second-staleness failure (seed 3)
   argues for combining fast quarantine with the slow re-mining flywheel and
   measuring joint convergence before trusting either alone.
3. **Retrieval beyond kind-Jaccard.** Kind-overlap retrieval is enough for
   4-node motifs; real Graphs will need signature-level or embedding
   retrieval, and the transfer probe suggests signature-level retrieval
   would transfer better than family-scoped retrieval.

Would flip to WATCH/REJECT if: a real-Runs replication shows the naive-vs-
scratch gap driven by instance-overfitting the distinct-instance bar fails
to catch, or guard+re-mining cannot be made to converge on drifted families.
