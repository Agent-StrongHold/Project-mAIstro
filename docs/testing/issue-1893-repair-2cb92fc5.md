# Issue #1893 repair — job 2cb92fc5

## Frozen scope and starting evidence

- Single assigned item: #1893, branch `auto-1893`, worktree `/home/dev/Git/wt/auto-1893`.
- Verified starting HEAD: `89dc4b7dc8962e6a4f88506540ebb2282aa1484b`.
- Supplied comparison base: `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree clean; no incoming edits to salvage.
- Frozen inputs: supplied dispatch-context.json (issue body and associated evidence),
  job check-0.log through check-4.log, prior result c0d5ea2c, existing codec,
  identity types, adjacent tests, applicable ADRs and CI gate definitions.
- Planned output: this validation/handoff note. Production/test/ledger changes only
  if a concrete in-scope failure establishes a repair; no speculative changes.
- Role ambiguity resolved as writer: explicit lane says assigned repair and local
  commit required. No GitHub operations, activation, or ownership changes authorized.
- Driver evidence inspected: dependency sync, ruff check and formatting passed;
  focused tests reported 346 passed / 3 skipped; core inventory passed (16,567 nodes).
  These are driver results, not independently rerun acceptance evidence.
- Reported `test: failure` has no traceback in the supplied check logs. Prior
  reachability authorization blocker will be checked, not assumed resolved.

## Validation

- Independently executed `RATCHET_BASE_REV=ac7370141e8e61bd6f352bca35ed0b505104aadb uv run python scripts/check-ratchet-provenance.py`: **exit 1**. The supplied base resolves. Both admission modules are new unreachable modules without trusted-base authorization, and their dispositions likewise lack authorization. Log: `/tmp/1893-2cb92fc5-provenance.log`.
- Independently executed `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **exit 0**, 1322 findings match 1322 reviewed identities; zero unclassified/never-allowlist. No Vulture ledger amendment is warranted.
- Source review confirms admission_codec.py explicitly has no production consumer; admission_identity.py is an inactive contract leaf. Passing codec tests cannot establish runtime admission reachability.
- The reproduced blocker is reachability authorization, not the permitted Vulture repair. No grant, baseline, fake caller or activation change will be made to bypass it.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: passed, two source files.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`: **346 passed, 3 skipped** in 2.76s. All three skips are codec database variants (test_admission_codec.py:470), requiring MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL. This is not durability evidence.
- Read Accepted ADR-082526-7f02 (immutable admission provenance), ADR-082826-b601 (canonical execution consumer; no inferred eligibility), and ADR-083126-5e62 (trusted-base authority). No conflict warrants changing the canonical Goal -> Graph -> Run -> NodeRun -> Attempt model. Integration-gate requirements cannot override trusted-base authorization; a separately scoped consumer is not a permissible fake reachability repair.

- `uv run pytest packages/maistro-core/tests -x -q`: **exit 0**, 15494 passed, 1070 skipped, 3 xfailed, 55 warnings in 230.59s. Log: `/tmp/1893-2cb92fc5-core.log`. Warnings include worker-thread exceptions and an unawaited fake-process coroutine; passing tests do not establish their absence. The reported hosted `test: failure` did not reproduce in the changed package.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: passed, 16567 unique node IDs, zero duplicate identities/files.
- `uv run python scripts/check-shipped-surface-truth.py`: passed.
- `uv run python scripts/check-reachability.py`: passed against candidate ledger, 1403 production modules / 171 unreachable.
- `uv run python scripts/check-reachability-dispositions.py`: passed against candidate ledger, 50 groups classify 171 modules. These two passes do NOT supersede the failed trusted-base provenance check.
- `git diff --check`: passed.
- Production-source import search finds only the codec importing admission_identity and a Vulture whitelist import. Neither is an entry-point consumer; production reachability remains absent.
- Executed in-memory negative control with `uv run python`: wrap encode_admission_record to force output task_id to NULL, then invoke pytest for test_v2_round_trip_preserves_all_snapshot_bytes. Expected **2 failed, 1 passed, 128 deselected**; bound and acknowledged variants fail independently at test_admission_codec.py:134. Wrapper asserts pytest exit TESTS_FAILED. No production file was mutated.

No new tests or changed inventory counts in this round. No production or quality policy changes. Existing inventory notes need no count adjustment.

## Acceptance review

All executed commands above use the verified starting production source SHA;
this round changes only this report. Historical verification is not adopted.

| Criterion | Current evidence / limitation |
| --- | --- |
| Frozen/slotted header; exact shared interfaces and six decode codes | Source inspection at admission_codec.py:128-270 and focused passing tests. |
| Named scalar columns, strict UUID hex, signed timestamps, matching header, immutable DTO constructors and fresh flat encoding | Focused schema/scalar/identity/round-trip tests passed. Independent binding assertion detected the injected missing-task mutation. |
| Bound/unbound/partial legacy evidence without invented identity | Focused tests passed, including receipt-only, announced-without-Run, bound pair without explicit receipt, unreadable data, ignored completed_at. Missing receipt remains partial, not a fabricated identity. |
| Header survives malformed snapshots and partial bindings; unsupported format fails closed | Prospective named tests passed. No clock or incoming fingerprint is accepted by the codec. Expiry replacement and 409 ordering remain the separate C/F2 consumer's responsibility, not behavior proven by B2. |
| Strict TEXT JSON: duplicate keys, nonobjects, bare nonfinite, corrupt original evidence | Passing invalid JSON, nesting, numeric precision, Unicode and predecoded-value tests. Safe typed errors retain only validated scope and suppress unsafe parsing traceback chains. |
| Tagged snapshots and unchanged stored fingerprint | Passing tag and arbitrary nested evidence tests. Actual materialization with model_of/model_of_json into TaskResponse/Run and original-model fingerprinting are **UNVERIFIED** here: fixtures use mappings/manual tags, not a reachable admission caller. |
| SQL mapping including task_id/run_id and acknowledged_at; owner token hex only in storage | Pure round-trip tests pass and binding mutation fails. Production INSERT legality is **UNVERIFIED this round** without live migrated PostgreSQL. |
| Raw/production pool independence on a dedicated migrated PostgreSQL DB, real JSONB object Run payload, sessions and final row counts | **UNVERIFIED**: three required DB cases skipped because DSNs are unset. No database was created or modified and no session/row-count evidence is claimed. |
| Explicit authorized principals, Workspace/Project and registered Graph | **UNVERIFIED as production admission**: codec/type fixtures contain inert identities; they do not authorize or dispatch work. |
| No SQL/HTTP/queue/claim/assessment/scope-policy or execution-authority changes | Inspected pure DTO converter boundary; this round changes no production source. Canonical execution model and accepted ADRs remain intact. |
| Focused tests, lint, format, types and inventory | Passed as recorded above; no inventory delta. |
| Full integration CI and runtime reachability without unauthorized baseline/grant changes | **BLOCKED** by independently reproduced trusted-base provenance failure. Full hosted CI and the unattributed hosted test failure remain **UNVERIFIED**; local core suite passed. |
| Ownership/staging/activation constraints | Only assigned isolated writer lane used. No merge, push, GitHub mutation, activation or competing consumer authorized or performed. |

## Handoff

**BLOCKED**, not an implementation completion or integration approval. No actual
in-scope code defect or unbanked Vulture identity reproduced. The inherited
reachability rows/dispositions cannot authorize themselves; the permitted
Vulture-ledger exception does not authorize reachability policy edits.

Required next input is a protected-base reachability authorization or an
explicitly coordinated real consumer integration, plus the actual failing
hosted test node/log and source SHA. Neither can be fabricated in this lane.
Do not repeat a generic test repair without new evidence. Required live-DB and
production materialization acceptance remains open even after the policy blocker.

Progress: checked 1 issue, done 0 repairs, skipped 0 issues, errors 1 blocking
gate. This report is the sole changed file and will be committed locally;
inherited implementation and all prior work are preserved.
