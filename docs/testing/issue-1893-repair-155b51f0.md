# Issue #1893 repair — job 155b51f0

## Frozen scope and initial evidence

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head `048d52432b65c899531bb3cc394133bc5dca3dd0`; supplied develop base `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Only issue #1893 is in scope. Existing implementation: `maistro/tasks/admission_codec.py`, `maistro/runs/admission_identity.py`, their task/run tests, adjacent task/run behavior and applicable CI gates. No new issue/PR enumeration or GitHub mutation.
- Initial worktree clean; no salvage needed. Planned edit is this evidence note unless a reproducible in-scope defect warrants a repair.
- Inspected supplied dispatch issue body, driver `check-0.log` through `check-4.log`, and prior job `523dc851.../result.json`. Driver results: sync/lint/format pass; focused tests 346 passed, 3 skipped; core inventory 16567 passes. These are supplied evidence, not independent executions.
- Ambiguity: hosted `test: failure` has no supplied traceback. Assumption: reproduce scoped acceptance and the specifically requested exact-debt gates; do not invent a fix for an unidentified failure.
- Previous round reported missing trusted-base reachability authorization. Vulture repair permission does not authorize reachability ledger/grant edits or production activation. Recheck once, then report any unresolved blocker rather than repeat prior repair loops.

## Validation

- Independent exact Vulture command passed: 1322 reviewed identities, 1322 findings, zero unclassified. No Vulture amendment is warranted.
- Independent `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` failed (exit 1): both admission modules are NEW unreachable modules and NEW dispositions without already-landed authorization. Supplied base resolves and is the actual merge base. Logs: `.pytest_cache/repair-155b51f0/{vulture,provenance}.log`.
- Read repository instructions and accepted ADRs 081226-a66b, 082526-7f02, 082826-b601, 083126-5e62. Reconciliation: preserve immutable admission provenance and the one canonical execution hierarchy; no fake imports or unauthorized consumer activation to evade reachability. Candidate evidence cannot grant itself authorization.
- This is a confirmed out-of-lane authorization blocker, not a Vulture debt finding or merge conflict. Do not repeat the failed provenance gate or alter reachability policy. Remaining validation will characterize library acceptance, not claim production activation.
- Fresh Ruff, format, two-module mypy, focused pytest, adjacent task/run pytest and core suite inventory all exited 0 (logs under `.pytest_cache/repair-155b51f0/`). Both PostgreSQL DSN variables are unset; skipped database legs are not durability proof.
- Production Python import search (`rg -n 'admission_codec|admission_identity' packages --glob '*.py' --glob '!**/tests/**'`) finds only the codec importing identity types and the Vulture whitelist. No runtime codec consumer is reachable. `git diff --check` passes.

### Executed command ledger

All validation commands used 1800-second timeouts at the starting source SHA. Local ignored logs are in `.pytest_cache/repair-155b51f0/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 reviewed identities; `vulture.log` |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | FAIL exit 1, four authorization violations; `provenance.log` |
| `uv run ruff check .` | PASS; `ruff.log` |
| `uv run ruff format --check .` | PASS, 3301 files; `format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 source files; `mypy.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs` | 349 nodes: 346 passed, 3 skipped; `focused.log` |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q` | 2229 nodes: 1919 passed, 310 skipped, 6 aiosqlite closed-event-loop thread warnings; `adjacent.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16567 nodes, zero duplicate evidence; `inventory.log` |

### Acceptance assessment

The passing tests below establish the staged library contract only. They do not establish reachable production admission.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, named columns, format/scope/fingerprint/signed scalar validation | Source inspected at `admission_codec.py:127-233`; invalid scalar, unknown-format and missing-column tests pass. |
| Reject mismatched supplied headers; scalar evidence survives invalid full records | Scalar-mismatch tests and both named expiry/fingerprint preservation tests pass. No clock or incoming fingerprint parameter exists. |
| Immutable V2 DTOs, fresh flat mappings, storage-only UUID hex | Three-state round trips, UUID tests, fresh-map assertions and identity immutability tests pass. Binding columns independently asserted at `test_admission_codec.py:134-137`. |
| Legacy bound/unresolved/partial distinctions, receipt-only and announced-without-Run; no invented identity | Legacy pair, missing receipt, receipt-only, whitespace/unreadable evidence and completed-at tests pass. Canonical binding requires actual receipt evidence; missing receipt is not inferred from task_id. |
| Six typed failure codes, validated hash only, safe error messages/chains | Enum/error inspected; malformed JSON, excessive nesting, numeric loss, surrogate, scope and UUID tests pass. Unsafe parse chains are suppressed. |
| Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection, tagged evidence/fingerprint preservation | Strict JSON and tagged nonfinite tests pass; numeric and Unicode storage-boundary injection tests pass. No recalculation of fingerprints occurs. |
| Evidence-json/model_of materialization and original-model fingerprinting, arbitrary permitted program_context | UNVERIFIED end-to-end: fixtures use synthetic tagged JSON and predetermined fingerprints. They prove storage preservation, not production model integration. |
| Real migrated disposable PostgreSQL, raw/production pools, TEXT bindings and JSONB Run object shape | UNVERIFIED this round: three pool tests skipped with both DSNs unset. No database identity, migration execution or SQL residue count claimed. |
| Authorized explicit principals, Workspace/Project, registered Graph kinds | UNVERIFIED production admission: synthetic identity strings in codec fixtures do not prove authorization. |
| No SQL/HTTP/queue/assessment/scope-policy changes or competing execution authority | Inspected codec is Mapping-to-DTO conversion. This round changes only this report. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains untouched. |
| Inventory, lint, format, scoped mypy, required integration gates | Commands above pass except provenance. Full unchanged integration CI and standalone shipped-surface/reachability/promotion commands UNVERIFIED this round; provenance's promotion subcheck passes. |
| Staged coordination and production reachability | Assigned base verified; modules remain inactive. Independent mergeability BLOCKED by missing trusted-base authorization. Activation and consumer expiry/409 behavior remain outside B2. |

No tests or source files added or changed: inventory delta zero, no inventory-note addition needed. No new regression/mutation experiment is claimed. Existing tests inject corrupt row columns directly rather than mocking transaction outcomes.

## Final disposition

**BLOCKED.** `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:606-613` add the two modules without trusted-base authorization. `.github/workflows/vulture-ratchet.yml:77` mandates the failing provenance check. The Vulture exception cannot repair this policy dependency. No merge conflict exists, so no fetch or merge was needed.

Hosted `test: failure` is **UNRESOLVED**: supplied driver logs and freshly executed focused/adjacent tests do not reproduce a failing test. The adjacent SQLite thread warnings are recorded, not asserted to be the hosted failure. Need its exact command, source SHA and traceback before a focused source fix is justified.

Only changed file: `docs/testing/issue-1893-repair-155b51f0.md`, committed as an evidence handoff, not merge/activation approval. No ledger/grant edits, production activation, GitHub mutations or destructive git commands.

Progress: checked 1, done 0 repairs, skipped 0 items, errors/blockers 1. Next: integration owner resolves trusted-base authorization outside this lane and supplies the actual hosted test failure. Do not redispatch the unchanged state as another Vulture repair.
