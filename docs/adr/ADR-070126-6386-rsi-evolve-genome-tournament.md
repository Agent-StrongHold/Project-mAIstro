---
id: ADR-070126-6386
title: "RSI code improvement as an evolve genome tournament"
repo: maistro-engine
kind: adr
status: Proposed
created: 2026-07-01
substrate: []
implements: []
related:
  - maistro-engine#ADR-088
  - maistro-engine#ADR-062
  - maistro-engine#ADR-093
  - maistro-engine#ADR-038
  - maistro-engine#ADR-099
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Evolve
owners:
  - '@BlakeMatthews-dev'
---

# ADR-070126-6386: RSI code improvement as an evolve genome tournament

**Status:** Proposed

## Context

The local recursive-self-improvement loop (`maistro_rsi.local_loop.LocalRsiLoop`)
today runs a **single** coding attempt per cycle: clone → one agent turn-loop
edits a target file → the multi-signal `Scorecard`
(`maistro_evolve.scorecard`) gates promotion → the change ratchets onto an
in-container `rsi-baseline` branch. A validated 15-cycle run (fully isolated per
ADR-093 — agent, git, tests, coverage, and the whole fitness evaluation execute
inside one ephemeral container; the host is never touched) promoted 11/15, with
all 4 rejections correctly vetoed by the `ruff_clean` gate. See
`tools/run_rsi_isolated.sh` and `Dockerfile.rsi-runner`.

That loop proves the *ratchet* and the *fitness gate*. It does not yet exploit
the two levers that make self-improvement compound:

1. **Competition.** One attempt is not the best attempt. The same improvement
   can be made several ways; a stronger or cleaner version should win.
2. **Improving the improver.** The thing that varies between attempts — the
   prompt, model, temperature, and strategy driving the coding agent — is
   exactly a **maistro-evolve genome** (`NodeGenome{role, strategy, model,
   temperature, max_tokens, system_prompt, max_tool_rounds}` inside a
   `DAGTopology` with a `use_scout` flag; `PipelineGenome` carries
   `fitness_score`, `eval_scores`, `generation`, `parent_*`). Evolve
   (ADR-088) already runs Elo tournaments over genomes, culls, breeds
   (`crossover`/`mutate_all`), and enforces diversity — but against generic
   benchmarks (ifeval, bfcl, swebench…), never against "did this genome produce
   the best fix for *our* code?"

The user's framing: *one model reads a file and identifies something
suboptimal; then multiple models and configs of the same model compete to fix
it best; the winner is kept, or complementary non-overlapping fixes are both
kept; and this repeats so the fixers themselves improve.* That is an evolve
genome tournament whose benchmark is our own codebase.

## Decision

Introduce a **code-improvement tournament** as the unit of an RSI cycle, and
express it entirely in evolve terms so the genome population — not a bespoke
roster — is what competes and evolves.

### Conceptual mapping

| RSI concept | maistro-evolve primitive |
|---|---|
| Scout reads the file, names the concrete fix | `DAGTopology.use_scout` node (`role="scout"`) |
| Competing models / configs of the fixer | the genome **population** (`NodeGenome.model` / `.temperature` / `.system_prompt` / `.strategy`) |
| Score of one fix attempt | RSI `Scorecard.composite` surfaced as an `EvalResult.score` for a new **`code_rsi`** benchmark |
| Head-to-head ranking | `EloTournament` battles over `code_rsi` scores |
| Keep winners, breed better fixers | `EvolutionCycle`: cull → `crossover`/`mutate_all` → diversity, across sessions |
| Winning code changes | promoted onto `rsi-baseline`, then harvested as PRs |
| Fixer lineage over time | `PipelineGenome.generation` / `parent_*`, persisted in `PopulationStore` |

### The `code_rsi` benchmark

Add a benchmark to `maistro_evolve.harness.EvalHarness` whose `evaluate_genome`
path, for a given `(target_file, scout_objective)`:

1. Drives the coding agent **configured by the genome** (its fixer node's
   `model`, `temperature`, `system_prompt`, `max_tool_rounds`) to implement the
   scout's objective on a fresh worktree off the current baseline.
