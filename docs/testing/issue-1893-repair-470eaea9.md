# #1893 repair handoff — job 470eaea9

## Scope and decision

Checked only assigned issue #1893 in `auto-1893`, starting at clean
`52eeec19bbcff5657b54a2d67ac83c40ec7a8ea4`. The supplied base and local
`origin/develop` both resolve to `3c761d14db944a727fa0744444bc67cfe36d49f7`.
No merge conflict or uncommitted work was present. Frozen inspection scope:
admission codec, identity DTOs, adjacent tests, governing ADRs and relevant CI
checks. This report is the only edit; no code, tests, inventory counts, ledgers,
grants or gates changed. No GitHub mutations.

**BLOCKED**, not repaired. The reproduced failure is a reachability authorization
failure, not unbanked Vulture identities. The explicit Vulture-ledger exception
does not authorize reachability ledger edits. ADR-083126-5e62 preserves trusted
base authority; ADR-081226-a66b preserves Run/NodeRun/Attempt lifecycle ownership.
Adding a fake import or activating an unreviewed consumer would violate the
issue's staged, representation-only scope. No such workaround was attempted.

## Executed evidence

All commands below ran independently against the starting source with
1200-second command timeouts. Logs are `worker-*.log` in
`/home/dev/maistro/jobs/470eaea9e25e4e3f917445b39ea58683/`.
Driver `check-0.log` through `check-4.log` were also read; their passing results
are not substituted for the independent runs below.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed findings, zero unclassified. No ledger amendment justified. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: two unauthorized unreachable modules and two unauthorized dispositions, naming `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`. Other subgates pass. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped in 1.36s. PostgreSQL DSNs absent; no live DB proof. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: 2 files |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes; zero duplicate evidence |

The supplied dispatch JSON was inspected locally, without re-fetching. Its only
failed `test` check names dependency head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output title, summary and
text. It is not an assigned-head traceback. Extracted evidence is retained as
`worker-supplied-test-checks.json`. CI's `test` job excludes the core unit suite
(`.github/workflows/ci.yml:574` onward); focused codec passes do not prove that
job repaired. Full integration CI remains UNVERIFIED.

## Acceptance audit

Both implementation modules and both focused test files were read. A production
source reference search finds only the codec-to-DTO import and Vulture whitelist
import (`worker-references.log`). The trusted-base gate independently reports
both modules unreachable. No runtime admission behavior is proven by these DTO
tests.

| Criterion | Evidence and limits |
| --- | --- |
| Frozen/slotted header, required signatures and six typed failure codes | Source inspected; scalar, mismatch, unknown-format and constructor cases pass. |
| Named columns, signed timestamps, strict storage UUID `.hex`, #1851 constructors | Focused schema/UUID/range tests pass; encode returns a fresh flat mapping. |
| Safe decode errors with validated hash only | Invalid scope, malformed snapshot and owner-token cases pass, including suppressed parsing chains. |
| Immutable snapshots, unchanged fingerprint, arbitrary permitted evidence | Round-trip, nonfinite tags, Unicode and exact-number cases pass; fingerprints/tags are supplied fixtures, not production model serialization proof. |
| Strict TEXT JSON | Duplicate keys, nonobject roots, bare nonfinite values, lossy numbers, excessive nesting and lone-surrogate rejection cases pass with storage-text injection. |
| Legacy bound/unbound/partial/receipt-only evidence without invented identity | Focused cases pass. A pair without a receipt is partial because the DTO requires receipt identity; no-invention takes precedence over the issue's shorthand that both IDs are bound. |
| Header evidence survives full decode errors; unknown formats fail closed | Both named header-separation cases and unsupported-format cases pass. No clock, incoming fingerprint, assessment or claim API exists. |
| SQL mapping and acknowledgement | Independent encoder assertions check paired task_id/run_id and task_id=receipt_id; DTO receipt mismatch is rejected. completed_at grants no authority. Live constraint execution UNVERIFIED this round. |
| Original-model fingerprinting, evidence-json encoding and model_of/model_of_json materialization | UNVERIFIED: no production consumer; fixtures do not establish these integration behaviors. |
| Migrated disposable PostgreSQL, raw/production pools and session/row counts | UNVERIFIED: all three DB cases skipped at test_admission_codec.py:470 for absent DSNs. No session identities or final row counts claimed. |
| Run JSONB object INSERT, explicit authorized principals, Workspace/Project and registered Graph | UNVERIFIED: no runtime admission or Run INSERT executed. |
| No SQL mutation, HTTP/queue/scope/classifier or policy change | Source is mapping-to-DTO only; this round changes documentation only. Consumer expiry/replacement/409 behavior is outside B2 and UNVERIFIED. |
| Meaningful tests, inventory, pre-fix evidence | Existing tests inject malformed storage rather than mocked claims. Inventory passes unchanged. No new tests or mutation/pre-fix experiment; no inventory delta required. |
| Required CI, production reachability, coordinated activation | NOT established: provenance gate fails; no production consumer. Local lane ownership is not external stack coordination, merge approval or rollout authorization. |

## Required next action

The blocked identities remain in `quality/reachability-baseline.json:131,147`
and `quality/reachability-dispositions.json:612-613`, rejected by the mandatory
check at `.github/workflows/vulture-ratchet.yml:77`. An owner must arrange
separate trusted-base authorization or the properly scoped consumer integration;
this worker cannot self-authorize it. Obtain an assigned-head failing test step
and traceback before requesting another test repair. Repeating this unchanged
repair dispatch cannot resolve that authority boundary.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required gate.
Only this blocked handoff is committed. Residual risks: inactive runtime surface,
unverified live PostgreSQL and model/auth integration, and unverified full CI.
