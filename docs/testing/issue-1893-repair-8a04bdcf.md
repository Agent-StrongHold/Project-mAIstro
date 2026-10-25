# Issue #1893 repair handoff — job 8a04bdcf

## Frozen assignment and disposition

- Assigned worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
- Verified starting HEAD: `fa5cdcc0abc53a714edc18c29b08cec2aa3724bb`.
- Frozen develop base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`;
  both local `origin/develop` and the merge base resolve to this SHA.
- One item: reproduce the supplied `test: failure` and previously reported
  provenance blocker; review the existing admission codec, immutable identity
  types, adjacent tests, workflows and relevant ADRs. Initial tree was clean.
- Read the captured issue and linked PR descriptions in `dispatch-context.json`,
  the five driver check logs, and the supplied prior result. None of those
  check logs contains a failed test or traceback. Historical successes are not
  adopted as current evidence.

**BLOCKED; no code repair identified or claimed.** Fresh execution reproduces
four trusted-base authorization violations, not a Vulture discrepancy:

- `quality/reachability-baseline.json:131,147`: new unreachable modules
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
- `quality/reachability-dispositions.json:606-613`: their new dispositions
  lack already-landed authorization.
- `.github/workflows/vulture-ratchet.yml:77` requires the failing provenance
  gate before the Vulture scan. The permitted Vulture-ledger exception does
  not authorize reachability ledger/grant changes.

The scope assumption is that this writer assignment authorizes evidenced repair,
not production activation or an authorization change. No conflict or incoming
uncommitted work existed. No merge, fetch, GitHub mutation, source/test change,
ledger/grant edit, gate change or artificial runtime import was performed.
Only this handoff is added; test inventory does not change.

Read accepted ADRs 081226-a66b, 082526-7f02 and 082826-b601. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt spine, immutable admission provenance
and explicit consumer eligibility. The codec's typed partial disposition for a
legacy bound pair lacking receipt evidence reconciles the issue's “both ids is
bound” shorthand with its no-invention requirement and the shared binding
constructor. It must not fabricate a receipt. No new execution authority is a
permissible way to make this inactive leaf reachable.

## Executed validation

Commands ran at the starting HEAD with 1,200-second timeouts. Full logs and
collected focused node identities are under
`/home/dev/maistro/jobs/8a04bdcfa2f647b8a9ff4a539090701a/`.

| Command | Fresh outcome |
| --- | --- |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py` | **FAIL**, exit 1: two unauthorized unreachable modules and two unauthorized dispositions; `worker-provenance.log` |
| `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1,322 reviewed identities / 1,322 findings, zero unclassified; `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs --junitxml=/home/dev/maistro/jobs/8a04bdcfa2f647b8a9ff4a539090701a/worker-focused.xml` | PASS: 845 passed, 20 PostgreSQL-gated skips, 16.54s; `worker-focused.log` and `worker-focused.xml` |
| `uv run ruff check .` | PASS; `worker-ruff.log` |
| `uv run ruff format --check .` | PASS; `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files; `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16,567 nodes, no duplicate test evidence; `worker-inventory.log` |

The codec file accounts for 128 passes and three skips; the identity file for
73 passes. Pytest emitted three `record_property`/xunit2 warnings, not failures.
Both PostgreSQL DSNs were absent/empty. No database was provisioned in this
blocked round; no live durability, session identity or SQL row counts are claimed.
No pre-fix/mutation failure is claimed because no implementation was changed.

## Acceptance accounting

These are representation tests, not evidence of production admission. A source
import search finds no production caller of the codec; its only non-test
identity-module dependency is the codec itself, apart from the Vulture whitelist.
This agrees with `admission_codec.py:50-54` and the provenance failure.

| Issue criterion | Current evidence / limitation |
| --- | --- |
| Frozen/slotted header, exact shared interfaces, six decode codes, fresh flat encoding | Reviewed source plus codec/identity tests pass; production consumer UNVERIFIED/inactive |
| Named SQL fields, strict storage UUID `.hex`, signed timestamps, shared constructors and mismatched-header rejection | Scalar, schema, owner/generation, binding and header-mismatch tests pass |
| `test_v2_round_trip_preserves_all_snapshot_bytes` | Three states pass; independent assertions require the migration-055 task/run pair and matching receipt |
| `test_owner_token_is_hex_at_storage_only` | Pass; malformed representations rejected and token absent from record repr |
| `test_legacy_binding_unbound_and_partial_are_distinct` | Pass, plus receipt-only/missing-receipt/unreadable/whitespace evidence cases; no inferred identities |
| `test_expired_legacy_header_does_not_invent_missing_identity` | Pass; pure scalar evidence, not a clock-driven expiry decision |
| `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` | Pass; duplicate-key snapshot fails without losing the valid header |
| `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` | Pass; header fingerprint survives typed partial-binding failure |
| `test_unknown_format_cannot_be_reinterpreted_as_legacy` | All parameter cases pass, including attempts to supply a supported header |
| `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` | Pass at storage-text level; tests supply tags directly |
| `test_invalid_and_duplicate_json_is_rejected` | Pass, plus nonobject/nonfinite, deep nesting, lossy-number and invalid-surrogate cases; typed errors suppress unsafe parsing chains |
| Existing evidence-json serialization, `model_of`/`model_of_json`, arbitrary permitted program context and original-model fingerprinting | UNVERIFIED end-to-end: direct tagged fixtures do not establish model materialization or original-model fingerprinting |
| `test_raw_and_production_pool_codecs_read_identical_text_snapshots` | UNVERIFIED: all three states skipped; no migrated PostgreSQL proof this round |
| Bound TEXT parameters, real migrated schema, Run JSONB object rather than doubly encoded string | Flat TEXT mapping reviewed; real DB/Run insertion UNVERIFIED |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED by DTO fixtures; these are not positive production-admission tests |
| No SQL mutation, clock, classifier, live `_assess`, scope utility, HTTP/queue or legacy/deletion policy change | Reviewed codec and handoff-only change preserve the stage boundary |
| Inventory, focused tests, Ruff, format and applicable mypy | Passed as above; no test additions, so no inventory delta required |
| Full unchanged integration CI and runtime reachability | UNVERIFIED full CI; required provenance gate demonstrably FAILED |
| Replacement/409 precedence and transaction/crash/dispatch invariants | UNVERIFIED and explicitly reserved to consumer/integration leaves, not B2 |

## Next action

Checked: 1 issue; done: 0 repairs; skipped: 0 issues; errors: 1 required gate.
The supplied generic `test: failure` remains **UNRESOLVED**: scoped passes do
not establish that every CI test passes. Supply the actual failing step/node
and traceback before attempting a test repair.

The owner-controlled trusted-base prerequisite must change before another
identical repair round can resolve provenance. Any reviewed authorization must
land separately under the two-merge rule; this worker cannot grant or integrate
it. Then validate PostgreSQL and unchanged integration CI at the coordinated
head. Repeating unchanged scans, amending Vulture without a finding, or importing
an unused codec does not resolve this blocker. This is a locally committed
blocked handoff, not merge or activation approval.
