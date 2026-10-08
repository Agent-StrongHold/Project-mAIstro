# M8-D3 research note — observation-driven replanning after failures, surprises, and changed constraints

Leaf: [#927](https://github.com/Agent-StrongHold/Project-mAIstro/issues/927).
Epic: [#903](https://github.com/Agent-StrongHold/Project-mAIstro/issues/903) (M8-D,
planning / Goal decomposition / Graph synthesis). Initiative:
[#879](https://github.com/Agent-StrongHold/Project-mAIstro/issues/879).

## Hypothesis

Explicit replanning from current Run evidence after a tool failure, changed state, or new
constraint improves Goal completion versus blindly continuing an original plan.

## Canonical seams

Canonical execution is the durable spine `Goal -> Graph -> Run -> NodeRun -> Attempt`
(`packages/maistro-core/src/maistro/graph/durable_runs/`). What the shipped system does
today when the world surprises a Run:

- **Attempt-level repair only.** `execute_with_resilience`
  (`packages/maistro-core/src/maistro/graph/executor.py`) retries a node in place under
  `RetryBudget` (`maistro/resilience/p1`), with the `ResiliencePolicyStore` consulted on
  every retry decision. This is the harness's **no-replan** baseline: the plan is never
  revised and the world is never re-observed.
- **Human steering, not observation-driven replanning.** `SteeringQueue`
  (`packages/maistro-core/src/maistro/graph/steering.py`) drains operator guidance
  strings; nothing re-synthesizes a Graph from Run evidence. The absence this leaf
  evaluates is real: there is no shipped observation-driven replanner to compare against,
  so the benchmark models the policy shapes instead of measuring a production one.
- **Provenance as non-falsification.** `graph/definitions.py` (`TemplateProvenance`,
  `PROVENANCE_METADATA_KEY`) pins the canonical rule this harness borrows: derivation
  recorded at production time must not be retroactively falsified by later state.
- **Budgets fail loudly with the budget named.** `graph/policies.py`
  (`resolve_max_cycles` semantics) is the pattern the harness copies for its replan and
  oscillation ceilings: exhausting `max_replans` or the oscillation guard is a recorded
  terminal outcome (`replan-budget-exhausted`, `replan-oscillation-exhausted`), never a
  silent truncation.

No research planner may become a parallel execution authority (epic contract). The
harness below imports no maistro module and writes nothing: it is a measurement device
for policy *shapes*, not an executor.

## Record

This note does not report an experiment on MAIstro workloads. The deterministic CI
environment holds no live providers, tools, or capability authorities, and no corpus of
representative Goal executions with injected surprises exists in-tree; manufacturing one
was out of scope, and absent evidence is recorded rather than simulated (M8 guardrail 3).
This change adds no product code, no flag, and touches no authority path.

What it adds is the reproducible measurement machinery the issue's benchmark procedure
demands, as a separated research artifact:
`packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py` (test suite only;
it imports no maistro module, so it cannot become an authority by accident — M8
guardrails 1-2). Validated on deterministic hand-checked fixtures (46 checks), it
implements:

- the issue's six surprise injections as a scheduled world clock — unavailable provider,
  changed artifact, failed tool, denied capability, stale assumption, newly satisfied
  subgoal — each firing after N completed attempts, with observations free and
  instantaneous;
- the three policies on one shared sequential NodeRun spine: **no-replan** (blind
  attempt-in-place retry; never re-observes), **local repair** (re-observes; requeues on
  favorable change, re-derives exactly the invalidated producer chain, skips subgoals the
  world already satisfied), **full replan** (re-derives the remaining plan from current
  evidence through a deterministic planner that substitutes declared alternates);
- the issue's full measure list: goal recovery rate (split into *completed* versus
  *recovered*, where a completion whose recorded derivation was falsified is dirty and
  never counts as recovery), duplicated work (task executions spent on subgoals the world
  had already satisfied), invalidated-work reuse (skips and planner drops of externally
  satisfied subgoals), cost (every attempt and every replan pays in full, failed or not),
  latency (sequential attempt durations plus planner latency), oscillation (same-structure
  replans, with a consecutive-run loop guard that stops loudly with the budget named), and
  provenance correctness (a completion walk over the derivation chain that names each
  consumed-version, emitted-version, and assumption edge the world has since falsified);
- trust-boundary accounting: capability denial is an authority decision —
  observation-aware policies never attempt without the grant and never re-attempt into a
  denial, while blind re-attempts against a denial are counted
  (`denied_reattempts`) as a hazard measure, not normalized.

What the fixtures demonstrate (synthetic five-task catalog, one Goal artifact; **not**
evidence about real MAIstro workloads — the arithmetic is hand-checked and pinned by
tests):

- On the six-surprise suite, the blind baseline recovers 1/6 and *completes* 3/6 — the
  other two completions ship falsified derivations (a stale artifact chain; an output
  computed under an assumption that no longer holds). Observation-driven policies never
  ship a dirty completion on this suite: local repair fails loudly instead (1/6 dirty,
  0 for both aware policies).
- **Local repair dominates the blind baseline** on the suite: 3/6 clean recoveries at 34
  cost units versus the blind policy's 1/6 at 44 — the blind policy burns sunk retry
  spend on a permanently failed tool and re-executes externally satisfied work.
- **Full replan buys the two structural recoveries** — tool substitution through a
  declared alternate (failed tool) and a differently-constrained alternate path
  (invalidated assumption) — reaching 5/6 clean at 48 cost units, ~41% more than local
  repair. On data-freshness surprises (changed artifact, provider blip) full replan
  degenerates to local repair plus a planner fee: re-deriving an identical structure is
  corrective (counted as one oscillation replan), not progress. Structural substitution
  is the only thing replanning buys on this fixture set.
- A hot world (an artifact revised after every action) thrashes an unbounded replanner:
  five same-structure replans for one Goal, 21 cost units versus 6 for the bounded
  policy that the oscillation guard stops loudly mid-thrash. In a continuously-changing
  world *no* pin-based policy ships valid outputs — the blind policy completes while
  shipping two falsified edges, local repair exhausts its requeue budget, and only the
  unbounded replanner eventually converges (at 3.5x the quiet-world cost). The fix —
  change-detection or quiescence gating — is outside this benchmark and recorded as the
  next required evidence below.
- The trust boundary holds under replanning pressure: the only policy that re-attempts a
  denied capability is the blind one, and the attempt is counted; the full replanner ends
  the denial scenario in a loud `no-viable-plan` rather than working around the authority.

Executed probe record (head af7996883, 2026-10-08):
`uv run pytest packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py -q`
→ 46 passed; `uv run ruff check` and `uv run ruff format --check` clean on the module;
mutation-checked (blind-assumption judgment, denial requeue, free replans, dirty
recoveries each caught by the test that names them); full `packages/maistro-rsi/tests`
suite 1241 passed.

## Benchmark procedure (what a real experiment must do)

1. Select representative Goal executions on the durable spine — real Graphs with
   producer/consumer artifact chains, capability-gated nodes, and declared alternates
   where the canonical owner allows them.
2. Inject the six surprise classes at controlled NodeRun boundaries (provider outage,
   external artifact revision, tool failure, capability revocation, assumption
   invalidation, externally satisfied subgoal), recording every injection with its
   Attempt position.
3. Run each execution three times — no-replan (the shipped retry-only shape), local
   repair, full replan — with identical budgets, judging recovery by the canonical
   completion evidence plus a provenance walk over the recorded derivation, never by
   "the Run stopped failing".
4. Report per surprise class: recovery rate, clean-recovery rate, duplicated work,
   invalidated-work reuse, cost (attempts + replans, sunk spend included), latency,
   replan count with oscillation-loop detection, and denied re-attempts.
5. Report the dominance frontier (clean recovery vs total cost) and the degenerate
   bounds (never-replan, replan-on-every-observation) as with the #915 frontier.
6. Update the disposition here. Cost accounting must include failed attempts and failed
   replans; a completion with a falsified derivation counts as a failure, not a recovery.

## Trust boundary

Replanning research and execution authority stay separate — this leaf's own epic contract
sentence. Every number the harness produces is advisory evidence: it reads no Goal,
writes no Run, makes no routing or capability decision, and touches no Warden/HITL
control. The module imports no maistro module (asserted by test), so it cannot become a
second execution authority by accident. A policy shape that survives a real experiment
reaches production only as a change to the canonical Goal/Graph owner's seam per the epic
exit — where the durable `Goal -> Graph -> Run -> NodeRun -> Attempt` model, the single
recovery path, and the ResiliencePolicyStore's authority over retries remain untouched by
this note.

## Disposition

- #927 (observation-driven replanning after failures, surprises, changed constraints):
  **WATCH** — the measurement machinery is reproducible and its arithmetic and policy
  mechanics are validated, but no real run on representative MAIstro workloads exists,
  so the hypothesis is unevidenced where it matters. Move to **INCUBATE** when a real
  run on representative Graph executions shows a material clean-recovery improvement at
  bounded cost/latency overhead, zero provenance violations under the replanning policy,
  bounded replan loops, and zero denied re-attempts — and the Goal/Graph owner has the
  result. **REJECT** if real runs show replan loops or planner cost dominating the
  recovery gain, or any falsified-derivation completion under an observation-driven
  policy. Hot-world (continuously-changing) workloads must be reported either way: the
  fixture shows pin-based policies cannot converge there, which is evidence about the
  policy family, not a benchmark artifact.

No adoption is authorized by this note.
