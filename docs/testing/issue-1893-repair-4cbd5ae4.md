# Issue #1893 repair — job 4cbd5ae4

## Frozen scope and checkpoint

- Assigned worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD `d0a88cec67148735e04256c5a59a8123d53e4b6b`; assigned develop base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial working tree clean. One item: #1893; no GitHub mutations or production activation.
- Read frozen dispatch issue body and source index. Prior claims are not validation.
- Driver logs: check-0 dependency success; check-1 ruff success; check-2 3277 formatted; check-3 201 passed / 3 skipped; check-4 core inventory 16466 matches. These are driver results, not fresh worker executions.
- Planned inspection: repository instructions, ADRs governing immutable admission/evidence, codec/identity source and adjacent tests, CI exact-debt-ledger workflow, existing reachability additions.
- Edit scope: this validation record; source/tests or permitted vulture ledger only if an actual reproduced defect warrants repair. No speculative gate changes.
- Ambiguity: reported `test: failure` includes no failing node or traceback. Proceed with focused tests and exact ledger/provenance checks; do not infer a source defect.

## Reproduced blocking result

Executed against the assigned, resolved base with 1200-second timeout:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed identities / 1323 findings. No unbanked identities; no Vulture ledger amendment warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL. `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` each add an unauthorized unreachable module and an unauthorized disposition (169 -> 171). Other provenance subchecks passed.

This is not a sync conflict or a Vulture repair. The lane cannot authorize reachability debt or wire the out-of-scope C consumer. Preserve implementation, record the blocker, and finish focused validation rather than manufacture approval. Supplied prior result confirms an earlier blocked handoff; current failure is independently reproduced.

## Focused validation completed

Fresh commands against unchanged source at the starting HEAD (1800-second timeout):

| Command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped, 1.29s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, 2 files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS, 16466 nodes |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

Read both complete source modules and focused test files, repository AGENTS.md, exact-debt-ledger workflow, and accepted ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62. Reconciliation: preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`, immutable admission provenance, and trusted-base authorization. The Vulture-only ledger exception does not authorize reachability/disposition changes.

## Acceptance audit

- Required frozen/slotted header, interfaces, error codes, validated scope, constructor contracts: source inspected and focused tests pass.
- Header/full decode separation, expiry/fingerprint scalar preservation despite malformed snapshots or partial bindings, strict unsupported format/schema and mismatched-header rejection: focused tests pass. No expiry classifier or HTTP precedence claim; those belong to C/F2.
- Named fields, strict storage UUID `.hex`, signed timestamps, fresh flat mapping, optional binding/acknowledgement and receipt consistency: focused tests pass, including storage-column assertions independent of encode/decode agreement at `test_admission_codec.py:134-138`.
- Legacy unbound/bound/partial, receipt-only, missing receipt, unreadable identity and ignored completed_at: focused tests pass. No legacy identity invention.
- Strict TEXT JSON, duplicates/nonobjects/bare nonfinite rejection, safe exception suppression, tagged snapshots and unchanged stored fingerprint: focused tests pass. Numeric-loss, recursion and Unicode boundary tests exercise direct storage corruption.
- Existing evidence-json encoding and `model_of`/`model_of_json` production materialization, original-model fingerprint integration: **UNVERIFIED**. Tests hand-build tags; they do not prove production model materialization.
- Raw and production pools on the same disposable, genuinely migrated PostgreSQL database: **UNVERIFIED this round**. Three tests skip at `test_admission_codec.py:470` because both required DSNs are absent. No database provisioned after independent mandatory authorization blocker reproduced; no migration, DB session, durable row or residue-count evidence claimed.
- Run JSONB object persistence and explicitly authorized principals/Workspace/Project/Graph kinds: **UNVERIFIED**. Mapping-only DTO tests cannot establish these integration properties.
- No clock, claim mutation, live assessment, HTTP/queue/scope or policy change: inspected codec remains mapping-only. No new scheduler, Goal store, event authority or authorization path.
- Focused tests, lint, format, scoped types and inventory pass. No new tests or source changes, so no inventory delta or mutation/pre-fix claim this round.
- Unchanged full required integration CI: **UNVERIFIED** and mandatory provenance check **FAILS**. Coordination/activation prerequisites remain external; no production activation or independent mergeability asserted.

## Failure attribution and final handoff

Source search `rg -n 'admission_codec|admission_identity' packages/*/src quality/reachability-baseline.json quality/reachability-dispositions.json` finds only the codec importing the DTO and a whitelist importing its enum: no runtime consumer. The mandatory gate at `.github/workflows/vulture-ratchet.yml:77` rejects additions at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`.

Inspected captured check-run data in the frozen dispatch without fetching GitHub. Its failed `test` check belongs to `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with no output summary/text. Checks captured for the other three linked heads succeeded. None of these heads is the assigned candidate. Attribution of the reported `test: failure` to this head remains **UNRESOLVED**; no failing node or traceback supports a source repair.

Only changed file: `docs/testing/issue-1893-repair-4cbd5ae4.md`. Source, tests, inventories, ledgers, grants, whitelist and gates remain untouched. No conflict exists, so no fetch/merge was justified. No speculative or cosmetic code repair made.

Required next input: an authorized integration base/consumer resolution for the inactive modules, plus assigned-head CI failure diagnostics. Candidate banking cannot satisfy trusted-base authorization; repeating the same repair dispatch cannot resolve this external blocker. Stage readiness is not integration approval.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 mandatory gate; next: external prerequisite and attributable CI diagnostics.

Verdict: **BLOCKED**. Commit this evidence locally as the handoff; no push or issue action.
