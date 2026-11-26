# Issue 1893 repair — e3db92ae

## Frozen scope

- Single assigned item: #1893, branch `auto-1893`, starting HEAD
  `823dc533917861297b2406580f900546a9898ec1`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Working tree was clean. Preserve all existing implementation and prior notes.
- Inspect existing admission codec/identity modules, their tests, repository
  instructions, relevant ADRs and CI workflows. Only repair reproduced failures
  in this slice; no activation, integration, GitHub mutation or reachability
  ledger/grant edits. Vulture ledger amendment only if the prescribed scan
  identifies reviewed retained identities.
- Potential edit files frozen to the two admission modules, their two test files,
  `quality/vulture-baseline.json` (explicit exception only), this report and
  `docs/testing/inventory-notes/atomic-admission-b2-e3db92ae.md` if tests change.
- Dispatch context is the supplied local snapshot; no remote re-enumeration.

## Initial evidence and assumptions

The driver logs `check-0.log` through `check-4.log` report dependency sync,
ruff check/format passing, 346 tests passing with 3 skipped, and suite inventory
16567 passing. Those are driver results, not new worker executions. The generic
`test: failure` has no failing node in these logs. Reproduce focused validation
before considering a code change. The prior reachability provenance block is
not assumed resolved: validate it without changing its ledgers or inventing
runtime callers. Explicit lane ownership is used for this local repair only;
production activation and parent closeout remain outside scope.

## Worker results

Fresh worker checks at the starting HEAD (logs in the supplied job directory):

- `uv sync --locked --extra dev`: PASS.
- `git rev-parse --verify` confirmed supplied base and `origin/develop` both
  resolve to `ac7370141e8e61bd6f352bca35ed0b505104aadb`; merge base is identical.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`:
  FAIL (exit 1). `worker-provenance.log` names two unauthorized unreachable
  modules (`maistro.runs.admission_identity`, `maistro.tasks.admission_codec`)
  and their two unauthorized dispositions. This is a trusted-base blocker,
  not missing dependencies or an unbanked Vulture identity.
- `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  PASS, 1322 reviewed identities / 1322 findings, zero unclassified
  (`worker-vulture.log`). No Vulture ledger amendment is warranted.

Provenance is BLOCKED under current scope. Do not rerun unchanged scans or
amend reachability grants/ledgers. Continue only focused acceptance accounting
and commit this handoff; no guessed code repair.

Further executed validation (1200-second timeout):

