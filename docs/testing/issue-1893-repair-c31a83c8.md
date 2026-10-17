# Issue #1893 — repair checkpoint c31a83c8

## Frozen scope

- Assigned branch/worktree: `auto-1893`, `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `0fe3eb886540d67bd7b1eb735f6333d3b899d8e4` (clean).
- Supplied develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- One item: #1893 immutable admission codec, its prerequisite identity DTO and
  adjacent tests. No other issue/PR will be processed.
- Initial writable scope: this validation report only. Evidence-backed codec/test
  repairs if demonstrated; Vulture ledger only if the requested scan warrants it.
  No reachability/grant/gate edits, activation or remote mutations.

## Evidence and ambiguity

Read the supplied dispatch issue body and prior result. The driver logs report
ruff/format success, 346 passed / 3 skipped, inventory 16567. These are supplied
results, not this worker's executions. The prior worker reported unresolved
trusted-base reachability authorization and an unlocalized hosted `test` failure.
Assumption: this is a writer CI-repair round, not authorization to wire a staged
codec into live admission or alter reachability policy. No develop conflict is
present, so no sync is justified by the conditional sync instruction.

## Independently reproduced blocker

At starting HEAD, with 1200-second command timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1322 findings, zero unclassified. No Vulture ledger amendment is warranted.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`
  exited 1. Both `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` are new unreachable modules and new dispositions
  absent from trusted-base authorization (four errors). Local `origin/develop`
  resolves to that exact supplied base. This is not a merge conflict.

Read accepted ADR-082826-b601 and ADR-083126-5e62 completely. Reconciliation:
canonical execution remains opt-in and candidate bookkeeping cannot authorize
itself. The Vulture-only exception cannot repair reachability provenance. The
codec explicitly has no production consumer; a fake caller or unauthorized
activation would not be a valid repair. This round will remain BLOCKED unless
other executed evidence changes that conclusion. Focused validation follows;
PostgreSQL skips will not count as durability evidence.

## Focused validation at starting source SHA

All commands below used 1200-second timeouts and ran independently of the driver:

- `uv run ruff check .` — passed.
- `uv run ruff format --check .` — passed, 3301 files formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`
  — passed, 2 files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`
  — 349 nodes, 346 passed, 3 skipped (test database URLs unset).
- `uv run python scripts/check-shipped-surface-truth.py` — passed.
- `uv run python scripts/check-reachability.py` — passed candidate ledger,
  1403 modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py` — passed candidate
  ledger, 50 groups / 171 modules.
- `uv run python scripts/check-promotion-surface.py` — passed, 74 tolerated modules.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`
  — passed, 16567 nodes, no duplicate evidence.

Production-source import search finds only the codec importing the identity DTO
and a Vulture whitelist import, not a codec runtime caller. Candidate-ledger
checks do not override the failed trusted-base check. No source/test change is
justified by these results. No tests were added, so no inventory delta is needed.

- `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`
  — 2229 nodes: 1919 passed, 310 skipped, 5 aiosqlite worker-thread warnings
  (`RuntimeError: Event loop is closed`), 48.25 seconds. No failing test node.
- `git diff --check` — passed.

## Acceptance accounting

Read the complete codec, prerequisite identity DTO and both contract test files.
The focused run above includes every prospective B2 test name (the real-pool
case is parametrized into three skipped nodes).

| Criterion | Executed evidence or limitation |
| --- | --- |
| Exact shared APIs; frozen/slotted header; six typed errors; fresh flat SQL mapping | Source inspection and passing header/schema/encode tests in the focused command |
| Header scalar match; strict storage UUID hex; signed timestamps; DTO constructors | Passing scalar mismatch, invalid header, storage owner/generation, v2 validation and identity DTO tests |
| No raw snapshot/token in errors; validated scope hash; suppressed unsafe parse chain | Passing invalid/duplicate JSON, deep nesting, lossy number, Unicode and owner token tests |
| Immutable snapshots, preserved fingerprint and permitted tagged evidence | Passing unbound/bound/acknowledged byte round trips and tagged nonfinite tests; tests assert the storage binding shape independently of encoder/decoder agreement |
| Legacy bound/unbound/partial/receipt-only/announced-without-Run distinctions | Passing legacy binding tests. Bound task/run pair without stored receipt remains typed partial, because the prerequisite binding constructor requires receipt identity; inventing a receipt would violate the no-guessing requirement |
| Header survives corrupt snapshot or partial binding; no expiry/claim decision | Passing named expiry/fingerprint header separation tests; no clock or request fingerprint parameter exists |
| Unknown format fails closed | Passing unsupported-format tests (including attempts to reuse a supported header) |
| Named SQL field mapping; optional completed_at not authority | Passing encode and completed_at tests; production code contains no SQL statements or row-position reads |
| Real raw/production pool comparison on same disposable migrated PostgreSQL DB | UNVERIFIED: all three DB nodes skipped for unset URLs. No migration, database session identities or final row counts claimed |
| Existing evidence-json/model_of materialization, arbitrary permitted program_context and Run JSONB object shape | UNVERIFIED end-to-end: tests hand-build tags; codec preserves text and does not materialize models or insert Runs |
| Authorized positive admission with explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED: DTO fixtures are not authorized production admission flows |
| Typed representation only, unchanged live assessment/scope/HTTP/queue/claim/legacy policy | Full source inspection and production import search; this round edits this report only. Canonical execution spine remains unchanged |
| Expired replacement and 409 precedence | UNVERIFIED, intentionally later C/F2 behavior rather than B2's pure codec responsibility |
| Focused tests, ruff/format/mypy, inventory | Passed as recorded above, with explicit PG exclusions; no new tests or inventory change |
| Unchanged integration CI and no self-authorizing reachability expansion | FAILED trusted-base provenance. Hosted `test: failure` remains unlocalized; full integration CI UNVERIFIED |

No pre-fix or mutation experiment is claimed: no code repair was made. Existing
negative tests inject malformed storage at the actual codec boundary; they do
not establish transaction/crash/dispatch invariants. Skipped PG tests and past
worker reports are not adopted as current durability proof.

## Disposition and next action

BLOCKED, not merge-ready. The reproduced errors refer to
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. A coordinated trusted-base prerequisite
must land before this branch can pass provenance; that authorization is outside
this writer lane. Do not re-dispatch an unchanged repair without that prerequisite
or a concrete hosted failing test node/traceback.

Changed file: `docs/testing/issue-1893-repair-c31a83c8.md` only, committed locally
as the required writer handoff. No gate, ledger, grant, implementation or test
edits. No fetch, merge, remote mutation, destructive Git command or DB mutation.
Residual risks: absent runtime consumer, unverified database/materialization
acceptance, unlocalized hosted test failure and SQLite cleanup warnings.

Progress: {checked: 1, done: 0, skipped: 0, errors: 1,
next: coordinated trusted-base authorization and localized hosted-test evidence}.
