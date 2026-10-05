---
inventory-delta:
  packages/maistro-core/tests: +44
---
# #965 — shared extension-family conformance suite

Issue #965 (M9-E4) adds a conformance framework that proves third-party
provider/connector/tool implementations obey the same cross-cutting platform
semantics as supported built-ins. The framework lives in
`packages/maistro-core/src/maistro/conformance/` (contract, subject protocol,
shared check bodies, runner) with a `maistro conformance` CLI surface.

**+23 `packages/maistro-core/tests`**, all under `tests/testing/`:

- `test_extension_conformance.py` (+10): the shared suite executed end to end
  — the reference conformant subject passes with a valid claim in all three
  families (`PROVIDER`/`CONNECTOR`/`TOOL`, parametrized); the report names the
  exact contract id/version/backend; and one negative leg per broken semantic:
  a plaintext-secret keeper, a raw-socket egress bypass (detected by the audit
  server's wire-hit count, not source inspection), and an uncancellable
  effect. Plus policy restoration and run repeatability.
- `test_conformance_claim_contract.py` (+13): the claim-contract rules —
  skipped real-backend legs refuse claims and are fatal under
  `MAISTRO_REQUIRE_REAL_BACKEND_LEGS`; an executed-but-failed leg is a
  finding, not a missing leg; a declared contract-version mismatch refuses the
  claim even when every check passes; discovery is entry-point-only; an empty
  report is never a claim; CLI registration and empty-registry fail-closed.
- Repair round (CI quality/coverage gates), **+21 more**: the suite's own
  verdict branches were below the diff-coverage floor (90% lines / 80%
  branches per changed file). New single-property violators drive each check
  body's negative branches directly: secret-check strip-vs-foreign-error,
  credential-ref subject-side scope denial and a simulated repr leak in the
  credential seam, the egress verdict matrix (quiet normalized refusal,
  non-refusal crash, no-fetch declared leg, double fetch, offsite origin on a
  declared leg, unavailable provider, raw-then-guarded bypass caught by wire
  evidence), deadline refusal of vacuous probes and exception-on-cancel
  surfaces, usage rejection of incomplete effects / drifted units / usage
  claimed on unreported effects, negative-usage and wrong-refusal-shape
  fail-closed pins, CLI success render + subjects listing (partial and full
  family coverage) + drift-guard loudness, and `ConformanceReport.result()`
  scan-past/missing arcs.

`tests/testing/conformance_subjects.py` is a helper module (reference subject
plus one-property violators), not a collected test file; `conftest.py` there
gained an autouse fresh-event-loop fixture for sync tests only (no count
change; `test_faux_provider.py`/`test_harness.py` still pass under it).

Validation on this head: `uv run pytest packages/maistro-core/tests/testing -q`
104 passed; ruff check/format clean on changed paths;
`python scripts/check-suite-inventory.py` green after this note (drift was
exactly +44, all from the two files above); diff-coverage gate green
(`check-diff-coverage.py` with the core producer's data).
