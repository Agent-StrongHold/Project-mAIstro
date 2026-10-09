---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair d828 — checkpoint

Frozen scope: issue #1893 only, branch auto-1893, starting head
6ded18136a06d1b01223cc36c2daf9160d175e57, supplied base
2b897bc78b68ac900cb0432fb9dc29324d96aca8. Working tree initially clean.
Files under review: admission_codec.py, admission_identity.py, their two test
files, migration 055, existing B2 inventory notes, relevant ADRs and CI scripts.
Potential edits limited to the codec, its tests, this note, and (only if the
required scan demonstrates actual debt) quality/vulture-baseline.json.
No new runtime wiring, activation, or other ledger/grant changes authorized.

Dispatch ambiguity: issue requests coordinated staged work, while lane explicitly
assigns this existing branch. Proceed with local repair only, not activation or
integration approval. Prior findings may be stale and will be rechecked.

Driver logs inspected: check-0 dependency sync successful; check-1 ruff passed;
check-2 format passed (3231 files); check-3 201 passed / 3 skipped;
check-4 inventory matched 16095 core tests. These are driver evidence, not proof
of real PostgreSQL behavior. Existing unrelated branch changes are preserved.

Fresh checkpoint: required Vulture command exits 0. Provenance command with
RATCHET_BASE_REV=2b897bc78b68ac900cb0432fb9dc29324d96aca8 exits 1; its resolved
trusted merge base is 675db8be6c41. Both admission modules have unauthorized
NEW reachability and disposition entries (repair-provenance.log:20-29).
The reported encoder bug is already fixed at admission_codec.py:291; both
binding columns are checked independently in test_admission_codec.py:134-135.
Accepted ADR-081226-a66b preserves the canonical execution hierarchy;
ADR-083126-5e62 prohibits candidate evidence becoming its own authorization.
No source or Vulture ledger change is justified by these findings.

## Executed validation at the frozen source head

Raw logs and collected node IDs are in
`/home/dev/maistro/jobs/d8286d42ded94bee84f0c4f4070f178e/repair-*`.

- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: exit 0; 1323 reviewed
  identities / 1323 findings. No unbanked identity to amend.
- `RATCHET_BASE_REV=2b897bc78b68ac900cb0432fb9dc29324d96aca8 uv run python
  scripts/check-ratchet-provenance.py`: exit 1, as recorded above.
- `createdb maistro_1893_d828` and
  `DATABASE_URL=postgresql:///maistro_1893_d828 uv run alembic upgrade head`:
  exit 0. Fresh dedicated disposable native PostgreSQL DB, actual migration
  chain including 055 through 061; no stamping, recreation in SQLite, or
  downgrade. Database retained for inspection.
- With both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_d828`, and `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, zero skips**. The same paths with `--collect-only -q`
  collected 204 nodes (`repair-nodes.log`).
- Production/raw pool backend PID pairs were 3592483/3592484 (unbound),
  3592485/3592486 (bound), 3592487/3592488 (acknowledged), all on
  `maistro_1893_d828` via Unix socket. Tests require non-null `pg_pool` and
  compare database/server identities. Production fixture uses
  `_register_json_codecs`; raw pool does not. Each persisted exactly one scoped
  admission row. Final SQL: revision 061, zero admission rows, zero distinct
  generations, zero distinct bound Run IDs after test cleanup.
- An in-process mutation replaced the encoder's `task_id` with `None`, then
  invoked `pytest.main` on the codec file with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`:
  expected exit 1, **2 failed / 1 passed / 128 deselected**. Both bound states
  fail the independent SQL shape assertion at test line 134. No source files
  were mutated. This demonstrates sensitivity to the reported historical bug.
- `uv run ruff check .`, `uv run ruff format --check .`, and
  `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: exit 0.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: exit 0; no tests added/removed in this repair.
- `uv run python scripts/check-<name>.py` for `shipped-surface-truth`,
  `reachability`, `reachability-dispositions`, `promotion-surface`: exit 0.
  Candidate agreement does not authorize the trusted-base failure.
- Production-source import search finds only codec-to-identity and Vulture
  whitelist imports, consistent with the reachability gate: no production
  consumer exists. Exports and test callers are not runtime wiring.

## Acceptance audit

| Criterion | Executed evidence / limit |
| --- | --- |
| Exact immutable interfaces, header/row scalar agreement, fresh named flat mapping | Passing codec and adjacent identity tests; inspected frozen/slotted header and constructors. |
| v2 round trip preserving snapshot evidence | Named round-trip test passes in unbound, bound, acknowledged states; migrated PG confirms SQL shape; historical-bug mutation fails both bound cases. |
| Owner token hex only at storage | Named test passes, strict UUID tests and safe error/repr assertions pass. |
| Legacy bound, unbound and partial stay distinct | Named test plus receipt-only, absent receipt, one-sided pair and unreadable evidence tests pass. No receipt is invented for a legacy pair lacking receipt evidence. |
| Expired legacy header does not invent identity | Named test passes; codec has no clock/assessment decision. |
| Header expiry survives snapshot failure | Named separation test and malformed snapshot tests pass. |
| Header fingerprint survives partial binding | Named separation test passes; stored fingerprint is never recomputed. |
| Unknown format cannot become legacy | Named format tests pass, including forged supported headers. |
| Tagged nonfinite snapshots and arbitrary program_context | Synthetic tagged nan/inf/-inf round trips pass without fingerprint change. Actual evidence-json/model_of/model_of_json model materialization remains UNVERIFIED. |
| Reject invalid/duplicate/nonobject/bare nonfinite JSON, safe errors | Named tests plus precision, nesting and Unicode cases pass; suppressed exception chains asserted. |
| Raw/production pools read identical TEXT snapshots | Three real migrated PostgreSQL cases pass, each with distinct pool sessions on the same DB; escaped-surrogate corruption rejected through both pools. |
| Named SQL field mapping, binding constraints | Mapping matches migration 055, including physical `request` TEXT mapped to DTO `request_snapshot`; bound `task_id=receipt_id` independently asserted. |
| Representation only: no SQL mutation, HTTP/queue/claim/expiry policy changes | Codec source remains pure mapping/DTO translation; this repair changes only this evidence note. |
| Unchanged required CI / reachable production behavior | NOT proven: trusted-base provenance fails, modules lack production consumer. Hosted `test: failure` not reproduced by focused tests; full CI remains UNVERIFIED. |

Real authorized principal/Workspace/Project/registered-Graph admission, Run
`json_of` TEXT-to-JSONB object insertion, transaction/crash/dispatch invariants,
live replacement/409 precedence and migration downgrade/adoption remain
**UNVERIFIED** here. DTO fixtures and direct SQL inserts do not prove them;
this is representation validation, not production activation evidence.

## Handoff — BLOCKED

Only this note changed. Do not introduce a fake caller, new execution authority,
or candidate grant to turn the gate green. Integration ownership must resolve
real consumer wiring or separately landed trusted-base authorization under
existing governance. The Vulture exception cannot authorize reachability debt.
Obtain the hosted failing `test` traceback before assigning another source
repair; no local focused failure currently justifies one.

Progress: checked 1 issue; done 1 validation/handoff; skipped 0 issues;
errors 1 unresolved gate; next: integration owner resolves provenance and
provides failing hosted-test evidence. No push, merge, GitHub mutation,
activation, or quality ledger/grant modification. Local commit records the
handoff; it is not integration approval.
