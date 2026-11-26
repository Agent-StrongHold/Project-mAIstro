# Issue #1893 repair checkpoint — job 6f300fab

## Frozen scope

Single assigned item: #1893, branch `auto-1893`, starting HEAD
`6a8f43715b6fb6d06ca68ebc4460f8b342578b54`, dispatch base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
Inputs: supplied dispatch-context.json, check-0.log through check-4.log,
and prior result e29fb517 (if present). No GitHub mutation or new issue/PR
enumeration. Relevant code: admission_codec.py, admission_identity.py,
their tests, production admission consumer and evidence JSON helpers;
relevant gates: vulture baseline, ratchet provenance, ruff, format, mypy,
focused pytest. Documentation output is this file; no test additions planned.

Ambiguity: the dispatch names generic CI `test: failure` without a failing
node. Treat as unlocalized until logs or a fresh execution identifies it;
do not invent a code repair. The existing reachability ledger changes are
preserved, not authorized by this round's vulture-only exception. Activation
is forbidden by the issue; do not wire a runtime consumer to appease a gate.

## Progress

- Confirmed exact starting HEAD and clean worktree.
- Read full issue body from the supplied snapshot. No evidence yet justifies
  changing production behavior, tests, or ledgers in this round.
- Supplied check logs: dependency sync, ruff, format and suite inventory pass;
  focused pytest reports 346 passed, 3 skipped. Prior result is BLOCKED, not
  evidence of acceptance; this round independently reproduced the blocker.
- Executed `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 findings,
  zero unclassified/forbidden identities. No vulture ledger repair warranted.
- Resolved `origin/develop` and merge base to the frozen dispatch base.
  Executed `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb
  uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), two new
  unauthorized unreachable modules and two unauthorized dispositions for
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`.
  This is the exact-debt-ledger prerequisite, not a vulture identity failure.
  No merge conflict exists and no fetch/sync can be justified from that failure.
- Read accepted ADR-081226-a66b and ADR-082526-7f02, repository instructions,
  quality-gate policy, complete codec/identity source and codec tests, plus
  live `_assess` and evidence-json helpers. Reconciliation: admission provenance
  is immutable history, not a second execution authority; preserve
  `Goal -> Graph -> Run -> NodeRun -> Attempt`. B2 prohibits activation, so
  an artificial runtime consumer is not an acceptable reachability repair.
- Executed `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **346 passed, 3 skipped**, 349 collected nodes, 2.71 seconds. All skips
  are the database cases at `test_admission_codec.py:470`: both DSNs absent.
- Executed `uv run ruff check .`: PASS; `uv run ruff format --check .`:
  PASS (3301 files); `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
  Validation tool timeouts were 600/1200 seconds, not short probes.
- Executed `rg -n 'admission_codec|decode_admission_record' packages/*/src`:
  only the codec's own export and definition. The live consumer remains
  `tasks/idempotency.py:391`, not this staged codec. Direct test imports and
  passing candidate-ledger scans do not establish production reachability.

## Acceptance assessment at the exact starting source SHA

| Criterion | Fresh evidence / limit |
| --- | --- |
| Shared immutable header/record interfaces, named fields, flat fresh mapping | Codec/identity tests pass; inspected frozen/slotted header, row/header comparison, encode mapping and constructor calls. |
| Strict UUID hex, signed timestamps, typed failures, validated scope and safe displayed exception chain | Executed owner-token, generation, invalid-header, schema, scope and snapshot error tests. No raw snapshot/token is included in codec messages; parse failures suppress displayed chains. |
| Bound/unbound/partial legacy and receipt-only dispositions, no invented identity | Executed legacy binding, receipt-only, bound-without-receipt, whitespace and completed_at tests. Missing receipt evidence remains partial rather than fabricated. |
| Header preserves expiry/fingerprint despite invalid full record; unknown formats fail closed | Executed all four named prospective header/format tests. These test stored evidence only, not a consumer decision. |
| v2 canonical snapshot bytes and binding SQL shape | Executed unbound/bound/acknowledged round-trip cases, independently asserting task_id = receipt_id with run_id. This is not live CHECK-constraint proof. |
| Tagged nonfinite evidence and unchanged fingerprint; invalid/duplicate/nonobject/bare nonfinite JSON rejected | Executed named tagged and invalid JSON tests plus numeric-loss, nesting and Unicode cases. Fixtures use handcrafted tags and fixed fingerprints: original-model fingerprint computation and model materialization are UNVERIFIED. |
| No clock, incoming fingerprint, claim/SQL/HTTP/queue change; no alternate execution authority | Complete codec inspection: mapping-to-DTO boundary only. No source changes this round, no activation. |
| Both pool codecs on same migrated disposable PostgreSQL DB, non-null pool, session identities and final row counts | UNVERIFIED: three tests skipped. No disposable DB provisioning, migration, SQL or durability claim in this round. |
| Production evidence-json/model_of materialization, arbitrary program_context and Run JSONB object shape | UNVERIFIED end to end. Helpers inspected; the inactive codec does not create or materialize Run payloads. |
| Real authorized principals, Workspace/Project and registered Graph; consumer expiry/409 precedence | UNVERIFIED; DTO fixtures are not authorization/admission evidence. Consumer ordering belongs to C/F2, not activation in B2. |
| Full integration CI, runtime reachability, trusted-base governance | UNVERIFIED full CI; provenance FAIL executed above; no production codec caller found. |
| Inventory and source regression proof | No test/source changes, so no inventory delta or new mutation claim. Driver suite inventory reports 16567 nodes; not independently rerun. |
| Coordinated ownership/staging and activation policy | Dispatch assigns this repair worktree only. Independent integration/activation approval remains UNVERIFIED and is not granted by this report. |

## Disposition and handoff

**BLOCKED.** The `test: failure` ambiguity is UNRESOLVED: supplied passing
check logs and the fresh focused run provide no failing node or traceback.
Do not guess a source or ledger edit. The vulture-only exception does not
permit candidate approval of the four reachability violations. No fetch or
merge was attempted; local develop equals the frozen dispatch base and no
conflict exists. No GitHub mutation, gate weakening, grant edit, source/test
change, or new execution authority was performed.

Changed file this round: this report only. It is committed locally as an
evidence checkpoint, not a repair success or integration approval.
Next: integration owner must resolve the trusted-base reachability prerequisite
through the established authorized process and supply the exact failed CI
SHA/step/node/traceback before another source-repair dispatch. Do not repeat
this task on identical inputs. Real PostgreSQL and complete integration
acceptance remain outstanding.

Progress: checked 1 item; done 0 repairs; skipped 0 items; errors 1 reproduced
gate blocker. Existing implementation and all prior work were preserved.