| Command | Outcome / job artifact |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs --junitxml=/home/dev/maistro/jobs/e3db92aebccd451d9c706e3bcc234354/worker-focused.xml` | PASS: 845 passed, 20 skipped, 3 warnings, 16.48s; `worker-focused.log`, `worker-focused.xml` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS; `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS; `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; `worker-inventory.log` |

PostgreSQL environment was not configured; all three codec DB contrast states
skipped. These skips are NOT durability proof. Warnings concern pytest
`record_property` with xunit2. No source or tests changed, no mutation/pre-fix
failure is claimed, and no inventory delta is necessary.

## Acceptance accounting and architecture

Read repository `AGENTS.md`, documentation authority map, and accepted ADRs
081226-a66b (Run/NodeRun/Attempt lifecycle), 082526-7f02 (immutable admission
provenance), and 082826-b601 (explicit canonical consumer eligibility). Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing execution authority
or authorization route is introduced. The issue's legacy “both IDs is bound”
shorthand is reconciled with the no-invention rule and shared constructor:
a pair without receipt evidence yields typed partial binding, not a fabricated
receipt. That is covered by the existing missing-receipt test.

Source search under `packages/**/src/**/*.py` finds only the codec importing
identity types and the Vulture whitelist importing an identity alias. It finds
no production codec caller. The source explicitly describes the inactive stage
at `packages/maistro-core/src/maistro/tasks/admission_codec.py:50-54`. Unit tests
are not runtime reachability or positive authorized admission evidence.

All test names below refer to the executed codec file; focused JUnit records
its collected cases. No earlier run is adopted as current proof.

| Criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header, shared signatures and six typed decode codes | Source review and codec/identity tests pass; no production consumer |
| Exact snapshots and fresh flat SQL mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound/bound/acknowledged; independent assertions at test lines 134-137 check migration-055 task/run shape; fresh-mapping and invalid-input tests pass |
| Storage UUID `.hex`, owner-token hygiene | `test_owner_token_is_hex_at_storage_only` and strict generation tests pass |
| Legacy bound/unbound/partial distinction without invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only, missing-receipt, unreadable and whitespace evidence tests pass |
| Expired legacy scalar evidence without clock/assessment | `test_expired_legacy_header_does_not_invent_missing_identity` passes; this is not expiry-policy execution |
| Header expiry survives bad snapshot | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` passes |
| Header fingerprint survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` passes |
| Unknown formats fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` parameter cases pass |
| Tags preserved without fingerprint recalculation | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` passes at TEXT level; fixtures directly supply tags |
| Strict JSON, safe typed errors and validated error scope | `test_invalid_and_duplicate_json_is_rejected`, excessive nesting, lossy numbers, invalid UTF-8, and scope-key tests pass |
| Named columns, signed timestamps, shared constructors, header/row agreement | Scalar/header mismatch, missing columns, identity, binding, acknowledgement and lease tests pass; source uses named mapping fields |
| Existing evidence serializer, model materialization and original-model fingerprinting | UNVERIFIED end-to-end; direct tagged fixtures do not prove `model_of`/`model_of_json` or original-model fingerprinting |
| Raw/production PostgreSQL pools read identical TEXT snapshots | UNVERIFIED: all three `test_raw_and_production_pool_codecs_read_identical_text_snapshots` states skipped at line 470; no DB provisioned, session IDs or SQL row counts claimed |
| Real migration chain, bound TEXT parameters and Run JSONB object | Flat TEXT mapping proven in unit tests; migrated DB/Run INSERT behavior UNVERIFIED |
| Authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED by DTO fixtures; no live positive admission exercised |
| No SQL mutation, HTTP/queue mapping, clock/classifier, live `_assess`, scope utility or deletion policy change | Codec source respects representation-only stage; this round changes only this report |
| Focused pytest, Ruff, format, mypy and inventory | PASS as recorded; inventory 16567, zero duplicate evidence; no test additions |
| Full unchanged integration CI, reachability/disposition/promotion gates | Full CI UNVERIFIED; required provenance gate FAILED; its promotion component passed, but that cannot waive the two reachability failures |
| Replacement/409, transaction/crash/dispatch invariants | UNVERIFIED and reserved to later consumer/integration leaves, not claimed by B2 |

## Final disposition and next action

**BLOCKED.** Existing branch rows at `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:606-613` are not authorized by the
trusted base. `.github/workflows/vulture-ratchet.yml:77` requires the failed
provenance gate. The narrow Vulture-ledger exception cannot resolve this.
No reachability ledger/grant changes, fake runtime imports, source/test changes,
fetch/merge, GitHub mutations or activation were performed.

The generic `test: failure` is **UNRESOLVED**: supplied check logs and current
scoped tests provide no failing test node. Request the actual CI traceback
before attempting a test repair. Owner-controlled trusted-base coordination is
also required: an approved reachability authorization would need to land
separately under the two-merge rule, followed by coordinated integration and
fresh CI/DB validation. This worker cannot grant or integrate it.

Only changed file this round: `docs/testing/issue-1893-repair-e3db92ae.md`.
Checked: 1 issue; done: 0 repairs; skipped: 0 issues; errors: 1 required gate.
This locally committed blocked handoff is not integration approval. Repeating
this unchanged repair input cannot resolve the trusted-base prerequisite.
