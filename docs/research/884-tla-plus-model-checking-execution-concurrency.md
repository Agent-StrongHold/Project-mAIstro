# M8-A4 research record — bounded model checking for the execution concurrency protocols

Issue: [#884](https://github.com/Agent-StrongHold/Project-mAIstro/issues/884) (RESEARCH M8-A4, milestone M8, parent epic #880).
Deliverable artifacts, all reproducible from this tree:

- Executed checker: [`scripts/model_check_consumer_claim.py`](../../scripts/model_check_consumer_claim.py) — a deterministic, dependency-free exhaustive bounded explorer of the consumer-claim spine, with the guarded/unguarded variant switch and the mutation surface the evidence below rests on.
- Portable model: [`docs/research/models/884-execution-lease/ConsumerClaimLease.tla`](models/884-execution-lease/ConsumerClaimLease.tla) (+ `.cfg`) — the same transition relation in plain TLA+/TLC form.
- Executed tests: [`tests/test_model_check_consumer_claim.py`](../../tests/test_model_check_consumer_claim.py) — 27 tests pinning every claim in this record (including that each invariant can fail).

## Disposition: INCUBATE

Not GRADUATE: a protocol-level model is **not** implementation equivalence, and the issue is explicit that graduation requires a demonstrated conformance strategy. This record demonstrates two conformance seams (transition legality imported from the shipped tables; lease-expiry time derivation cross-checked against the shipped predicate) and deliberately does **not** claim guard-level conformance — the model restates the guards in its own vocabulary, and nothing today proves a store transaction implements the atomicity the model assumes. That missing half is the graduation gate (see Conformance strategy).

Not REJECT: the experiment paid for itself immediately — the checker rediscovered both historically real bug shapes (#1335's completion window and ADR-082426-e3ff's stale acceptance) from the interleaving space alone, in BFS-minimal form, and proved the shipped guards close every interleaving up to the bound. No randomized or hand-written test in the tree makes the second claim.

Not WATCH: WATCH would be right if the protocol were still moving or the tooling were expensive. The spine's windows are now fenced and tested at the store level; the checker costs ~0.2–0.5 s per exploration and zero dependencies. INCUBATE: keep the model + checker as the standing experiment harness for the next concurrency-relevant change to the spine (lease semantics, recovery cadence, a second claimant class), not as a shipped CI gate.

## Hypothesis, and where it landed

The issue hypothesizes that a bounded state-machine model checker can expose unsafe interleavings in claim → admit → execute → cancel → crash → recover → retry protocols that randomized async tests may never schedule. Result: **confirmed, with one sharpening.** The interleaving space of a *single node's* attempt lifecycle under two consumers and a bounded clock is 9,520 states / 25,756 edges — exhaustively checkable in 0.17 s — and it contains both known bug shapes at depths of 5 and 6 actions. The sharpening: the value was not in finding *unknown* bugs (the two violations the unguarded variant produces correspond to races the repo already fixed and documents), but in turning "these guards closed the races we thought of" into "these guards close every interleaving up to the bound," and in making the *semantics boundary* explicit (effect-once holds exactly under `once` replay semantics; under `retryable`, re-execution of a crashed in-flight effect is the contract, not a violation — § Evidence).

## Modeled protocol and scope

One narrowly scoped protocol, per the issue: the **consumer-claim / execution-lease lifecycle for one node's work**, implemented by `maistro.runs.consumer_claim` (the atomic claim), `maistro.runs.execution` (heartbeat, landing writes, the terminal-Run fence), `maistro.runs.lifecycle` (transition tables, lease predicates), and the durable recovery walk (`maistro.graph.durable_runs.attempt_executor._reconcile_orphaned_attempts`, `resume_due_graph_runs`). This is the spine the canonical execution model (`Goal -> Graph -> Run -> NodeRun -> Attempt`) actually executes attempts through.

Modeled actions (each mapped to its source):

| Model action | Shipped counterpart | Guard source |
|---|---|---|
| `claim(c)` | `claim_consumer_run` — Run QUEUED→RUNNING + Attempt RUNNING + lease, one atomic write | consumer_claim.py module contract |
| `renew(c)` | `renew_attempt_lease` / heartbeat task (TTL/3 cadence) | no renewal of an expired lease; token unchanged |
| `tick` | clock advance | bounded at `horizon` |
| `crash(c)` | process death; renewals stop, durable state stands | ADR-082526-b36a |
| `dispatch(c)` | the physical effect (tool/provider call) starts | live lease + fence (ADR-081626-f383); ReplayRefused for `once` nodes (#1194) |
| `begin_commit(c)` | `_settle_provider_success` step 1: **read the Run** | the #1335 window, modeled explicitly |
| `land_commit(c)` | step 2: **write the Attempt** | `refuse_completion_under_terminal_run` (#1335): converts to CANCELLED under a terminal Run; transition table refuses a write over a reclaimed Attempt |
| `accept(c)` | `accept_outcome` projection terminalizing the Run | ADR-082426-e3ff: acceptance carries the live token, latest attempt only |
| `cancel` | run-level cancellation; settles open Attempts (requested) | RUN_TRANSITIONS / attempt cascade |
| `recover` | `reclaim_expired_attempts` (CANCELLED, `CancellationCause.RECOVERED`) | `lease_is_expired` |
| `retry(c)` | `resume_due_graph_runs` fresh Attempt under the RUNNING Run | LiveAttemptOwned (subsumed: open Attempt blocks; terminal never live), RECOVERED cause authorizes |
| `spawn(c)` (progress graph only) | orchestrator worker replacement | fairness assumption, not protocol |

Scope cuts, stated: single node, single Run; no WAITING/PAUSED/YIELD, no FAILED/TIMED_OUT dispositions (they add states, not window interleavings); no LaneGate/TaskQueue capacity model — the issue's "capacity never exceeds configured bounds" candidate invariant belongs to `maistro.tasks.lanes.LaneGate`, a different protocol (reserved floors + tier-ordered handoff), and is explicitly **not modeled here** (a WATCH item if a second protocol is ever modeled); admission ceilings (#1182) not modeled; the effect is an abstract flag (real idempotency boundaries live outside the spine).

Deliberate abstractions, with soundness direction: renewals cap expiry at `horizon` (max-expiry abstraction — leases can only lapse *earlier* than real, so explored behaviors are a superset); `spawn` exists only on the fairness graph and adds no safety-relevant behavior (a revived worker can only take lease/fence-guarded actions already covered by never-crashed workers).

## Invariants checked

Safety (state predicates, checked on every discovered state):

- **S1_single_owner** — at most one active Attempt owns the node.
- **S2_effect_once** — under `once` replay semantics, the physical effect dispatches at most once.
- **S3_acceptance_is_current** — the acceptance that terminalizes the Run comes from the latest Attempt (ADR-082426-e3ff's stale acceptance).

Transitions (edge properties, checked on every edge — they are about *writes landing*, not states coexisting; run CANCELLED with an attempt COMPLETED is a legal shipped state: the work finished, then the run was cancelled):

- **S4_no_completion_under_terminal_run** — a COMPLETED Attempt write never lands once the Run is terminal (#1335's refusal).
- **S5_terminal_no_regress** — terminal statuses are absorbing, for the Run and every Attempt.

Liveness (exact backward reachability, no sampling):

- **Progress without a person** — every safety-reachable state with tick budget left reaches a terminal Run or *live ownership* (open Attempt, unexpired lease, alive holder) using only non-`cancel` edges plus `spawn`, `tick`, `recover`. Fairness assumptions, stated: the clock advances; the sweep eventually runs; crashed workers are eventually replaced. States at `clock == horizon` are outside the claim — the model's time budget is exhausted and even a fresh lease cannot outlive it; a finite-clock TLC run has the same boundary.
- **No deadlock short of the declared ceilings** — every non-terminal state retains a non-person action unless it sits at the tick horizon or the attempt bound.

Model-vs-implementation conformance seams (the only two that exist today):

- every Run/Attempt move the model makes is legal per `maistro.runs.lifecycle` — the shipped tables are **imported**, not restated (`conformance_with_shipped_tables`, pinned by a test);
- the model's lease-expiry predicate derives time identically to `maistro.runs.lifecycle.lease_is_expired` — cross-checked over unexpired / lapsed / terminal / lease-less Attempts against the real pydantic models (pinned by a test).

## Evidence

All numbers from `scripts/model_check_consumer_claim.py` at this head; explorations are deterministic (same states, same first counterexample, pinned by test).

**The guarded protocol is clean.** `Spec()` (all shipped fences) exhaustively explored: **9,520 states, 25,756 edges, 0 violations** across S1–S5, no deadlock beyond ceilings, progress under the stated fairness. Every interleaving of claim/dispatch/commit/accept/cancel/crash/recover/retry up to the bound, checked, in 0.17 s.

**The unguarded protocol violates exactly the two invariants whose guards were removed** (`FencedAcceptance=FALSE`, `TerminalRunRefusal=FALSE` — the pre-fix world): 14,320 states; `S3_acceptance_is_current` and `S4_no_completion_under_terminal_run` fire, and nothing else (S1/S2/S5 hold by construction in both variants — verified).

The counterexamples are the shipped races, BFS-minimal:

- **S3** (ADR-082426-e3ff's reproduced interleaving): `claim(c0) → dispatch(c0) → begin_commit(c0) → land_commit(c0) → retry(c0) → accept(c0)` — worker completes, its completed-but-unaccepted node is parked for retry (the pre-fix era behavior), a successor attempt goes live, and the stale acceptance lands. The ADR's own reproduction ("worker A completes an Attempt but has not yet committed its outcome; recovery parks the node as orphaned; worker B claims Attempt 2 and is live; worker A then commits") is this trace.
- **S4** (#1335's window): `claim(c0) → dispatch(c0) → begin_commit(c0) → cancel → land_commit(c0)` — the Run lands CANCELLED *inside* the read/commit window and the stale success lands COMPLETED underneath it. Because the model keeps the window open as explicit state, the guard's correctness claim is "no interleaving of the window escapes," not "the interleaving we wrote down is handled."

**Effect-once holds exactly under `once` semantics.** Under `retryable` (14,032 states), S2 fires — and the violating trace re-dispatches only through `recover` (a crashed in-flight effect re-runs; that is the at-least-once contract ReplaySemantics defines, not a bug). A completed Attempt's node is never re-driven in the guarded world: guarded `retry` demands the RECOVERED cause (pinned by a direct action test).

**Invariant can-fail discipline** (formal/INVARIANTS.md #410): beyond the unguarded variant itself, each remaining invariant was demonstrated to fire against a realistic mutant, each a documented bug class: resume over a live owner (the `LiveAttemptOwned` hazard) → S1; a dropped ReplayRefused → S2; acceptance over a terminal Run → S5; a store dropping the Attempt transition-table guard on the landing write → S5; a clockless world → the stuck-state detector counts states a person would have to unstick. A checker that never fires is not evidence.

**State-space growth** (guarded, `once`, 2 consumers, measured):

| Configuration | States | Edges | Time |
|---|---:|---:|---:|
| ttl=2, horizon=6, max_attempts=2 (base) | 9,520 | 25,756 | 0.17 s |
| horizon=7 | 15,736 | 42,872 | 0.33 s |
| horizon=8 | 24,328 | 66,652 | 0.51 s |
| ttl=3, horizon=7 | 7,840 | 21,668 | 0.20 s |
| max_attempts=3 | 17,616 | 44,796 | 0.42 s |
| `retryable` | 14,032 | 38,028 | 0.31 s |
| unguarded (base) | 14,320 | 39,116 | 0.30 s |

Growth is roughly linear in the horizon (~8.5k states/tick at these bounds) and modest in the attempt bound; a longer TTL *shrinks* the space at fixed horizon (fewer recovery paths explored). One node + two consumers stays tractable by a wide margin; the growth risk is per-node and per-claimant multiplicity, which is why the scope cut to one node matters (§ Fidelity risks).

**Comparison against current async/property tests.** The tree already covers this protocol three ways, and the checker complements rather than replaces each:

- `formal/models/test_run_lease_fence.py` — a Hypothesis state machine driving the **real PgRunStore** with randomized interleavings and replayed stale tokens (its own README: "the interleavings nobody thought to write down"). It samples; it cannot prove absence. The checker proves absence up to the bound, but over an abstract relation — the two are the complement pair, and the fence invariant I29 checks at the store level is exactly S3's subject.
- `packages/maistro-core/tests/runs/test_spine_conformance.py` — ten workers raced by hand against the store: the named interleavings, forced. The checker generalizes "the ones we named" to "all of them, bounded."
- `packages/maistro-core/tests/runs/test_crash_window_invariants.py` — process kills forced at the named two-write seams with an explicit `KNOWN_GAPS` ledger. The checker's `begin_commit`/`land_commit` split is the same discipline applied to a fifth window (#1335's) and explores every fill of it rather than one.

Counterexample usefulness, measured: both discovered traces are 5–6 actions deep, land within the existing documentation (#1335's docstring narrates the S4 trace almost line by line), and would be actionable as store-level regression tests had they been unknown. Modeling effort: the transition relation is 804 lines of checker (including CLI, reports, and the progress graph) plus a 252-line TLA+ rendering and 582 lines of tests — roughly 1:1 with the 1,632 lines of production spine it models. A protocol change touching guards is a one-flag or one-action edit; a structural change (new actor class) reopens the action inventory.

## Tooling: TLA+/TLC/Apalache vs. the justified equivalent

The issue allows "TLA+ with Apalache, TLC, or a justified equivalent." This environment (and this repo's CI) has no JVM: TLC and Apalache were not executable here, and no check in this record depends on them. The justified equivalent is the Python explorer: same bounded exhaustive semantics (BFS over a hashed frontier, all interleavings to the bound), zero dependencies, deterministic, reviewable by the same engineers as the protocol, and fast enough for a per-PR budget (0.2–0.5 s per safety exploration; the fairness graph adds ~1 s). The portable TLA+ module (`ConsumerClaimLease.tla` + `.cfg`) renders the identical relation — constants, actions, guards, and the violations-flag trick that expresses S4/S5 as state invariants for TLC — so a JVM-having reviewer can cross-run it:

```
java -cp tla2tools.jar tlc2.TLC docs/research/models/884-execution-lease/ConsumerClaimLease.cfg
apalache-mc check --config docs/research/models/884-execution-lease/ConsumerClaimLease.cfg
```

Honest status: the TLA+ module is hand-checked against the Python relation but was **not executed** — treat it as the portability artifact, and treat the Python explorer as the source of truth for the numbers above until a TLC run confirms them. TLC brings two things the equivalent lacks and one cost: an independent implementation of the exploration (a second opinion on successor enumeration — the main defense against a checker bug), symmetry reduction (irrelevant at this size), and its own DSL maintenance burden. If a future protocol outgrows hand-rolled BFS (partial-order reduction needs, larger actor sets), that is the trigger to graduate to TLC/Apalache execution in CI.

## Fidelity risks (what a clean run does *not* prove)

1. **Atomic actions vs. transactions.** Every modeled action is atomic; the implementation makes them atomic with store transactions and locks. The model proves the *protocol given that atomicity*. The two windows the spine itself names (#1335, ADR-082426-e3ff) are modeled as explicit splits; any *other* multi-await window in the stores would need the same treatment before a clean run says anything about it.
2. **Guard restatement.** The guards are re-expressed in the model's vocabulary from the source docstrings; only transition legality and lease-expiry derivation are imported. A guard change in the stores does not move the model — the lifecycle-table seam will catch table changes, nothing catches guard drift automatically. (This is the graduation gate.)
3. **Single node, closed actors.** Multi-node Runs compose per-node lifecycles through the frontier/scheduler, whose wakeup and checkpoint semantics (the issue's fourth candidate target) are not modeled. A cross-node invariant would need the frontier as an actor.
4. **Clock abstraction.** Bounded ticks with capped expiries coarsen time conservatively for safety, but progress claims are stated only within the horizon.
5. **Capacity is absent.** LaneGate floors/tiers and the #1182 admission ceilings are different protocols; "capacity never exceeds configured bounds" is UNVERIFIED by this model.
6. **Effect atomicity.** The effect is a flag; the real protection against a half-applied physical effect lives in effect-level idempotency, outside the spine.

## CI feasibility and maintenance burden

Feasible and cheap: stdlib-only, offline, deterministic, ~2 s for the full both-variant run inside a 27-test file that also proves the machinery fires. It is *not* wired as a gate in this change — INCUBATE, not GRADUATE — so there is no new required check and no ledger touch. Maintenance: the model lives beside the research record, the tests pin the evidence, and the lifecycle-table import makes the most drift-prone part (transition legality) tracked. The residual maintenance cost is guard restatement (risk 2): a guard change to the spine should be reviewed against this model, and a second claimant class, a new terminal disposition, or a recovery-cadence change should reopen it.

## Conformance strategy (what graduation would require)

The issue: "A model is not evidence of implementation equivalence unless a separate conformance strategy is demonstrated." Status of the candidate strategies:

- **Transition legality** — demonstrated (tables imported; tested).
- **Time derivation** — demonstrated (predicate cross-check over the shipped pydantic models; tested).
- **Guard-level equivalence** — not demonstrated. The honest path: a store-level state machine (the `formal/models/test_run_lease_fence.py` pattern) driven over *the same bounded action vocabulary* as the checker, with the checker's traces replayed as store command sequences and outcomes compared — differential conformance at trace granularity. That is a real build (an executor harness for the model's actions against `InMemoryRunStore`/`SqliteRunStore`), and it is the next artifact if this is ever graduated.

## Reproduction

```
uv run python scripts/model_check_consumer_claim.py                      # both variants, human-readable
uv run python scripts/model_check_consumer_claim.py --json               # machine-readable
uv run python scripts/model_check_consumer_claim.py --variant unguarded  # the two counterexamples
uv run pytest tests/test_model_check_consumer_claim.py -q                # the pinned evidence
```
