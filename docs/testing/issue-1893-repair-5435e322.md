# Issue #1893 repair handoff — job 5435e322

## Scope and decision

Only assigned issue #1893, branch `auto-1893`, worktree
`/home/dev/Git/wt/auto-1893`. Verified starting source SHA:
`d0d50a1f496dda54e7948bfbd7a325e7161b800c`. Verified supplied base and local
`origin/develop`: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial working tree was clean; no incoming work needed salvage.

Read repository instructions, supplied dispatch evidence and check-0.log through
check-4.log, prior result 24103494, both admission modules and adjacent tests.
Read accepted ADR-081226-69ee (canonical execution), ADR-082526-7f02 (immutable
admission provenance), and ADR-083126-5e62 (trusted-base quality authority).
No competing execution authority, activation, authorization or policy change is
permitted by this repair. B2's inactive stage does not override trusted-base gates.

**BLOCKED: no safe in-scope repair established.** Fresh provenance execution
rejects both admission modules as new unreachable modules without trusted-base
authorization, and rejects both corresponding dispositions. Candidate accounting
passes do not authorize them. The Vulture gate passes with zero unclassified
identities; its special ledger-edit permission does not resolve reachability.
No code, tests, ledgers, grants or gates were edited. Only this handoff is added;
there is no test inventory delta. This commit is evidence, not a repair or merge
approval. No GitHub mutations or destructive Git operations were performed.

## Executed validation

Commands below ran independently in this job with 1200-second timeouts, against
the starting source SHA. Driver logs were also inspected, not treated as proof
of missing acceptance. No full-tree pytest run or database provisioning was
started after the reproduced governance blocker.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 findings, zero unclassified |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL: two unauthorized unreachable modules and two unauthorized dispositions; trusted 169 versus candidate 171 |
| `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs` | 204 nodes: 201 passed, 3 skipped in 1.43s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/runs/admission_identity.py packages/maistro-core/src/maistro/tasks/admission_codec.py` | PASS: 2 files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-reachability.py` | PASS candidate accounting: 171 unreachable / 1396 production modules |
| `uv run python scripts/check-reachability-dispositions.py` | PASS candidate accounting: 50 groups / 171 modules |
| `uv run python scripts/check-promotion-surface.py` | PASS: 74 tolerated modules |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

The required workflow invokes provenance at
`.github/workflows/vulture-ratchet.yml:77`. Its actual failures name
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
The disposition additions are at `quality/reachability-dispositions.json:606-613`.
Production-source import search finds only codec-to-identity and Vulture whitelist
imports; the live PostgreSQL reader still uses `_row_of` at
`packages/maistro-core/src/maistro/tasks/idempotency.py:1190`.
Test imports and whitelist imports are not production reachability.

## Acceptance review

These are contract-level results, not reachable production admission proof.
All test evidence below is from the focused execution above.

| Criterion | Evidence or limitation |
| --- | --- |
| Exact shared interfaces; frozen/slotted header; six typed decode codes | Source inspected at `admission_codec.py:127-254`; schema, format, scalar and mismatch tests PASS. |
| Named storage columns; strict UUID .hex; signed timestamps; #1851 constructors | Owner-token/generation/scalar tests PASS; encoder source maps physical `request` and `claim_token` columns. |
| Fresh flat mapping; immutable v2 round trips in all three binding states | Unit tests PASS; independent task_id/receipt_id/run_id storage-shape assertions at `test_admission_codec.py:134-137`. Real SQL CHECK proof UNVERIFIED this round. |
| No inferred legacy identity; bound/unresolved/partial/receipt-only distinction | Unit tests PASS; missing receipt on a bound pair yields typed partial evidence rather than fabricating the receipt required by the DTO. completed_at is not authority. |
| Header survives malformed snapshots and partial binding; unknown formats fail closed | Named prospective header and format tests PASS. Inclusive expiry and 409 precedence belong to consumer C, not this codec; production behavior UNVERIFIED. |
| Strict JSON duplicates/nonobjects/bare nonfinite rejection | Unit tests PASS, including nested duplicate tests in the identity suite and boundary injections for excessive nesting, lossy decimals and invalid Unicode with positive controls. |
| Safe errors; validated scope only; no unsafe displayed exception chain | Error tests PASS and raisers inspected: typed code, validated scope, suppressed context, no raw snapshot/owner in messages. |
| Tagged snapshots and unchanged fingerprint | Hand-built tagged snapshot round trips PASS. Evidence-json producer plus model_of/model_of_json materialization and arbitrary permitted model-domain evidence are UNVERIFIED; fixed tagged fixtures do not prove those integrations. |
| Raw and production-codec pools, migrated disposable DB, both DSNs same DB, required pg_pool | UNVERIFIED: all three nodes skip at `test_admission_codec.py:470` because both PostgreSQL DSNs are not configured. No session identities or final SQL row counts claimed. |
| JSONB Run payload remains an object; explicit principals, authorized Workspace/Project, valid Graph kinds | UNVERIFIED: codec fixtures do not execute Run insertion or authorized admission. |
| No SQL mutation, HTTP/queue/scope utility/live assessor/new decision or clock | Source inspection confirms pure codec; this repair changes documentation only. Production use remains absent, deliberately not fabricated to satisfy reachability. |
| Focused pytest, lint, format, applicable mypy, inventory | PASS above. No new tests or mutation experiment in this round; no claim of pre-fix failure. |
| Unchanged integration gates; no candidate baseline/grant/gate bypass | Provenance FAILS. Other named gates pass as above; full required CI remains UNVERIFIED. Existing unauthorized accounting is preserved, not blessed. |

## Failure attribution and next input

The frozen dispatch check-run records were inspected locally, without refetching.
Their only failing `test` check names #1855 head
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, not the assigned head.
For #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355`, `test` succeeds
and `exact-debt-ledger` fails; output summary/text are null.
**UNRESOLVED:** no assigned-head failed node or traceback supplied. Assumption:
do not change unrelated behavior to repair an unattributed label.

No sync conflict was observed; the local develop ref equals the supplied base.
Do not repeat an identical repair dispatch on this unchanged source/base expecting
a Vulture amendment to fix it. Required next input is a separately reviewed
trusted-base resolution of the reachability authorization blocker (or authorized
real consumer integration), and assigned-head CI failure evidence if `test`
remains reported failed. This worker cannot land that authorization, activate B2,
or mutate GitHub. Live DB/model/authorization acceptance and full integration CI
remain residual risks, not implied passes.

Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker); next:
external trusted-base resolution and attributable failed-test evidence.
