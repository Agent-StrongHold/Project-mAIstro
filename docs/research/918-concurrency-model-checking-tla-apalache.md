# M8-A research note — concurrency/model checking with TLA+/Apalache or equivalent

Epic: #880. Leaf: #884. Initiative: #879.

## Research question

Can lightweight concurrency bugs in MAIstro's core be detected early using TLA+ or Apalache model checking, focusing on race conditions in state management, task admission, or extension lifecycle that existing testing misses?

## Canonical seams

Concurrency hazards likely exist in:
- Task admission and scheduling (`packages/maistro-core/src/maistro/scheduling/`)
- Extension lifecycle state machines (`packages/maistro-core/src/maistro/extensions/`)
- Durable run state transitions (`packages/maistro-core/src/maistro/graph/durable_runs/`)
- Invocation effect indexing (`packages/maistro-core/src/maistro/capabilities/`)
- Worker shutdown and cleanup paths (`packages/maistro-core/src/maistro/runtime/`)

The canonical seam for modeling is the public async interface of these modules, particularly where shared mutable state is accessed across task boundaries.

## Record

This note does not report an Apalache run. No TLA+/Apalache toolchain exists in this
repository's deterministic CI, none was run for this leaf, and no real-model corpus
exists here; manufacturing evidence was out of scope, so absent evidence is recorded
rather than simulated (M8 guardrail 3). This change adds no product code, no feature
flag, and touches no authority path.

What this change does add is the technique's mechanics, reproducible today, as a
clearly separated research artifact:
`packages/maistro-rsi/tests/test_m8a_tlaplus_model_checking_research.py` (test suite
only; it imports nothing from `maistro`, so it cannot become an authority by accident
— M8 guardrails 1 and 2). The leaf's title says "or equivalent": since Apalache could
not be run, the harness implements the equivalent in miniature — an explicit-state
model checker (the kind of checker TLC executes), validated on deterministic,
hand-checked models. It implements:

- exhaustive reachability over a fingerprint set with a bounded state budget whose
  exhaustion is reported as `truncated` — an inconclusive result that can never be
  read as a pass;
- safety invariant checking with shortest counterexample traces (initial states
  included), plus trace replay to validate every step is an enabled transition;
- leads-to liveness checking (`<>target`) by sticky-cycle detection over the reachable
  graph, with terminal states treated as stuttering (TLA+ semantics: a stopped
  execution repeats forever), so a dead end short of the target is a violation;
- state abstraction with counterexample spuriousness replay (benchmark step 5): a
  deliberately over-coarse abstraction is included precisely to demonstrate the
  harness flagging its own invented counterexample as spurious;
- a hand-written abstract model of the canonical seam's exactly-once contract
  (occurrence claiming, duplicate-claim consumption, cursor-after-run discipline).
  Dropping each documented guard makes the checker rediscover the corresponding
  defect shape — the second-Run race and the cursor-stamped-without-Run skip — which
  is the failure class the leaf asks about, caught on a hand-checked model. It is
  evidence about the technique, never about the real implementation, which carries
  the guards.

Relationship to existing evidence infrastructure (epic non-goal: no competing
`formal/` authority): `formal/` stays the canonical in-tree model suite — randomized
Hypothesis state machines against the real code. This harness is the complementary
mechanism (exhaustive checking of hand-written abstract models), shares nothing with
it, and does not modify it. The Hypothesis-integration step of the procedure below is
future work, deliberately not claimed as done.

## Benchmark procedure (what a real experiment must do)

1. Identify a bounded concurrency-critical subsystem (e.g., task admission cycle with overlap policies);
2. Manual abstraction to a TLA+/Apalache model, preserving key async interleavings;
3. Define safety/liveness invariants based on MAIstro's execution contract (ADR-081426-1f7c);
4. Run Apalache (or the in-repo explicit-state checker on the same abstract model) to check invariants against bounded execution traces;
5. Analyze counterexamples for spuriousness (due to abstraction) vs real bugs — the harness's trace replay is the prototype of this step;
6. Map confirmed bugs to MAIstro code and assess fix cost;
7. Emit disposition: GRADUATE if model checking finds actionable bugs with low false-positive rate; INCUBATE if promising but needs better abstraction; REJECT if cost/yield unfavorable; WATCH if external tooling not ready.

## Trust boundary

Experimental model checking outputs are evidence, not authorization. Nothing in this change reads or writes a Goal, a Run authority, or a Warden/HITL/delegation control. Any future adoption must route through the earliest owning milestone and the canonical authorization paths (ADR-068).

## Dispositions

- **WATCH** — exploratory harness created (explicit-state checker + hand-checked occurrence-claim model, 41 checks); no Apalache/TLA+ run and no real-subsystem abstraction yet. Move to INCUBATE on a successful abstraction of a real MAIstro subsystem with non-spurious counterexamples (checker or Apalache). Move to GRADUATE if model checking finds bugs that, when fixed, reduce escape defects in representative MAIstro workloads with acceptable engineering cost.