2. Runs the existing `candidate_fitness.evaluate_candidate` → `Scorecard`.
3. Returns `EvalResult(benchmark="code_rsi", score=scorecard.composite,
   metadata={gates, per-signal scores, patch-ref})`. A gate veto ⇒ score 0
   (evolve's hard-gate semantics already exist via `FitnessComponents`).

The genome's `code_rsi` score is thus "how good a code fix this prompt/model/
config produces", so `EvolutionCycle` evolves the population toward better
*fixers*. `EvalWeights` is extended (or a code-only weight profile is used) so
`code_rsi` dominates when the RSI loop runs.

### Cycle algorithm (per target file)

1. **Scout.** A scout genome (or the `use_scout` node of the champion) reads the
   file/module and emits one concrete, bounded improvement objective. All
   competitors receive the *same* objective — a fair head-to-head.
2. **Compete.** Evaluate a batch of genomes on `code_rsi` for this objective
   (bounded by `EvolutionConfig.eval_batch_size`, `MAX_*` ceilings in
   `cycle.py`). Each yields a patch + composite.
3. **Select + merge** (the competitive/complementary rule). Rank passing
   candidates by composite, descending. Starting from the baseline, apply each
   candidate's diff in order:
   - applies cleanly ⇒ **keep** (it touches a different region — complementary);
   - conflicts with an already-kept diff ⇒ **drop** (same region — the
     higher-scored candidate already won).
   Re-score the merged result when ≥2 diffs combined; if the combination
   regresses a gate, fall back to the single top candidate (known-good).
4. **Promote** the merged result onto `rsi-baseline`; record each contributing
   genome's win/loss for the Elo tournament.
5. **Evolve** (every N cycles, not every cycle): run `EvolutionCycle.run_cycle`
   to cull weak fixer genomes and breed new ones from the winners.

### Persistence and PRs

A session's promotions are harvested into **a few PRs grouped by the file (or
package) edited** — each promotion commit already touches one file, so grouping
is a partition of the commit set. Harvesting exports validated patches out of
the sandbox and opens PRs against the base the run improved; applying vetted,
gate-passing diffs to a review branch is a controlled step and does **not**
re-run agent code on the host. The genome `PopulationStore` and Elo state
persist across sessions so the fixers keep improving.

### Safety

- **Isolation (ADR-093).** The whole tournament — scouts, every competitor,
  tests, coverage — runs inside the ephemeral container. Nothing but reviewed
  patches leaves it.
- **Promotion gate.** `PipelineGenome.approved_for_promotion` stays closed;
  winning a tournament never flips a genome to live traffic without an explicit
  human gate (existing evolve RSI-safety invariant).
- **Resource ceilings (ADR-038, `cycle.py` `MAX_*`).** Batch size, population,
  tournament size, and self-improve fan-out remain hard-capped so an autonomous
  ("use all tokens continually") run cannot consume unbounded compute.
- **Honesty.** `reflective_improve` already refuses stub eval signal; `code_rsi`
  must likewise never score against a stubbed/absent test suite.

## Consequences

**Positive.** Self-improvement compounds on two axes: better code *and* better
fixers. Reuses evolve's tournament/cull/breed/diversity wholesale instead of a
parallel bespoke selector. Complementary-merge captures more value per cycle.
The genome lineage makes "which prompt/model/config improves our code best" an
observable, evolving artifact.

**Negative / risks.** Cost multiplies by the competitor count per cycle (bounded
by the `MAX_*` ceilings and rate-limited by the LiteLLM `code` group). Merge
re-scoring adds evaluations. Cross-package coupling (`maistro-rsi` depends on
`maistro-evolve` harness/population). Scout quality caps the whole cycle — a
vague objective yields weak competition. `code_rsi` is a non-deterministic,
cost-bearing benchmark, unlike the existing static ones.

## Staged rollout

1. **Tournament engine** in the RSI cycle: N candidates + competitive/
   complementary merge, candidates described *as genome nodes*. (Selection/merge
   is independent of how candidates are generated.)
2. **Scout** step feeding a shared objective to competitors.
3. **`code_rsi` benchmark** in `EvalHarness`; drive competitors from a
   `PopulationStore` via `EvolutionCycle` (Elo + cull + breed + mutate).
4. **Harvest** session → grouped PRs; persist population + lineage; enable
   longer/autonomous capped runs.

## Alternatives considered

