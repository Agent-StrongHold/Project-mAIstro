# Issue #1893 assigned repair checkpoint

## Frozen scope

- Assigned branch/worktree: `auto-1893`, `/home/dev/Git/wt/auto-1893`.
- Exact starting HEAD verified: `39cc35440c52e96b4e3d6b01e2b4085da8fea12d`.
- Assigned base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Initial worktree clean; no incoming edits to salvage.
- Process only issue #1893 using the supplied dispatch snapshot. Inspect existing
  `admission_codec.py`, `admission_identity.py`, their adjacent tests, applicable
  ADRs/workflows, supplied logs, and the named gates. No GitHub mutations.
- Ambiguity: generic CI `test: failure` has no failing node in the brief. Reproduce
  focused tests before deciding whether any source/test repair is justified.
- Reachability grant edits are prohibited; the explicit exception is only for
  reviewed vulture identities discovered by the exact requested scanner.
- No production activation or competing execution authority is authorized.

## Executed evidence

- Exact requested Vulture scan passed: 1322 findings, zero unclassified; no ledger
  amendment is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python
  scripts/check-ratchet-provenance.py` failed (exit 1): both admission modules
  introduce unauthorized unreachable modules and unauthorized dispositions.
  Remaining wrapper gates passed. This is not a Vulture identity failure.
- Supplied check-0 through check-4 logs were read: dependency sync, ruff,
  formatting and inventory pass; focused tests report 324 passed, 3 skipped.
- Prior result artifact was read for context only; its results are not claimed
  as fresh execution.
- Fresh focused command: `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q`:
  **324 passed, 3 skipped**, 327 nodes, 1.75 seconds.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, 2 files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16543 nodes, zero duplicate evidence.

All validation commands above used 1200-second timeouts. Both PostgreSQL test
URL variables are unset. The three skipped tests are not durability evidence.
Read accepted ADR-081226-a66b and ADR-083126-5e62: canonical execution ownership
and trusted-base policy authority remain unchanged. Production import search
finds no caller of admission_codec; admission_identity is imported by the codec
and Vulture whitelist only. Tests and whitelist references do not supply runtime
reachability. The issue's inactive staging constraint cannot be reconciled with
the failed gate by inventing a production caller or editing candidate grants.

## Acceptance audit and limits

Reviewed the full codec and identity implementations and both adjacent contract
test files; the following claims refer to the fresh focused execution above.

| Criterion | Evidence / limitation |
| --- | --- |
| Frozen/slotted header, named fields, strict versions and signed timestamps | Header implementation at admission_codec.py:159–258; existing invalid scalar, schema, format and header-mismatch tests PASS. |
| Exact immutable DTOs and fresh flat mapping | Existing v2 three-state round trips and fresh mapping tests PASS; binding storage shape is independently asserted at test_admission_codec.py:134–137. |
| UUID hex at storage only, owner-token hygiene | Existing owner-token and generation rejection tests PASS; constructors keep actual UUID objects. |
| Legacy bound/unbound/partial/receipt-only with no inferred identity | Existing legacy tests PASS. A pair without receipt evidence fails partial, since the shared binding constructor requires a receipt; no invented receipt is permitted. Optional completed_at is never read. |
| Header/full decode separation; no clock, incoming fingerprint or claim decision | Header expiry/fingerprint preservation and mismatch tests PASS. Consumer expiry/409 ordering remains outside this leaf and UNVERIFIED. |
| Strict snapshot TEXT and safe errors | Existing duplicate/nonobject/nonfinite, nesting, lossy number and Unicode corruption tests PASS; corruption is injected into raw row TEXT, and tests assert suppressed chains. |
| Tagged nonfinite program_context and unchanged stored fingerprint | Tagged nan/inf/-inf tests PASS. Production model_of/model_of_json materialization and original request fingerprint computation remain UNVERIFIED; fixtures only prove tag and stored-digest retention. |
| Both raw/production PostgreSQL pools, real migrations, TEXT parameters, JSONB object payload | UNVERIFIED: three codec PG tests skipped; no disposable DB started in this blocked round. No sessions, SQL row counts or migration results claimed. |
| Explicit authorized principals, Workspace/Project and registered Graph | UNVERIFIED for live admission: fixtures construct DTOs, not authorization or Graph registration calls. |
| No SQL mutation, HTTP/queue/scope/assessor or legacy/deletion policy change | This round changes only this report. Import search confirms inactive staging, not reachable admission behavior. |
| Focused tests, typing, lint, inventory, required quality gates | Commands above PASS except trusted-base provenance. Full required integration CI remains UNVERIFIED. |

Additional fresh execution: `uv run pytest packages/maistro-core/tests/tasks
packages/maistro-core/tests/runs -x -q` (1200-second timeout): **1919 passed,
310 skipped, 6 warnings**, 2229 nodes, 51.87 seconds. Warnings are aiosqlite
worker-thread `Event loop is closed` reports in test_sqlite_store.py, not codec
assertion failures. No skipped test is claimed as durability evidence.

## Disposition and handoff

**BLOCKED.** The actual failed command is the provenance wrapper, rejecting
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612–613`. Vulture succeeds; changing its
ledger cannot repair these failures. Existing implementation and ledger edits
are preserved, not discarded. No develop conflict exists at the assigned head.
The protected-base authorization prerequisite requires campaign-owner action
outside this lane, followed by a separately authorized integration/revalidation.
No GitHub mutation, fetch, merge, activation or gate weakening was performed.

The generic reported `test: failure` is **UNRESOLVED**, not reproduced by either
fresh scoped test command. A bounded check-run extraction from the supplied
snapshot did not recover a failing-node log; no failing test is guessed. Supply
the actual SHA-qualified merge-queue log before a code repair. PostgreSQL and
full integration acceptance remain explicitly unverified, rather than inheriting
prior runs' claims.

Only this report changed. No test/source repair or inventory-count change was
justified, so no inventory delta or new pre-fix/mutation evidence is claimed.
This is a locally committed blocked handoff, not integration approval.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 blocking
provenance command. Next: coordinate the protected-base prerequisite and obtain
the failing test log before another repair dispatch.
