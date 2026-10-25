---
inventory-delta:
  packages/maistro-core/tests: +29
---

# Eval-workspace conformance command and validator dissolution (#107 repair)

Adds `maistro eval-workspace conformance` (packages/maistro-core/src/maistro/
cli/_eval_workspace.py) — the production consumer the #107 substrate was
missing — and 29 node IDs covering it in
`packages/maistro-core/tests/eval_workspace/test_conformance_cli.py`.

Why a consumer landed in a repair round: the vulture per-identity ledger and
both reachability gates refused the branch because `maistro.eval_workspace`
had no in-repo production caller — every surface (`provision`, `activate`,
`fork_from_workspace`, `fork_from_snapshot`, `find_by_owner`, `warm_count`)
was test-only, and a grant cannot authorize its own introduction
(`ratchet_provenance.load_authorizations` reads grants from the merge base).
The command drives the whole lifecycle through `SandboxProtocol` on the real
backend (fake under `--allow-fake` for protocol shape), so the findings are
eliminated by usage rather than banked.

The coverage splits along what a conformance harness must prove:

- **Passing runs** (4): the full proof passes on the fake backend with every
  check `pass` or truthfully `unsupported`; the report's environment digest
  binds the declared inputs (image changes change it); the command prints
  identities, costs and verdict; on a host that can build one, the proof
  passes on a real tier (`requires_bwrap`, mirroring tests/sandbox).
- **Explicit non-answers** (3): no backend at all, no backend satisfying the
  interactive policy, and `_pick_backend` refusing the fake without the
  opt-in — each a loud exit, never a silent pass.
- **The proof can fail** (22): drifting reads, spawn faults, write faults
  after the seed, read faults at capture, cross-instance leaks, a branch
  record lying about its start digest (`model_copy(update=...)` forging the
  tampered-record shape), an ownership claim miss, `find_by_owner`
  disagreeing with the claim, a second attempt stealing a held workspace, a
  non-owner release that wrongly succeeds, a warm-count overstatement, and
  digest disagreement between two provisions of one input set. Each injected
  failure asserts the check reports `fail` (and the command exits 1 for the
  command-level variants).

The model restructure in the same round (blank checks became declarative
`NonBlankStr` field constraints; `validate_invariants` is now itself the
`@model_validator(mode="after")` the store's write door calls by name) is
covered by the existing lifecycle suite (41 node IDs, unchanged count).
