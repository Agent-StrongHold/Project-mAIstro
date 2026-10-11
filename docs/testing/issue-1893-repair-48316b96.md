# Issue #1893 repair — 48316b96

## Frozen scope and checkpoint

Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`, starting
HEAD `6f902f9183a753431c691c225de83536f37393ea`, trusted dispatch base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
Only #1893 is processed. Scope: existing admission codec/identity and adjacent
tests, supplied logs/context, named CI gates; evidence-backed repairs only.
No fetch, merge, GitHub mutation, activation, or reachability-policy change.

The driver logs `check-0.log` through `check-4.log` were read, as were the
previous result and complete issue body in the frozen dispatch context.
These are prior evidence, not substitutes for fresh executions below.

Fresh Vulture execution passes (1323 findings / 1323 reviewed identities).
Fresh trusted-base provenance execution fails for both admission modules:
new unreachable modules and new dispositions are not authorized by the base.
No Vulture amendment is warranted; its limited repair exception does not permit
reachability grants, fake callers, exports, or gate weakening.

Read repository instructions and accepted ADR-081226-a66b, ADR-082526-7f02,
and ADR-083126-5e62. Preserve Goal → Graph → Run → NodeRun → Attempt,
immutable admission provenance, and protected-base quality authority.
An initially attempted ADR filename was not found; skipped in favor of the
resolved lifecycle ADR filename. No unresolved git ref was executed.

## Fresh validation

Commands ran with 1200-second timeouts against the starting source SHA.
Logs are in `/home/dev/maistro/jobs/48316b96c5424850825528ada0505ba5/`.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1323 identities; `worker-vulture.log` |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1; `worker-provenance.log` |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped in 1.42s; `worker-focused.log` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 source files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes, no duplicate evidence |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `rg -n 'admission_codec\|admission_identity' packages/*/src` | Only codec-to-identity import and Vulture whitelist import; no runtime consumer |

No tests or production files changed, so no inventory delta is needed. No new
mutation/pre-fix evidence is claimed. No database was provisioned after the
independent required gate failed. The three skipped tests require both
`MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL`; they are not durability proof.

## Acceptance audit

Source and both adjacent test files were read. Focused test success establishes
an inactive codec contract, not reachable admission behavior.

| Criterion | Evidence or limitation |
| --- | --- |
| Exact interfaces, frozen/slotted header, six error codes, #1851 DTO constructors | Source inspection; focused header/schema/DTO tests pass. |
| Named columns, UUID .hex only at storage, signed timestamps, fresh flat mapping | Owner-token, scalar, generation, round-trip and fresh-mapping tests pass. Binding SQL shape asserted independently at `test_admission_codec.py:134-138`. |
| Legacy bound/unbound/partial/receipt-only/announced-without-Run, no guessed identity | Focused legacy tests pass. Bound pairs without receipt evidence fail partial rather than fabricate the receipt required by #1851. |
| Header mismatch rejection, header/full-record separation, unknown formats fail closed | Mismatch, unknown-format, preserved expiry/fingerprint tests pass. Inclusive expiry and changed-request 409 remain C/F2 behavior, not B2 claims. |
| Strict TEXT snapshots, duplicate/nonobject/nonfinite rejection, safe errors | Focused JSON, recursion, precision, Unicode and suppressed-chain tests pass. |
| Preserve tagged program_context and stored fingerprint | Byte/tag round-trip tests pass; fixture tags and fingerprints are manually constructed (`test_admission_codec.py:43-63`). Actual evidence encoder → model_of/model_of_json materialization and original-model fingerprinting: UNVERIFIED. |
| Migrated PostgreSQL raw/production pools, TEXT durability, matching DB identity | UNVERIFIED this round: all three database cases skipped. No session or residual-row counts claimed. |
| Run JSONB object insertion; authorized explicit principals, Workspace/Project and registered Graph kinds | UNVERIFIED; codec fixtures and DTO construction prove none of these integration requirements. |
| No SQL mutation, HTTP mapping, queue, clock, assessment, scope or policy changes | Mapping-only codec inspection confirms boundary; no implementation changes this round. No competing execution or authorization authority introduced. |
| Focused pytest, lint, format, mypy, truthful inventory | Fresh commands above pass, except mandatory provenance. No inventory change. |
| Full unchanged integration CI and no baseline/grant/gate workaround | BLOCKED: provenance fails. Full integration CI UNVERIFIED; no workaround made. |
| Coordination, ownership/base agreement, activation prerequisites | UNVERIFIED externally; assigned snapshot is not integration/activation approval. |

## Failure attribution and handoff

The frozen dispatch has four captured `test` checks: failure at
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (null summary/text), success at
`5d835338f7fa45b62d6361c9f3eddc5faf14284a`,
`fcc8b437f209a35aa68a61d6f0a5387414938355`, and
`d0a03c8db5c49c4756a1dc231a7bdc31f731f105`. None is the assigned HEAD.
The generic `test: failure` remains UNRESOLVED without an assigned-head
step/node/traceback. CI's `test` job excludes core unit suites
(`.github/workflows/ci.yml:574-612`); focused success does not prove that job green.
Do not invent a source repair from an unrelated-head status label.

The reproduced required-gate blocker is
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`, enforced by
`.github/workflows/vulture-ratchet.yml:77`. Both modules lack trusted-base
reachability authorization. This cannot be repaired under a Vulture-only ledger
exception, and the issue forbids baseline/grant/gate changes to green an unwired
slice. No sync conflict exists; no fetch/merge or policy change was attempted.

Only changed file: this report, committed locally as a blocked handoff. Existing
work preserved. Next action requires an externally authorized integration/base
resolution consistent with the issue's constraints, plus actual assigned-head CI
failure evidence. Do not redispatch an unchanged repair expecting a different
provenance result.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 required gate.
Verdict: **BLOCKED**.
