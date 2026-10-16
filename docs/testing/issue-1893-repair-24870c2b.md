# Issue #1893 repair — job 24870c2b

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `4b78950f7db6461efef1e78ddf7b569a6098aeba` (resolved).
- Assigned develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62` (resolved by diff).
- Working tree initially clean; no incoming changes to salvage.
- Inspect existing admission codec/identity implementation, their adjacent tests,
  applicable ADRs, CI definitions, and supplied dispatch evidence. Only this
  report and evidence-backed in-scope repairs may change; no new integration,
  policy, ownership, scheduler, or reachability authorization.
- No GitHub mutations or enumeration; supplied dispatch-context.json is the frozen evidence.

## Initial evidence / ambiguity

Driver `check-0.log` through `check-4.log` inspected: dependency resolution,
lint and formatting passed; tests reported 346 passed, 3 skipped; inventory
reported 16,567 core tests with no duplicate evidence. Skips are not storage proof.
The supplied `test: failure` label has no failing node or traceback in these
logs. Assumption: independently run focused tests and the named exact-debt
checks, rather than guessing a code change. Prior provenance blocker is a
claim to recheck, not a current result. No develop sync conflict exists at entry.

## Reproduced blocker

Fresh commands (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings, zero unclassified.
- `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add an unauthorized unreachable module and disposition (169 -> 171). Other provenance checks pass.

This is actual reachability debt, not missing Vulture identities. The Vulture
repair exception does not permit reachability baseline/grant changes. B2 also
forbids production activation, so neither fake caller wiring nor self-approval
is an authorized repair. The previous block remains reproduced. Finish focused
acceptance validation and commit a blocked handoff; do not start unrelated work.

## Focused validation

Executed at the starting Python source SHA, with a 1200-second timeout:

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -r s`: **346 passed, 3 skipped**, 349 nodes, 2.95 seconds. Three PostgreSQL cases skipped at `test_admission_codec.py:470` because both DSNs are not configured.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, two files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS, 16,567 nodes, no duplicate identities/files.

The prior result artifact was read but its live-PostgreSQL/mutation results are
not adopted as fresh evidence. An optional guessed historical note path
`docs/testing/issue-1893-repair-43909947.md` was not found; skipped without retry.

## Acceptance audit

| Criterion | Evidence at this head / limitation |
| --- | --- |
| Frozen/slotted header, exact interfaces and six typed decode codes | Inspected `admission_codec.py:132-270`; header schema/scalar/mismatch and unknown-format tests pass. No clock or incoming fingerprint argument. |
| V2 exact immutable DTO and fresh flat named-column mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` passes for unbound, bound and acknowledged; `test_encode_returns_a_fresh_flat_mapping` passes. |
| Storage-only UUID .hex, strict signed timestamps, #1851 validation | Owner-token, generation, invalid-scalar, lease, acknowledgement and identity tests pass. DTO receipt mismatch is rejected by `admission_identity.py:291-292`. |
| No inferred legacy identity; distinct bound/unbound/partial/receipt-only | Legacy binding, receipt-only, missing-receipt, unreadable and whitespace tests pass. A pair without receipt evidence remains partial: the prerequisite binding constructor requires a receipt and B2 may not fabricate it. `completed_at` grants no authority. |
| Header evidence survives snapshot/binding decode failures | Expired-legacy, preserved-expiry, preserved-fingerprint and scalar-inversion tests pass. This is not proof of C's expiry/replacement/409 decisions, which remain outside this leaf. |
| Unknown formats cannot fall through to legacy | Seven unsupported-format cases pass, including rejection with a hand-built supported header. |
| Duplicate keys/nonobjects/bare nonfinite/invalid TEXT rejected safely | Invalid JSON, deep nesting, precision-loss and Unicode cases pass; safe errors suppress parsing chains and retain only a validated scope hash. |
| Tagged nonfinite evidence and fingerprint unchanged | Tagged snapshot and round-trip tests pass; tags/fingerprint are supplied directly. Actual `evidence_json` serialization, `model_of`/`model_of_json` materialization and fingerprint generation from the original model remain **UNVERIFIED** by these tests. |
| Raw and production pools read identical TEXT on the same migrated disposable DB | **UNVERIFIED this round**: three skipped cases. No DB session identities, migration-chain execution, final SQL counts or durability proof claimed. |
| Run payload is a JSONB object; explicit authorized principals/Workspace/Project/registered Graph | **UNVERIFIED**: fixtures use identity strings and the codec has no admission consumer. A codec DTO round trip is not authorization or Run-insertion proof. |
| No SQL mutation/HTTP/queue/claim/assessment/scope-policy change | Codec inspected: mappings only. This repair changes only this report, not production behavior. Canonical execution hierarchy untouched. |
| Meaningful regression sensitivity | Independent task_id/run_id assertions at `test_admission_codec.py:134-137` pass. No fresh mutation experiment or pre-fix failure is claimed. |
| Inventory note and focused checks | Existing inventory folds successfully. No tests added/removed this round, so no inventory delta is necessary. |
| Reachable production behavior and unchanged full required integration CI | **NOT PROVEN**: provenance gate fails on both inactive modules; full hosted CI remains **UNVERIFIED**. No baseline/grant/gate modifications made. |
| Coordinated stage/owner and activation prerequisites | Assigned head respected. External coordination/activation decisions remain **UNVERIFIED**; no merge, rollout or closure authorized. |

## Architecture and unresolved CI label

Read repository AGENTS.md, docs/README.md, docs/quality-gates.md and accepted
ADRs 081226-a66b, 082526-7f02 and 083126-5e62. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`, immutable admission provenance,
Attempt-owned dispatch identity and trusted-base authorization. The Vulture
repair exception does not override reachability policy. An inactive B2 leaf
cannot be made independently merge-ready by inventing a production caller.

`.github/workflows/ci.yml:573-612` explicitly partitions core tests away from
the `test` job. Therefore the core pass above does not establish the reported
hosted `test: failure` is fixed. The supplied driver logs contain no failing
node/traceback; the prior result also reports this unresolved. No guessed
scanner finding, cosmetic source change, or unrelated test repair was made.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-24870c2b.md`.
Verdict: **BLOCKED**, not a completed repair or integration approval.

Next: provide the assigned-head hosted failing step/traceback; separately
coordinate a permitted trusted-base reachability resolution or real consumer
integration. Re-running unchanged inputs or amending the already-matching
Vulture ledger cannot resolve the reproduced reachability blocker. No fetch,
merge, remote mutation, ledger edit or production activation was performed.

Progress: checked 1 issue; done 0 repairs; skipped 0 issues; errors 1 required
gate. Residual risks are the inactive slice, unresolved hosted test failure,
and explicitly unverified acceptance rows above.
