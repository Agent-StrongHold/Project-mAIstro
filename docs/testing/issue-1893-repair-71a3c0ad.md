# Issue #1893 repair checkpoint — job 71a3c0ad

## Frozen scope

- Issue: #1893 only; assigned branch `auto-1893`.
- Starting HEAD: `949e4f7569bcb938fcaf4e532b2b34a876748a1e`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect existing admission codec, admission identity constructors, their two test
  files, applicable ADRs/workflows, supplied dispatch evidence/check logs, and
  existing reachability provenance blocker. No other issues or PRs will be worked.
- Initial worktree clean; no incoming diff to salvage.
- Only this report is planned for modification unless validation identifies a
  permitted, concrete implementation defect. No tests or inventory counts changed.

## Ambiguities and constraints

The dispatch reports `test: failure` without a failing test node. Treat it as an
unlocalized failure, not permission to guess a repair. The issue expressly forbids
production activation and baseline/grant changes to make an unwired slice green.
Only the vulture identity ledger has a repair exception. Reachability grants and
production integration therefore remain outside this repair's authority.

## Reproduced blocker

Fresh execution of the requested Vulture command passed: 1323 reviewed identities,
1323 findings, zero unclassified. No vulture ledger amendment is justified.

`RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`
exited 1. Both `maistro.runs.admission_identity` and
`maistro.tasks.admission_codec` have unauthorized new unreachable-module and
new disposition entries relative to the resolved dispatch base. Logs are
`worker-vulture.log` and `worker-provenance.log` in the supplied job directory.

Driver logs were read: dependency sync, lint, format and inventory passed;
focused tests report 201 passed, 3 skipped. Prior job result was read but its
claims are not adopted as current execution evidence. The reproduced blocker is
not a missing Vulture identity.

## Focused validation (fresh executions)

Commands ran at the starting source SHA with 1200-second tool timeouts. Logs are
in the supplied job directory, under `worker-*.log`.

| Command | Outcome | Log |
| --- | --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, 3 skipped; 204 nodes | `worker-focused.log` |
| `uv run ruff check .` | Exit 0 | `worker-ruff.log` |
| `uv run ruff format --check .` | Exit 0 | `worker-format.log` |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Exit 0, two files | `worker-mypy.log` |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Exit 0, 16466 nodes, zero duplicate evidence | `worker-inventory.log` |
| `uv run python scripts/check-shipped-surface-truth.py` | Exit 0 | `worker-shipped.log` |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Exit 0 | `worker-vulture.log` |

`rg -n 'admission_codec|admission_identity' packages/*/src` found only the
codec-to-DTO import and whitelist import (`worker-callers.log`). No runtime
consumer was found; the module docstrings expressly describe inactive contracts.

Read accepted ADR-081226-a66b (one execution lifecycle), ADR-082526-7f02
(immutable admission provenance) and ADR-083126-5e62 (protected-base quality
authority). Reconciliation: do not invent identity, activate an unauthorized
consumer, or treat candidate bookkeeping as permission. Canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` and authorization are unchanged.

## Acceptance audit

| Criterion | Executed evidence / limit |
| --- | --- |
| Exact immutable DTOs, required interfaces and six decode codes | Source inspection plus passing header, schema, v2 state and DTO constructor tests. |
| Named columns, fresh flat mapping, storage-only strict UUID hex, signed timestamps | Passing mapping, owner/generation rejection, scalar-range and bound identity tests. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run | Passing legacy tests distinguish states and reject absent receipt evidence rather than fabricate identity. |
| Header/full-decode separation and matching, unknown formats fail closed | Passing expiry/fingerprint preservation, scalar mismatch and unsupported-format tests. No clock or request fingerprint input. |
| TEXT snapshots; duplicate/nonobject/bare nonfinite rejection; safe errors | Passing invalid JSON, numeric-loss, nesting, Unicode, predecoded-value and error-redaction tests. |
| Preserve tagged context and stored fingerprint | Passing tagged/Unicode/exact-number tests. Real `encode_evidence`/`model_of`/`model_of_json` materialization and original-model fingerprinting are **UNVERIFIED** by these hand-built fixtures. |
| Real migrated PostgreSQL raw/production pool contrast | **UNVERIFIED**: three skips at test_admission_codec.py:470 for absent DSNs. No migrations, database sessions or final SQL counts established this round. |
| Run payload is JSONB object, not double-encoded string | **UNVERIFIED**: these tests insert admission rows only. |
| Authorized Workspace/Project, explicit principals and registered Graph kinds | **UNVERIFIED**: fixture strings prove representation, not authorized admission. |
| No SQL/HTTP/queue/assessor/scope/decision/policy changes | Production source inspected; this round changes only this report. |
| Replacement and mismatch-409 precedence | **UNVERIFIED**, reserved for the C/F2 consumer, not B2. |
| Inventory, focused checks and unchanged required integration CI | Focused checks above pass; full CI **UNVERIFIED**; required provenance **FAILED**. |
| Coordinated stack ownership and activation | Lane supplies repair authority only. Broader integration coordination/activation remain **UNVERIFIED/BLOCKED**. |

No tests or inventory counts changed, so no inventory-delta note is required.
No source fix or new pre-fix/mutation proof is claimed. No DB was provisioned:
the independently reproduced provenance blocker already prevents readiness.

## Failure attribution and final handoff

Inspected the frozen dispatch's captured `test` checks and latest issue comments
(`worker-captured-evidence.json`). The captured failure belongs to
`3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (#1855), with no summary or traceback.
The captured #1945 head `fcc8b437f209a35aa68a61d6f0a5387414938355` reports
`test: success`. Neither is the assigned head. The dispatch's generic test
failure remains **UNRESOLVED**; no speculative test change is justified.
CI's `test` job at `.github/workflows/ci.yml:496` covers other packages, root
integration and frontend suites, so this focused pass is not its reproduction.

**BLOCKED** by the actual required provenance failure. Candidate entries at
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613` cannot authorize themselves;
`.github/workflows/vulture-ratchet.yml:77-85` requires the failing gate.
No sync conflict existed, so no fetch/merge or remote mutation was performed.

Next: owner-coordinated, independently landed reachability authorization and
an explicitly authorized base sync, or separately authorized real consumer
integration. Also supply the assigned-head failing CI traceback if a test
repair is still required. Do not repeat unchanged-source repair rounds without
one of those inputs; a Vulture ledger edit would not solve this blocker.

Changed file: this report only. All existing source, tests, ledgers, grants and
gates preserved. `git diff --check` passed. This evidence/handoff is committed
locally; it is not an implementation repair or integration approval.
Progress: checked 1, done 0, skipped 0, errors 1 (provenance blocker); next:
owner coordination and current-head failure evidence.

