---
inventory-delta:
  packages/maistro-rsi/tests: +27
---
# 897 M8-A16: Lean/Leanstral + Rust/Aeneas kernel-feasibility harness (+27)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #897 (epic #880, initiative #879) asked for a bounded real-code
prototype evaluating Lean and Rust/Charon/Aeneas feasibility for a tiny
MAIstro correctness kernel, with an explicit model-equivalence measurement.
The research record (`docs/research/897-lean-leanstral-rust-aeneas-correctness-kernel.md`)
registers **WATCH** — no Lean proof was machine-checked, no Rust crate was
built, and the Leanstral API was not exercised (none of those toolchains or
networks exist in this repo's deterministic CI) — and this change adds the
prototype's mechanics as one self-contained test module in
`packages/maistro-rsi/tests/`
(`test_m8a16_lean_rust_kernel_research.py`, +27 node IDs). The module is
deliberately test-side and imports no maistro module (AST-checked): it reads
the production source as text and never writes it, so it cannot become an
authority by accident (M8 guardrails 1–2), and it changes no product code, so
no vulture/reachability identity moves.

The 27 checks validate, on the real seam and hand-checked fixtures:

- **Mechanical extraction (the "Python semantic-model path", step 1).** The
  `RUN_TRANSITIONS` / `ATTEMPT_TRANSITIONS` tables, terminal sets and status
  universes are AST-extracted from the real
  `maistro/runs/lifecycle.py` + `maistro/runs/model.py` (text read, never an
  import). Three synthetic drift cases make the extraction fail LOUDLY —
  missing table, computed-not-literal table, non-enum keys — because a silent
  fallback to a stale snapshot would void every equivalence claim downstream.
- **Three-way artifact equivalence.** The embedded Lean 4 kernel and the
  embedded safe-sequential Rust kernel are parsed (regex over the artifact
  text, not trust) and equated against the extraction: status universes,
  terminal sets, and every transition row, for Runs and Attempts. A mutated
  Lean row fails as `lean run row drift at <status>` — verified by mutation
  during development, not assumed.
- **Python duals of the Lean theorems.** Terminal statuses absorb (Runs and
  Attempts), no self-loops, every non-terminal status reaches every terminal
  status, `transition_path` returns a path iff the target is reachable (against
  an independent fixpoint closure oracle), returned steps are legal and
  shortest (layer-count oracle), and the search is deterministic — one dual
  per theorem the Lean artifact states, named in its docstrings.
- **The measured translatability surface.** All 20 top-level functions of
  `lifecycle.py` are classified pure-decision (10) vs pydantic/clock-boundary
  (10), with the classification enforced against the AST: a body that touches
  `model_validate`/`model_dump`/`model_copy`/`now`/`datetime` cannot be
  classified translatable, and an unclassified function (the module evolving)
  fails loudly — that failure IS the maintenance-cost measurement.
- **The evidence-only contract.** Advisory marker, WATCH disposition, frozen
  report records (mutation refused), no maistro imports, no
  network/subprocess imports, production files read-but-never-written, honest
  toolchain records (`elan/Lean 4`, `cargo/rustc`, `Charon/Aeneas`,
  Leanstral: all unavailable and unexercised, with recorded reassessment
  triggers), and the six evidence questions answered in one frozen report.
