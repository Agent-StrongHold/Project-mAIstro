# #1893 repair handoff — job 526b2a9f

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Starting HEAD: `8ca86b0723e09d06603bccaeea3328bced6c36c7` (verified); supplied develop base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect the supplied dispatch snapshot, check-0 through check-4 logs, repository instructions and applicable ADRs.
- Implementation scope: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, adjacent admission tests and existing atomic-admission inventory notes. This checkpoint records results. Only evidence-driven repairs; vulture ledger exception applies only if the exact scan demonstrates a retained identity requiring amendment.
- No reachability baseline, disposition, authorization, activation, HTTP, scheduler or SQL mutation changes authorized.

## Assumptions and progress

The lane is a writer repair despite the shared prompt's verifier instructions. The supplied exact base/owner assignment controls this bounded work; issue coordination/activation restrictions remain in force. Previous verification is evidence to recheck, not proof. A generic `test: failure` has no actionable traceback yet. No develop sync conflict is present, so no fetch/merge is planned.

Verified initial HEAD and clean status; read repository instructions and complete issue body from the frozen dispatch artifact. Driver check-0..4 pass (sync, Ruff, format, 324 passed/3 skipped, core inventory 16543); skips are not PostgreSQL proof. Read the previous result, codec, first 270 lines of codec tests, lifecycle ADR and CI exact-debt-ledger invocation.

Fresh exact Vulture scan exits 0. Fresh `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` exits 1. Logs are `.pytest_cache/repair-526b2a9f/{vulture,provenance}.log`. The supplied base resolves; its merge base is `2154f845347c9541016288c760f8da3f5cd2e064`. No guessed Vulture debt will be banked. The initial broad search referenced nonexistent `docs/adr/README*`; not found, skipped; used `docs/README.md` instead. The failure is exactly two NEW unreachable modules and two NEW dispositions: `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`. All other provenance subchecks pass. The exact Vulture result is 1322 reviewed identities / 1322 findings.

Fresh focused codec/identity tests, adjacent tasks/runs tests, Ruff check, Ruff format check, scoped mypy, core inventory and reachability/disposition/promotion/shipped-surface gates all exit 0; detailed counts are being transcribed from logs. Source search confirms no production codec consumer: only its own identity import and the Vulture whitelist reference the modules. The captured PR #1945 head `90d4c278e6d729d41a3f30d9f17bc65025d6f59d` has `test: success` and `exact-debt-ledger: failure`; this is a different head, not proof for this candidate. The dispatch supplies no failing test traceback at the assigned HEAD. No speculative test repair is justified.

Read accepted ADRs 081226-a66b, 082826-b601, 082826-d9f5 and 083126-5e62. Reconciliation: preserve the canonical execution/store authority and inactive B2 boundary; neither fake production imports nor candidate policy changes can authorize this leaf. Inspection and focused validation completed; blocked handoff below. No production, test, gate, ledger or inventory changes were justified. This note is the only changed file.

## Executed validation

All executions use the assigned worktree at the starting source SHA above; only this Markdown note changed. Command timeouts were 1200 seconds. Logs are under ignored `.pytest_cache/repair-526b2a9f/`.

