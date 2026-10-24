# Issue #1893 repair evidence — f4ddaefd

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `610a50ec5adcfe26b616b029d57335129d3e8ada`; supplied base `2154f845347c9541016288c760f8da3f5cd2e064`. Initial tree clean.
- Process only issue #1893: existing admission codec, admission identity DTOs, adjacent tests and associated CI evidence. No new activation, scheduler, identity inference, grants or reachability ledger changes.
- Candidate edit set: this evidence document; implementation/tests or Vulture ledger only if an executed check demonstrates a relevant defect. No tests added yet.
- Dispatch snapshot read from the supplied job directory; no GitHub queries or mutations. Driver check logs: sync/lint/format/inventory passed; focused tests 312 passed, 3 skipped. These skips do not prove database durability.
- Ambiguity: dispatch says `test: failure` without a failing test/log. Assume focused local reproduction and the named exact-debt gates are the repair targets; do not guess a defect. Prior result reports reachability provenance blocked; independently recheck before disposition.

## Validation

- `uv sync --locked --extra dev`: PASS.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings, zero unclassified. No Vulture ledger edit is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both admission modules are new unreachable modules and new dispositions without already-landed authorization. The failure is independently reproduced, not inferred from the prior report.
- Production import search finds only codec -> identity and a Vulture whitelist import; codec lines 50–53 explicitly describe inactivity. No reachable production consumer was found.
- Concrete blocker lies outside the permitted Vulture ledger exception. No merge conflict or develop-sync failure exists; do not fetch or merge speculatively. Continue focused acceptance validation, then report BLOCKED rather than changing grants or inventing a caller.
- Read accepted ADR-081226-a66b (execution hierarchy), ADR-082526-7f02 (immutable provenance) and ADR-083126-5e62 (trusted-base authority). No conflicting behavior is introduced; inactive representation is not runtime admission authority.
- `uv run ruff check .`, `uv run ruff format --check .`: PASS (3301 files formatted).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS (16541 nodes, no duplicate evidence).
- Created fresh disposable PostgreSQL database `issue1893_f4ddaefd` on the verified local `maistro-postgres` container only after checking nonexistence. `uv run alembic upgrade head`: PASS, real chain to 063, log `/tmp/1893-f4ddaefd-migrate.log`.
- Both PG DSNs and DATABASE_URL targeted that database; `MAISTRO_REQUIRE_PG_LEGS=1 REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs --junitxml=/tmp/1893-f4ddaefd-focused.xml -o junit_family=legacy`: exit 0, log `/tmp/1893-f4ddaefd-focused-pg.log`. Inspect node/session evidence next.
- Final independent SQL: PostgreSQL 18.6, Alembic 063, admission rows=0, canonical Run rows=0, canonical Project rows=0. Database retained for inspection; no shared database truncated.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: FAIL, 1 failed / 3772 passed / 100 skipped / 3 xfailed (35.36s), log `/tmp/1893-f4ddaefd-core.log`. Actual node: `packages/maistro-core/tests/extensions/test_cli_lock.py:138::test_lock_commands_exit_nonzero_for_an_invalid_lock`; expected `not a valid extension lock` is split as `not \na valid extension lock` by terminal wrapping of the temporary path. This is outside #1893 codec scope and not evidence of a codec regression. Record rather than silently altering unrelated tests; one targeted terminal-width contrast will qualify the finding.
- `COLUMNS=120 REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/extensions/test_cli_lock.py -x -q`: also FAIL (1 failed, 6 passed), same wrapped substring. COLUMNS did not affect this captured console. Test failure remains UNRESOLVED and out of the frozen edit scope; no claim it is the unidentified remote CI failure.
- `uv run python scripts/check-reachability.py`: PASS (1403 modules, 171 unreachable); `uv run python scripts/check-reachability-dispositions.py`: PASS (50 groups). Candidate checks do not override trusted-base rejection.
- Focused XML confirms **315 executed nodes, zero skips/failures/errors**, 1.79s pytest summary. Raw/production backend PID pairs: unbound 270960/270959, bound 270962/270961, acknowledged 270964/270963. All sessions report database `issue1893_f4ddaefd`, server `172.20.0.2/32:5432`; each state persisted exactly one admission row before cleanup.

