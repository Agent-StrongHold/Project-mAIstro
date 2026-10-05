---
inventory-delta:
  packages/maistro-core/tests: +23
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

`tests/testing/conformance_subjects.py` is a helper module (reference subject
plus one-property violators), not a collected test file; `conftest.py` there
gained an autouse fresh-event-loop fixture for sync tests only (no count
change; `test_faux_provider.py`/`test_harness.py` still pass under it).

Validation on this head: `uv run pytest packages/maistro-core/tests/testing -q`
83 passed; ruff check/format clean on changed paths;
`python scripts/check-suite-inventory.py` green after this note (drift was
exactly +23, all from the two files above).
