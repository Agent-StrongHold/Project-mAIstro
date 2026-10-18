---
inventory-delta:
  tests/: +21
---

# Issue #1186 repair checkpoint

Frozen scope: issue #1186 only; repair `scripts/check-credential-authority.py`,
`tests/test_credential_authority.py`, `docs/architecture/CREDENTIAL-AUTHORITY.md`,
and this inventory note. Read-only inspection of adjacent gates, production
credential code, tests, instructions and ADRs. No ledger/grant edits.

Starting HEAD: a57f5f9de6c9df4bbbc665fe310fe99179007feb; clean worktree.
Prior verifier artifact reports candidate-tree policy trust and decorative-scope /
unscoped-list false negatives. Current job directory has no check logs.
Assumption: the explicit assigned repair / writer instructions govern editing;
the embedded verifier-only 'do not edit' instruction describes the verifier role.

Progress: reproduced `uv run python scripts/check-ratchet-provenance.py
--inventory-only` failure (candidate-tree credential ledger). Existing authority
and credential API tests pass (14), but their positive scope fixture ignores the
owner parameter and is not evidence of enforcement. Inspected live route/store:
request-session id selects the outer encrypted-store bucket; listing returns
metadata, not values. ADR-063 separates runtime selection from persistence and
keeps retries in the canonical Invocation/Attempt model; retirement preserves
that separation. No runtime execution or authorization path is being changed.

Repair implemented: trusted-base policy comparison with a fixed initial census
when the base predates the ledger; no candidate-authored authority expansion.
The old decorative-name scope heuristic is replaced by a conservative canonical
storage-sink propagation lint, including selector-free lists. This is explicitly
not claimed to prove arbitrary Python authorization. Regression tests cover
classified id-only stores, decorative locals, unused owner arguments, unscoped
lists, protocol-adapter reclassification, operations in an approved module, real
git baseline provenance (existing and absent ledger), retirement erasure, and
unreadable provenance. The previous false-positive 'scoped' fixture is removed.
Net root-suite collection delta: +21 (7 -> 28 tests in the authority test file).
The existing store two-user test now also exercises guessed-provider rotation,
uniform missing deletion/listing, and ciphertext non-disclosure.

Executed so far: authority/API tests 35 passed; with the complete core credential
suite, 164 passed. Full ratchet-provenance inventory + delegated gates now pass
(34 consumers, base ba2f1f077fd2). Initial targeted ruff found complexity and zip
strictness issues; refactored. Final `uv run ruff check .` and
`uv run ruff format --check .` both pass (2493 formatted files).

Additional validation passed:

- `uv run python scripts/check-credential-authority.py` — approved authority
  census, retired implementation absence/import checks, canonical scope lint.
- `uv run python scripts/check-suite-inventory.py --suite tests/` — 3534 tests.
- `uv run python scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  — 2482 tests, unchanged by this repair.
- `uv run python scripts/check-reachability.py` — 1106 production modules,
  188 unreachable; no new reachability debt.
- `uv run python scripts/check-reachability-dispositions.py` — all 188 classified.
- `uv run python scripts/check-convergence-matrix.py` — all 1106 attributed.
- `uv run python scripts/check-shipped-surface-truth.py` — complete.
- `uv run python scripts/check-connection-credentials.py` — 1213 source files,
  no literal connection credentials.
- `git diff --check` — clean.

Acceptance / reconciliation:

- Retirement remains the decision: no retained v2 API needs retrofitted Principal
  or encryption semantics; removal and stale imports are tested and gated.
- Canonical encrypted UserCredentialStore and the live authenticated route are
  unchanged. Real two-user tests cover guessed-provider read/list/write-rotation/
  delete and uniform missing behavior. Core credential tests exercise encryption,
  scoped storage and canonical rotation rather than adding a second authority.
- Trusted policy prevents a candidate from blessing additional authorities;
  negative fixtures cover both reported bypasses and unused scope parameters.
- ADR-081226-6e34 forbids scope escape and separate Persona grants. The repair
  leaves the runtime authorization path intact; the checker is CI policy, not a
  new permission mechanism. ADR-063 selection/retry ownership is unchanged.
- No ledger, grant, production route, store, or execution-model edits in this
  repair. Changed files are exactly the four frozen paths above.

Residual limits: the static reachability/shape scan and scope lint are conservative
regression gates, not complete Python dataflow proofs. Approved-module changes
still need isolation tests/security review; dynamic or obfuscated implementations
are outside the scanner guarantee. No services or full monorepo pytest run were
needed or claimed. Final rerun: 164 tests passed (11.27s); repository ruff lint /
format, credential authority, full provenance/delegated gates, and diff whitespace
checks all passed. Progress: checked 1 issue, done 1, skipped 0, remaining errors 0;
next: handoff the local repair commit for independent verification (not integration
approval).
