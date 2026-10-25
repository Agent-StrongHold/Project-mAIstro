# Issue #1893 repair validation — b3d0b5b5

## Frozen scope and initial evidence

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `3fc6350fa02516ab57854eb0f8cb0190970e910a`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial worktree clean; no incoming edits required salvage.
- Snapshot: supplied dispatch-context.json, prompt, check-0 through check-4,
  and prior result 8036b74c; no remote issue/PR enumeration or mutation.
- Production review scope: `tasks/admission_codec.py`,
  `runs/admission_identity.py`, adjacent identity/codec tests, existing evidence
  serializer and task admission caller, applicable ADRs/workflows/ratchets.
- Planned write scope: this report; production/test repairs only if an actual
  in-scope defect is reproduced. No reachability ledger/grant changes authorized.
- Supplied checks: sync, ruff check, formatting, focused tests (201 passed,
  3 skipped), suite inventory (16466) succeeded. These are driver evidence,
  not a claim of execution by this worker.
- Prior result reports trusted-base provenance failure and no assigned-head
  traceback for the generic `test: failure`. Assumption: reproduce the named
  checks first; do not invent a test failure or production activation to repair.

## Results

The dispatch base resolves and is the actual merge base with HEAD; no sync
conflict is present. Fresh exact CI Vulture scan PASS: 1323 reviewed identities,
zero unclassified. No Vulture ledger amendment is justified.

Fresh trusted-base provenance FAIL (exit 1): `maistro.runs.admission_identity`
and `maistro.tasks.admission_codec` are two unauthorized unreachable modules
and two unauthorized dispositions (169 trusted versus 171 candidate). Commands
and outputs are `worker-vulture.log` and `worker-provenance.log` in the job
directory. This is a real policy rejection, not a missing dependency.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Reconciliation:
keep immutable admission provenance and canonical execution authority; a
candidate ledger cannot approve itself. The Vulture-only repair exception
cannot authorize reachability grants. Production import search finds only the
codec importing the DTO and the Vulture whitelist importing an assessment type.
The codec is not a reachable admission consumer; activating one to appease the
gate would exceed this staged leaf's explicit constraints.

## Executed validation

All worker checks ran on the unchanged starting production source, with
1200-second subprocess timeouts. Exact command/output records are in the job
folder's `worker-*.log`; the validation batch also wrote `worker-checks.json`.

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -rs` | 204 nodes: 201 passed, 3 PostgreSQL skips, 1.40s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger; 171 unreachable modules |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger; 171 dispositioned modules |
| `uv run python scripts/check-promotion-surface.py` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 reviewed identities |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized modules plus two unauthorized dispositions |

## Acceptance evidence and limits

These are DTO-level results, not reachable admission behavior. The production
`PgTaskIdempotencyStore._read` still calls the old positional `_row_of`
(`tasks/idempotency.py:1180-1191`), not this codec. The existing assessor is
unchanged (`tasks/idempotency.py:391`). No production activation is authorized
by this issue.

| Criterion | Evidence |
| --- | --- |
| Frozen/slotted header; exact shared interfaces and six decode codes | Source inspection of `admission_codec.py:129-262`; header/schema/mismatch tests PASS. |
| Named columns, strict UUID .hex, signed timestamps, #1851 constructors | Codec source and strict UUID, scalar, record-window and owner-token tests PASS. |
| Fresh flat mapping, paired task/run binding, immutable snapshot bytes | Three state round trips plus fresh mapping test PASS; independent SQL binding assertions at `test_admission_codec.py:134-137` prevent symmetric encode/decode bugs being hidden. |
| Original fingerprint and permitted tagged program_context evidence | Tagged nonfinite and snapshot round-trip tests PASS; source copies fingerprint without recomputation. Tests do not materialize real TaskCreate/TaskResponse/Run models. |
| Strict TEXT JSON, no duplicate keys/nonobjects/bare nonfinite values | Invalid JSON tests PASS; direct stored-TEXT injections for nesting, lossy numbers and lone surrogates PASS. Valid Unicode and exact numbers also PASS. No new mutation/pre-fix experiment claimed. |
| Typed safe failures and validated scope hash | Error-scope, token hygiene and injected snapshot failures PASS; parsing exceptions suppress displayed context and causes. |
| Legacy both/neither/partial, receipt-only and announced-without-Run | Legacy tests PASS; no fabricated task, Run or receipt. Both IDs without receipt remain partial because #1851 AdmissionBinding requires a receipt; synthesizing one would violate the no-guessing contract. |
| Header/full-decode separation; malformed snapshot, partial binding, unsupported format | Named expiry/fingerprint preservation, header mismatch and unknown-format tests PASS. No clock or incoming fingerprint argument. Replacement/409 precedence is the future consumer's responsibility, not established by B2. |
| Existing evidence-json producer and model_of/model_of_json materialization | UNVERIFIED by the focused tests: they construct tag dictionaries rather than serialize/materialize actual request/receipt/Run models. Inspected existing `runs/evidence_json.py`; codec preserves tags without decoding them. |
| Same migrated disposable PostgreSQL DB, raw and production pools, non-null pg_pool | UNVERIFIED this round: all three cases skip at `test_admission_codec.py:470` because DSNs are absent. Did not provision a database after reproducing the independent policy blocker. No session identities or final SQL row counts claimed. |
| Run INSERT uses text-to-jsonb cast and stores an object | UNVERIFIED this round; codec is a mapping leaf, and admission-row tests do not insert a Run payload. |
| Real authorized principals, Workspace/Project, registered Graph kinds | UNVERIFIED: fixture identity strings are not authorization evidence. No canonical execution, authorization or admission authority changed. |
| No SQL mutation, HTTP/queue mapping, live assessor/scope change or new decision | Source review PASS for the staged codec. This round changes only this report, not production behavior. |
| Focused tests, lint/format, typing and truthful inventory | PASS as above. No tests added/removed, so no inventory-delta note required. |
| Unchanged required integration CI and runtime reachability | BLOCKED / UNVERIFIED: trusted-base provenance fails; full integration CI not run. Candidate-ledger checks are not authorization. |

## Reported `test: failure`

Inspected the four captured `test` check records in the frozen dispatch;
recorded them in `worker-captured-tests.json`. Only the unrelated captured head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` reports failure, with null summary/text.
None of those records names the assigned starting SHA. No assigned-head
traceback was supplied. **UNRESOLVED:** focused tests pass, but they do not prove
CI's `test` job: that job explicitly partitions core tests into a different
producer (`.github/workflows/ci.yml:574-612`). No speculative repair is justified.

## Handoff

Verdict: **BLOCKED**, not an implementation or integration approval.
Only changed file: `docs/testing/issue-1893-repair-b3d0b5b5.md`; locally commit
this evidence. No source, tests, ledgers, grants, whitelist or gates changed.
No GitHub mutation, fetch, merge or activation attempted. The starting base is
already the merge base; this is not a develop-sync conflict.

Next: independently authorized trusted-base reachability resolution or separately
authorized real consumer integration, then revalidate; obtain the assigned-head
failing step/node/traceback before another `test` repair. Do not dispatch the
same unchanged base as a Vulture-only repair: Vulture already passes and cannot
authorize the failed reachability ratchet.

Progress: checked 1, done 0, skipped 0, errors 1 (required provenance gate).
Residual risks: inactive codec, unexecuted PostgreSQL/materialization/authorized
admission acceptance and incomplete full-CI evidence. Existing work preserved.
