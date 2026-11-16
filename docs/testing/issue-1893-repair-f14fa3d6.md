# Issue #1893 repair checkpoint — f14fa3d6

## Frozen scope

- Sole item: issue #1893; assigned worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `520d71bb30e4367aee1643acf5074dcc31a216ed` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Initial working tree clean; no incoming changes to salvage.
- Candidate repair surfaces: admission codec, admission identity DTOs, their two focused test files, corresponding inventory note, and (only if actual scan evidence requires it) vulture baseline. This report records validation even when no code repair is justified.
- No remote mutations, production activation, admission policy changes, or reachability/grant edits authorized. Existing staged implementation is preserved.

## Initial evidence and ambiguity

Read repository AGENTS.md and captured dispatch issue body. Driver logs check-0 through check-4: dependency sync, ruff check, format check, focused tests (201 passed, 3 skipped), and suite inventory (16466) passed. These are driver evidence, not independently executed acceptance tests.

The dispatch names `test: failure` but supplies no failing node in the prompt. Assumption: reproduce focused behavior and exact requested gates before considering any repair. Prior provenance blocker is not evidence of a vulture defect. Reachability authorization cannot be manufactured by this lane.

Independent named gates executed with 1200-second timeout: Vulture passes (1323 reviewed identities / 1323 findings), so no ledger amendment is warranted. `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` fails (exit 1): both admission modules are newly unreachable and newly dispositioned without trusted-base authorization. Base resolved before use. This is an external authorization/integration blocker, not a develop-sync conflict.

Read codec, immutable DTOs, both focused test files, exact-debt-ledger workflow, and accepted ADR-081226-a66b, ADR-082526-7f02, ADR-083126-5e62. Reconciliation: preserve canonical execution hierarchy and immutable admission provenance; candidate bookkeeping cannot authorize itself. This lane's Vulture exception does not extend to reachability grants. No source change justified by these findings.

## Independently executed validation

All commands ran against unchanged production/test source at starting HEAD, with 1200- or 1800-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 identities / findings |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL, exit 1: two unauthorized unreachable modules, two unauthorized dispositions |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 204 nodes: 201 passed, 3 skipped, 1.37s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3277 files |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS: two files |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS: 16466 nodes |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `rg -n 'admission_codec\|admission_identity' packages/*/src quality/reachability-baseline.json quality/reachability-dispositions.json` | Only codec-to-DTO and whitelist imports; no production consumer |
| `git diff --check` | PASS |

## Acceptance audit

- Frozen/slotted header, required interfaces/codes, #1851 constructor validation: inspected source and executed focused contracts pass.
- Named-column SQL mapping, strict UUID `.hex`, signed scalar timestamps, fresh mapping, task/Run binding shape: focused contracts pass. Independent binding-column assertions at `test_admission_codec.py:134-138` prevent encode/decode agreement from masking the prior schema bug.
- Legacy bound/unbound/partial, receipt-only and announced-without-Run: focused tests pass. A bound pair without stored receipt evidence remains partial, not an invented canonical binding.
- Header/full-record separation, preserved expiry and fingerprint despite corrupt snapshots/partial bindings, unknown-format rejection, mismatched-header rejection: focused tests pass. Expiry replacement and HTTP 409 precedence belong to C/F2, not this codec.
- Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection, error-chain suppression: focused tests pass, including recursion, numeric precision and Unicode corruption boundaries.
- Tagged snapshot and fingerprint preservation: byte/tag codec tests pass. End-to-end production `encode_evidence`, original-model fingerprinting and `model_of`/`model_of_json` materialization remain **UNVERIFIED**; manually constructed fixtures do not prove these paths.
- Raw/production pools on a genuinely migrated disposable PostgreSQL database: **UNVERIFIED this round**; three tests skip at `test_admission_codec.py:470` because both DSNs are absent. No DB provisioned after reproducing the independent mandatory authorization blocker. No session identity, durable row, migration-chain, or cleanup-count claim is made. Prior live-PG claims were read but not adopted as fresh evidence.
- Run JSONB object insertion, explicitly authorized principals/Workspace/Project and registered Graph kinds: **UNVERIFIED**; DTO fixtures prove neither authorization nor Run persistence.
- No clock, live assessment, SQL mutation, HTTP/queue/scope utility or policy changes: codec remains mapping-only, with no production consumer. Canonical execution authority unchanged.
- Focused tests, lint, format, scoped mypy, inventory: pass as above. No tests added, no inventory delta or new mutation/pre-fix claim.
- Unchanged required integration CI / independent mergeability: **BLOCKED** by provenance gate; full CI not run and remains **UNVERIFIED**. Stage coordination/activation prerequisites remain external and **UNVERIFIED**.

## Failure attribution and handoff

Read supplied prior result and captured issue comments/check data. The captured failed `test` check belongs to `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output summary/text. Captured checks on `5d835338f7fa45b62d6361c9f3eddc5faf14284a`, `fcc8b437f209a35aa68a61d6f0a5387414938355` and `d0a03c8db5c49c4756a1dc231a7bdc31f731f105` succeeded. None is the assigned HEAD. Assigned-head failure attribution is **UNRESOLVED**; a failing node/traceback from the actual candidate is required before a speculative CI repair.

Reproduced blocker: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`; mandatory gate `.github/workflows/vulture-ratchet.yml:77`. Resolving this requires separately authorized consumer integration or trusted-base authorization, neither permitted here. Vulture-only ledger permission cannot resolve this blocker. No conflict exists; no fetch/merge justified.

Only changed file: this report. Production, tests, inventory, ledgers, grants, whitelist and gates are untouched. Commit locally as a blocked handoff; no GitHub mutation or closure action. Do not dispatch another identical repair without the missing external prerequisite and attributable CI failure evidence.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 mandatory gate; next: authorized integration base and assigned-head CI diagnostics.

Verdict: **BLOCKED**.
