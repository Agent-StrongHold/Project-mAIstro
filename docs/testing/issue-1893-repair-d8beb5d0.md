# Issue #1893 repair checkpoint — d8beb5d0

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `104cfec9be47c801e1880d205e721d33640bc171` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item: #1893 immutable admission codec CI repair. No other issue or PR processing.
- Inspection scope: supplied dispatch snapshot/check logs, repository instructions and relevant ADRs, admission codec/identity modules and adjacent tests, CI gate definitions and existing admission validation notes.
- Potential edit scope: this report; codec/identity and adjacent tests only if reproduced defects require repair (with inventory note); vulture ledger only for reproduced reviewed retained identities under the explicit lane exception.
- Initial worktree clean; no uncommitted salvage needed.
- Ambiguity: `test: failure` has no test traceback in the lane text. Inspect captured evidence and run focused tests; do not guess a repair.
- Existing reachability ledger changes are preserved. The vulture exception does not authorize reachability grants, gate weakening or production activation.

## Progress

Driver check-0 through check-4 logs inspected: dependency sync, Ruff and inventory pass; focused tests show 201 passed / 3 skipped. These are not PostgreSQL durability evidence.

Fresh executions at the supplied HEAD:
- Exact requested Vulture command: exit 0, 1323 reviewed identities / findings, zero unclassified (`/tmp/1893-d8-vulture.log`). No ledger amendment is justified.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: exit 1 (`/tmp/1893-d8-provenance.log`). Both admission modules are unauthorized new unreachable modules and new dispositions. Base commit resolved before execution.

Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62. Reconciliation: preserve canonical execution and immutable admission provenance; candidate ledger edits cannot supply protected-base authority. The Vulture-only exception cannot repair the reachability failure. No sync conflict exists. Production activation is expressly excluded by #1893.

Source/test inspection confirms a staged mapping codec, not a production admission consumer. No source defect or permissible code repair is established.

## Fresh validation

Commands below ran against unchanged source at `104cfec9be47c801e1880d205e721d33640bc171`, with 1200-second validation timeout. Logs: `/tmp/1893-d8-<name>.log`.

| Command | Result | Log name |
| --- | --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 PostgreSQL cases skipped (DSNs absent) | focused |
| `uv run ruff check .` | Pass | ruff |
| `uv run ruff format --check .` | Pass, 3277 files | format |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Pass, two source files | mypy |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Pass, 16466 nodes, zero duplicate evidence | inventory |
| `uv run python scripts/check-shipped-surface-truth.py` | Pass | shipped |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Pass, 1323 reviewed identities | vulture |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, unauthorized reachability and dispositions for two modules | provenance |
| `rg -n 'admission_codec|admission_identity' packages/*/src` | Only codec-to-DTO import and whitelist import; no production consumer | callers |
| `git diff --check` | Pass | terminal |

## Acceptance audit

| Criterion | Evidence / limitation |
| --- | --- |
| Exact shared interfaces, frozen/slotted header, #1851 immutable DTOs, six error codes | Source inspected; passing header/schema, immutability and constructor tests. |
| Named columns, fresh flat SQL mapping, strict storage UUID .hex, signed timestamps | Passing mapping, token/generation format, scalar validation and independent binding assertions. Physical `request` TEXT maps to DTO `request_snapshot`; no SELECT ordering dependency. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run | Passing state tests, no invented identity. Canonical #1851 binding requires receipt evidence: a bound pair without it is partial rather than fabricated. |
| Header/full-decode separation, header mismatch, unknown format fail-closed | Passing expiry/fingerprint preservation and mismatch tests. No clock or incoming fingerprint; replacement/409 precedence remains C/F2 and is UNVERIFIED here. |
| Strict TEXT JSON and safe typed failures | Passing duplicate/nonobject/bare nonfinite, lossy number, deep nesting, surrogate and redaction tests. Parsing context suppressed. |
| Preserve snapshot evidence and stored fingerprint | Passing canonical text, tagged nonfinite, Unicode and exact-number tests. Original-model fingerprinting, real evidence encoder and model_of/model_of_json materialization are UNVERIFIED: fixtures hand-build tags. |
| Real migrated PostgreSQL raw/production pool contrast | UNVERIFIED this round: 3 skips at test_admission_codec.py:470. No DB provisioned after the independent blocker was reproduced; no session or final SQL count claims. |
| Run payload is a JSONB object, not double-encoded | UNVERIFIED; focused tests do not persist a Run. |
| Explicit authorized principals/Workspace/Project and registered Graph kinds | UNVERIFIED; fixture strings prove representation, not authorization. |
| No SQL mutation/HTTP/queue/assessment/scope/policy changes or new authority | Entire codec inspected; mapping-only module, no runtime consumer. This round changes only this report and preserves Goal → Graph → Run → NodeRun → Attempt. |
| Truthful inventory and focused checks | Fresh results above; no tests added or changed, so no inventory-delta note required. No new mutation/pre-fix proof claimed. |
| Unchanged required integration CI and no grant/gate bypass | BLOCKED by required provenance gate; full integration CI UNVERIFIED. Existing candidate ledger changes preserved, not approved. |
| Coordinated staged implementation versus activation | Assigned base/branch retained. Integration coordination and activation remain UNVERIFIED/BLOCKED; repair authority is not rollout approval. |

## Failure attribution and handoff

Read the supplied prior result as historical evidence only. Extracted all four captured `test` check records from the frozen dispatch into `/tmp/1893-d8-captured-tests.json`. The only captured failure is at `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`; its summary/text are null. The other three captured heads report success. None is this assigned HEAD. The generic `test: failure` is therefore UNRESOLVED without a current-head failing step/node/traceback. `.github/workflows/ci.yml:574-612` also shows that CI's `test` job excludes this core suite and runs other packages/root tests; a focused pass cannot stand in for it.

The reproduced required blocker remains `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`, enforced by `.github/workflows/vulture-ratchet.yml:77-85`. A Vulture ledger amendment would not address it. No baseline, grant, gate, whitelist, test or source changes made. No fetch/merge was needed: no conflict existed, and no new authorized base was supplied.

Only changed file: `docs/testing/issue-1893-repair-d8beb5d0.md`. Commit this handoff locally; it is not a code repair or integration approval.

**BLOCKED.** Next: separately landed trusted-base authorization and authorized base synchronization, or separately authorized real consumer integration; also supply the assigned-head failing CI traceback. Repeating unchanged-source repair rounds cannot resolve either missing input.

Progress: checked 1, done 0 repairs, skipped 0 issues, errors 1 required provenance gate; next: external prerequisite and current-head failure evidence.
