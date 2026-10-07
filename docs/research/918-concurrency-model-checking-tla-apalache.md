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

This note does not report a provider experiment. No real-model corpus exists in this repository's deterministic CI, and manufacturing one was out of scope; absent evidence is recorded rather than simulated (M8 guardrail 3). This change adds no product code, no feature flag, and touches no authority path.

What this change does add is an exploratory model checking harness as a clearly separated research artifact:
`packages/maistro-rsi/tests/test_m8a_tlaplus_model_checking_research.py` (test suite only; it imports nothing from `maistro`, so it cannot become an authority by accident — M8 guardrails 1 and 2). Validated on deterministic, hand-checked behavioral models, it implements:

- TLA+ specification extraction from async Python code via manual abstraction;
- Apalache model checking for invariant violation detection;
- Counterexample trace generation and simplification;
- Focus on liveness properties (e.g., "every admitted task eventually completes or fails") and safety properties (e.g., "no two tasks write to the same run record concurrently");
- Integration with existing Hypothesis state machine testing where applicable.

## Benchmark procedure (what a real experiment must do)

1. Identify a bounded concurrency-critical subsystem (e.g., task admission cycle with overlap policies);
2. Manual abstraction to TLA++/Apalache model, preserving key async interleavings;
3. Define safety/liveness invariants based on MAIstro's execution contract (ADR-081426-1f7c);
4. Run Apalache to check invariants against bounded execution traces;
5. Analyze counterexamples for spuriousness (due to abstraction) vs real bugs;
6. Map confirmed bugs to MAIstro code and assess fix cost;
7. Emit disposition: GRADUATE if model checking finds actionable bugs with low false-positive rate; INCUBATE if promising but needs better abstraction; REJECT if cost/yield unfavorable; WATCH if external tooling not ready.

## Trust boundary

Experimental model checking outputs are evidence, not authorization. Nothing in this change reads or writes a Goal, a Run authority, or a Warden/HITL/delegation control. Any future adoption must route through the earliest owning milestone and the canonical authorization paths (ADR-068).

## Dispositions

- **WATCH** — exploratory harness created; no real-model evidence yet. Move to INCUBATE on successful abstraction of a MAIstro subsystem with non-spurious counterexamples. Move to GRADUATE if model checking finds bugs that, when fixed, reduce escape defects in representative MAIstro workloads with acceptable engineering cost.