## Acceptance audit

All execution evidence above applies to starting source SHA
`610a50ec5adcfe26b616b029d57335129d3e8ada`; no executable changes were made.

| Requirement | Evidence / limit |
| --- | --- |
| Frozen/slotted header and #1851 immutable records; exact APIs and fresh flat mapping | Source inspected; focused codec/identity tests pass. |
| Named storage fields, strict UUID hex, signed timestamps, header/row agreement | Focused scalar, UUID, mismatch and record-constructor tests pass. Three real SQL inserts satisfy migration 055, including bound task_id = receipt_id. |
| Six typed decode codes, validated hash-only scope, safe error messages/chains | Focused schema/format/header/snapshot/v2/partial tests pass, including private-value injections and suppressed parsing chains. |
| Legacy bound, unresolved, partial pair, receipt-only, announced-without-Run; no guessed identity | Focused legacy tests pass. A bound pair without receipt fails partial rather than fabricating receipt evidence; completed_at is ignored. |
| Minimal scalar evidence survives snapshot/binding failures; unsupported formats fail closed | Both named header-preservation tests and unsupported-format tests pass. Consumer expiry/replacement/409 precedence is outside this leaf and UNVERIFIED. |
| Canonical TEXT, duplicate/nonobject/bare-nonfinite rejection; arbitrary permitted nested evidence | Focused snapshot, Unicode, exact-number, lossy-number, depth and nonfinite-tag tests pass. Canonical bytes/tags and stored fingerprint survive; no double tag decoding in this leaf. |
| Existing evidence-json encoding and model_of/model_of_json materialization; original-model fingerprint unchanged | Tests inject stored tags/fingerprints. The complete original model -> fingerprint -> tagged snapshot -> model materialization path is UNVERIFIED, not established by those fixtures. |
| Same migrated disposable DB; non-null pool; raw/production codec contrast | PASS: actual 001->063 chain, 315 tests without skips, separate backend identities, all TEXT mappings equal. No migration downgrade run claimed. |
| Run JSONB payload is an object, not doubly encoded | UNVERIFIED: codec tests insert admission rows, not canonical Runs. |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED as an admission path: fixture identity strings are not authorization evidence. |
| No SQL mutation, HTTP/queue/scope/policy/assessment change or competing authority | Source is a pure mapping/DTO leaf; no executable changes this round. Goal -> Graph -> Run -> NodeRun -> Attempt preserved. |
| Runtime reachability and unchanged required integration CI | NOT PROVEN: no production codec caller; trusted-base reachability provenance fails. Core suite now has the concrete CLI assertion failure above. Full cross-package integration CI UNVERIFIED. |
| Focused pytest, lint/format, applicable mypy, inventory and named quality gates | Focused/lint/format/mypy/inventory/Vulture/shipped-surface/candidate reachability pass; trusted-base gate fails. No test additions or inventory delta; no mutation/pre-fix failure claimed for an implementation repair because none was made. |

## Handoff

Only changed file: `docs/testing/issue-1893-repair-f4ddaefd.md`.
No source/test/ledger/grant/gate edits were justified within this assignment.

BLOCKED: `.github/workflows/vulture-ratchet.yml:77` rejects the additions at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-614`. Resolution needs separately
coordinated trusted-base authority or an authorized real consumer, not a
candidate grant or Vulture amendment. The unrelated CLI assertion at
`packages/maistro-core/tests/extensions/test_cli_lock.py:138` also needs an
explicitly scoped repair; changing terminal width did not resolve it.

Residual risks are the UNVERIFIED production/materialization/authorization/
Run-payload/integration paths above. No GitHub mutation, fetch, push, merge or
issue closure performed. Local evidence commit only; not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 2, next: owner-coordinated provenance resolution and scoped CLI-test repair}`.