| Command | Observed result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -ra --junitxml=.pytest_cache/repair-526b2a9f/focused.xml` | 201 passed, 3 skipped; 204 collected nodes recorded in JUnit. Three record_property/xunit2 warnings; PostgreSQL cases skipped because both DSNs are unset. |
| `uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q -ra` | 1919 passed, 310 skipped, 6 warnings; 2229 total nodes. Warnings are aiosqlite worker-thread/event-loop teardown warnings in existing SQLite tests; not silently treated as failures or repaired outside scope. |
| `uv run ruff check .` | Passed. |
| `uv run ruff format --check .` | Passed, 3301 files formatted. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | Passed, 2 source files. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Passed, 16543 unique collected nodes, no duplicates. No test additions/removals; no inventory delta needed. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed, 1322 reviewed identities = 1322 findings, zero unclassified. |
| `uv run python scripts/check-reachability.py` | Passed against candidate ledger; does not authorize debt. |
| `uv run python scripts/check-reachability-dispositions.py` | Passed against candidate ledger; does not authorize debt. |
| `uv run python scripts/check-promotion-surface.py` | Passed. |
| `uv run python scripts/check-shipped-surface-truth.py` | Passed. |
| `RATCHET_BASE_REV=321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62 uv run python scripts/check-ratchet-provenance.py` | FAILED, exit 1: two unauthorized unreachable modules and their dispositions, trusted merge base `2154f845347c9541016288c760f8da3f5cd2e064`. |
| `git diff --check` | Passed. |

Mutation evidence: `uv run python` replaced only the in-memory encoder with a wrapper forcing `row['task_id'] = None`, then invoked `pytest.main` on `test_v2_round_trip_preserves_all_snapshot_bytes[bound]`. It failed at `packages/maistro-core/tests/tasks/test_admission_codec.py:134` (`None != 'rcpt-1'`), as required. The harness verified `pytest.ExitCode.TESTS_FAILED` and exited 0. No mutation was written to disk. This establishes an independent storage-shape assertion rather than circular encode/decode agreement.

## Acceptance accounting

- Frozen/slotted header, strict formats/digests/signed timestamps, header/row mismatch rejection: inspected `admission_codec.py:157-253`; focused header tests passed. No incoming fingerprint or clock is accepted.
- Fresh flat v2 mapping, UUID .hex storage, all three snapshot strings, binding and acknowledgement states: focused round-trip/owner/encode tests passed; the bound-case mutation fails independently at line 134. Actual PostgreSQL CHECK execution this round is **UNVERIFIED**.
- Legacy unbound/bound/partial/receipt-only/announced-without-Run shapes, missing receipt evidence, ignored completed_at: corresponding focused tests passed. No missing work identity is invented.
- Header expiry/fingerprint preserved despite full-decode errors; unknown formats fail closed: all named prospective unit cases passed. Replacement/409 ordering remains C/F2 behavior, not proven by this codec.
- Strict JSON object parsing, duplicate/bare-nonfinite rejection, tagged evidence retained, unchanged stored fingerprint, deep nesting/lossy numbers/invalid Unicode refused with typed safe errors: focused tests passed. Tests inject storage TEXT rather than pre-normalizing malformed evidence.
- Real model materialization through evidence-json/model_of/model_of_json, valid registered Graphs and authorized principal/Workspace/Project admission: **UNVERIFIED**; the B2 tests exercise DTO snapshots, not a reachable admission consumer.
- Raw and production asyncpg pool comparison on the same migrated disposable DB, JSONB Run payload object shape, migration-chain durability, DB session/row/identity counts: **UNVERIFIED** this round. Both DSNs are unset and three focused PG cases skipped. No DB was created or mutated; no skipped test is counted as durability evidence.
- No SQL mutation, web serialization, scheduler, assessment, claim, policy or production activation change: preserved by the note-only diff and source inspection. Production reachability is absent (`admission_codec.py:50-53` and production-source search); test imports are not runtime reachability.
- Focused pytest, lint, format, types, inventory and exact Vulture scan: passed as recorded. Full integration CI and the reported hosted `test: failure`: **UNVERIFIED**, no failing-node traceback at this HEAD supplied or reproduced. Do not infer hosted success from local subsets or another PR head.
- Trusted-base quality/independent mergeability: **FAILED**, existing reachability rows at `quality/reachability-baseline.json:131,147` and dispositions at `quality/reachability-dispositions.json:606-613` remain unauthorized. Vulture exception cannot repair a reachability authorization failure.

## Disposition and next step

**BLOCKED.** The external coordination/policy blocker remains unresolved. An authorized owner must first resolve the staged-contract reachability authorization on the protected base (or supply an authorized integration path); only then can a subsequent lane synchronize that resolved base and revalidate. This worker cannot land a grant, activate the C consumer, or mutate GitHub. Supply the actual failing `test` log/node for this head before asking for a test repair. Do not redispatch the same generic failure as evidence for cosmetic or guessed scanner changes.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; errors 1 required gate; next: owner resolution plus disposable-PG/full-integration acceptance validation. Local handoff committed; no merge or integration approval is implied.
