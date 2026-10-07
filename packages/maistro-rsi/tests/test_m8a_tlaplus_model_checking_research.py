"""M8-A research harness — concurrency/model checking with TLA+/Apalache or equivalent.

Issue #918 (epic #880, initiative #879). Hypothesis under study: lightweight
concurrency bugs in MAIstro's core can be detected early using TLA+ or Apalache
model checking, focusing on race conditions in state management, task admission,
or extension lifecycle that existing testing misses.

This module is a RESEARCH ARTIFACT, not product code. It implements an
exploratory model checking harness to evaluate the feasibility and yield of
applying formal methods to MAIstro's concurrency-critical subsystems.

Trust boundary (the epic's contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Run authority, a routing decision, or a
  Warden/HITL/delegation control. It imports nothing from ``maistro`` at all,
  so it cannot become an authority by accident (M8 guardrails 1 and 2).
- Observed behavior from real Maistro execution is the only judge for
  counterexample validity. Abstract models must be validated against
  concrete traces to avoid spurious results.
- The harness is deliberately limited to exploration; it does not implement
  full TLA+/Apalache integration but documents the approach for future
  investigation.

Relationship to the canonical seams: potential modeling targets include
task admission (`packages/maistro-core/src/maistro/scheduling/`), extension
lifecycle state machines (`packages/maistro-core/src/maistro/extensions/`),
and durable run state transitions (`packages/maistro-core/src/maistro/graph/
durable_runs/`). These are orthogonal to routing authority and do not
conflict with existing verification infrastructure.

The experiment records and terminal dispositions live in
``docs/research/918-concurrency-model-checking-tla-apalache.md``. This
harness exists to document the research approach; no synthetic corpora or
metric machinery are implemented at this exploratory stage.

Usage:
    # This file is deliberately not executable; it serves as documentation
    # of the research approach for issue #918.
    # To contribute to this research, edit this file and the associated
    # research note to reflect progress on the TLA+/Apalache exploration.
"""