- **Bespoke roster in the RSI loop** (a hard-coded list of `model@temp`). Faster
  to build, but duplicates evolve's tournament/evolution and can't *learn* which
  fixers are best — rejected in favour of driving the genome population.
- **Best-of-N without merge.** Simpler, but discards complementary non-
  overlapping improvements the user explicitly wants kept.
- **Single strong model, no competition.** The current loop; leaves the "improve
  the improver" lever unused.

## Open questions

- Scout as a fixed champion node vs. its own evolving genome role.
- Weighting `code_rsi` against the existing benchmarks in `EvalWeights` (code-only
  profile vs. blended).
- Whether merged multi-genome commits credit Elo to each contributor or only the
  top scorer.

## Amendment (2026-07-04): typed fixer genomes, unified live evolution, and the maturity ladder

The tournament above shipped (PR #217) and was then extended twice more; this
amendment brings the ADR current with both extensions in one pass.

### The fixer genome became a typed "mad-lib" (`maistro_evolve.fixer_genome.FixerGenome`)

Each `NodeGenome.fixer` carries 16 evolvable slots — enums (`strategy`,
`test_style`, `review_pass`, `risk`, `reasoning_effort`), continuous dials in
`[0,1]` (`temperature`, `minimalism`, `ambition`, `edge_focus`, `tdd_rigor`),
and lineage-evidence text (`persona`, `strategy_hint`, `goals`,
`codebase_standards`, `learned_successes`, `learned_failures`) — rendered as
literal JSON into the coding agent's system prompt. An LLM **hyper-mutator**
(`maistro_evolve.hyper_mutator`) proposes typed slot changes for the fittest
genome each cycle, grounded in its lineage and an operator goal (GEPA
propose→verify shape); accepted children join the population **UNVERIFIED**.
A 10-cycle gym run showed the mutator reverse-engineer the fitness function
from experience ("test-first fixes with multiple assertions raise
acceptance") and converge the population on `strict_tdd` / `tdd_rigor→1.0` in
four generations — the fixer genome does learn, not just the code.

### The tournament and the evolution loop are ONE loop — working IS learning

The original design ran two separate things: a standalone `evolve` gym that
authored and scored real fixes and then discarded them, and a tournament that
did real work but learned nothing from it. That was a mistake — they were
never meant to be separate. `run --genome-db <path>` now makes the genome
**population** the tournament roster directly:

- Each cycle's real `Scorecard.composite` folds back into the genome that
  authored it via an **EMA** (`eval_ema_alpha=0.5`) — not overwritten, so a
  lucky 0.76 doesn't get erased by the next 0.0 and a genome's fitness reflects
  its trend, not its last roll. Stubbed (errored) attempts never fold; a
  rejected-but-real fix's `0.0` is genuine evidence and does fold.
- Same-slot competitors (same scout item ⇒ fair comparison) fight an Elo
  battle (`EloTournament`) whose result also lands in `harness_params`.
- Between cycles: fitness → cull the weakest → breed one crossover child →
  the hyper-mutator proposes one guided child of the champion. Children are
  **verified by the next cycle's actual work**, not a separate eval.
- `population.db` persists outside the run (host-mounted in isolated mode),
  so lineage **compounds across runs** — `seed_population` is top-up-only and
  never buries an existing lineage under fresh randoms.
- The `evolve` gym command is thereby demoted to an **offline harness** for
  ad-hoc experiments; it is not part of the production RSI path.

### Capacity is not fitness — the model bench and the reliability multiplier

Multi-provider free-tier rosters hit transient 429/quota/billing errors
constantly (see `MODEL-LIMITS.md`). Those are evidence about the *provider*,
not the genome, so they are handled separately from scoring:

- A transient error **benches the model** — it sits out, no sample folds into
  any genome (sitting out is neutral, not a rejection). The sit-out honors the
  provider's *own* stated wait (Groq's "try again in Xs", Gemini's
  `retryDelay`, `retry-after` headers) when the error names one; otherwise it
  defaults to `bench_cycles` worth of estimated cycle time, **doubling per
  consecutive bench** of the same model (capped) so a drained daily quota
  backs off geometrically instead of re-probing every cycle. The streak
  resets the moment the model scores real work again.
- A run-local per-model **reliability EMA** (starts at 1.0, decays on
  transient failure, recovers on success; deliberately *not* persisted —
  provider health is temporal) **multiplies into genome fitness** during
  cull/breed selection, so the same slot settings on a flaky provider rank
  below the identical settings on a dependable one — evolution re-tries
  winning strategies on other carriers rather than dying with the provider.
- Net effect: the roster can safely include *every* servable model
  (`--genome-models`, seeded round-robin so each gets a lineage from cycle
  one) — evolution learns from every model's real behavior, including
  surprises, instead of being pre-filtered to a "safe" shortlist.

### The maturity ladder — ambition without demolishing TDD

Emphasizing new features risked eroding the test-first discipline the
hyper-mutator had already learned. The fix is a **ladder of scout item kinds**
(`ImprovementKind`), each routed to its own budget and fitness signal, so
ambition is *earned* rather than substituted for rigor:

`bug_fix` → `new_test` → `assertion` → **`spec`** (finish a specific
UNIMPLEMENTED acceptance criterion — the single highest-reward move, reward
`spec_completion=0.45`, the largest weight in the system) → **`backlog`**
(draft a *new* spec contract for a genuinely good idea — the disciplined
alternative to shipping an unspecced feature raw, reward `spec_proposed=0.40`,
deliberately just below `spec_completion`: proposing new work never outranks
finishing promised work) → `feature` (v2.0, `BudgetTier.UNLOCKED`) → `edge_case`
→ `refactor` → `perf` → `doc` (fallback only).

`spec`/`backlog` completion is measured objectively, not judged:
`maistro_rsi.spec_tracker` diffs the AC checkboxes enumerated in
`docs/specs/*.md` against `@pytest.mark.ac("SPEC-x/AC-n")` markers across the
test suites. `spec_completion` fires only for **net-new** AC markers with
green tests (re-tagging an already-claimed AC earns nothing); `spec_proposed`
fires only for a well-formed new contract (parseable `id:` frontmatter plus
at least two enumerated ACs). Both are presence-gated exactly like
`new_test`, so neither can dilute a candidate doing other work. The scout
sees real uncovered lines (`coverage_gate.measure_coverage_detailed`) and real
spec gaps, and is instructed to propose `feature`/`backlog` only once a
module is verified and gap-free — ambition is earned, never assumed. An
un-built LLM `feature_judge` remains future work (tracked in the SPEC below,
not yet implemented) — FEATURE items score today on the signals that are
actually wired (red_green, code_quality, any coverage delta), not on a judge
that doesn't exist yet.

### Observability

Checkpoint reports (`build_checkpoint_report`) gained an `## Evolution`
section in live mode: population size and generation histogram, the fittest
genomes' settings (model, `tdd_rigor`, `test_style`, fitness), the per-model
reliability table, which models are currently benched, and the newest
lineage memory the hyper-mutator wrote — so a long run's *learning*, not just
its promotions, is legible without reading logs.

### Consequences (amendment)

**Positive.** One loop, not two — no more discarded gym evaluations. Capacity
problems (free-tier rate limits) no longer kill genomes or a run. Feature work
is now possible without weakening the TDD signals that made the tournament
converge in the first place, and finishing contracted spec work is rewarded
above inventing anything new. Population state is observable mid-run.

**Negative / risks.** `spec_tracker` depends on the AC-marker discipline being
followed consistently (a spec with no markers/frontmatter contributes no
signal in either direction — silently, not as an error). The reliability
multiplier is run-local, so a long-lived population.db doesn't remember which
models were unreliable in a *previous* run — acceptable, since provider
health genuinely changes over time. `feature_judge` is designed but not
built; FEATURE-kind promotions are judged by proxy signals only until it
lands.

## Acceptance Criteria

Criteria declared 2026-09-03 for the harvest-path tests that already cite this
ADR (`packages/maistro-rsi/tests/test_harvest.py`) — the behaviors those tests
prove, stated as the ADR's Stage-4 contract:

```gherkin
Feature: RSI evolve genome tournament — harvest persistence

  @persist
  Scenario: Harvest groups patches by file into durable, safe refs
    Given a session's promotion patches
    When they are harvested into grouped PR branches
    Then each file's patches form one group
    And the branch slug is a safe git ref

  @stage3
  Scenario: Stage-3 promotions persist to the population store
    Given promotions accepted during a session
    When the harvest completes
    Then population and fixer lineage are persisted for future sessions
```
