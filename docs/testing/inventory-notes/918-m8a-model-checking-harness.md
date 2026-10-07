---
inventory-delta:
  packages/maistro-rsi/tests: +40
---
# 918 M8-A: TLA+/Apalache-equivalent model-checking harness (+40)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #918 (epic #880, initiative #879) asked for exploratory research on
concurrency/model checking with TLA+/Apalache or equivalent. No Apalache/TLA+
toolchain exists in this repo's deterministic CI and none was run, so the research
record (`docs/research/918-concurrency-model-checking-tla-apalache.md`) registers
WATCH and this change adds the technique's mechanics as one self-contained test
module in `packages/maistro-rsi/tests/`
(`test_m8a_tlaplus_model_checking_research.py`, +40 node IDs, replacing a prior
docstring-only stub that collected zero tests).

The module is deliberately test-side and imports no maistro module (AST-checked): it
is research evidence, not product code (M8 guardrails 1-2), so no vulture/reachability
identity changes. The 40 checks validate, on hand-checked fixtures: the explicit-state
checker's mechanics (exact 9-state grid exploration, determinism, shortest
counterexample traces with hand-checked labels, violation at an initial state with an
empty path, honest `truncated` flag when the state budget stops exploration — never
readable as a pass, degenerate empty/zero-budget cases, frozen result records); safety
and leads-to liveness checking (`<>target` via sticky-cycle detection, terminal states
as stuttering per TLA+ semantics, deterministic cycle extraction, hand-checked ring
cycle `(b, c)`); abstraction (cap abstraction shrinking 9→4 states with no invented
failure, an over-coarse abstraction whose invented liveness counterexample is flagged
spurious by trace replay, replay of real counterexamples, and replay rejecting
fabricated traces and non-initial start states); liveness scoping (post-target
cycles never violate `<>target`, a bad cycle short of the target still does, and a
spurious cycle is rejected by full-lasso replay even when its stem replays
concretely); and the canonical-seam model of
exactly-once occurrence claiming (`scheduling/admission.py`'s contract abstracted:
one Run per occurrence, duplicate claims consumed, cursor stamped only after the Run —
hand-checked 7-state single-ticker space, the two-ticker race staying at one Run, and
both documented defect shapes rediscovered when each guard is dropped, with
hand-checked trace labels). The evidence-only contract itself (advisory marker, WATCH
disposition constant, no maistro imports) is asserted so it cannot silently rot.
