# Issue #1893 repair — job 60d3a446

## Frozen scope and initial evidence

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting HEAD: `3f1848254f47a906095db8d6b18957d5a9b8be95`.
- Supplied base and locally resolved `origin/develop`:
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Initial worktree clean; no incoming edits to salvage.
- One item: #1893 B2 codec CI repair. No other issue/PR will be processed.
- Inspection scope: admission codec/identity modules, adjacent tests, relevant
  ADRs, supplied job evidence, and CI gate definitions. Planned write scope:
  this report; change implementation/tests only for a reproduced scoped defect.
  No reachability ledger/grant edits, activation, or GitHub mutations.
- Ambiguity: dispatch reports `test: failure` without a failing node. Treat as
  unverified until reproduced. The supplied `check-0.log` through `check-4.log`
  instead show dependency sync, lint, formatting, 324 passed / 3 skipped, and
  core suite inventory (16,543 nodes) passing. These are driver evidence, not
  worker executions or real-Postgres durability proof.
- Prior block concerns reachability authorization, not permission to change
  admission semantics or bypass a gate. Check it using CI's exact invocation.

## Worker validation

- Exact requested Vulture scan: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS;
  1322 reviewed identities, zero unclassified. No ledger amendment warranted.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python
  scripts/check-ratchet-provenance.py`: FAIL, exit 1. Both admission modules
  have NEW unauthorized unreachable-module and disposition rows. The other
  wrapper checks pass. This independently reproduces the existing blocker.
- Production import search finds no codec caller; outside the codec itself,
  admission_identity is referenced only by the Vulture whitelist. Test imports
  and a candidate ledger are not production reachability or base authorization.
- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/extensions/test_cli_lock.py
  packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs`:
  **324 passed, 3 skipped**, 327 nodes, 2.14 seconds. The three PostgreSQL
  cases skip at `test_admission_codec.py:470` because the required database
  environment variables are not configured. They are not durability evidence.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: **1919 passed, 310 skipped,
  6 warnings**, 2229 nodes, 49.75 seconds. Warnings are aiosqlite worker threads
  reporting `Event loop is closed` in `test_sqlite_store.py`, not failed codec
  assertions. No unrelated source changes are justified by those warnings.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS, 2 files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16,543 nodes, no duplicate evidence.
- Validation commands used 1200-second timeouts.
- Bounded extraction of failed `test` check-run objects from the supplied
  dispatch JSON found one for SHA
  `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828` (not the assigned HEAD).
  Check run 111298008450 has null output title/summary/text and reports 12
  annotations. This does not identify a failing node at the assigned HEAD.
  The reported merge-queue failure remains UNRESOLVED; no remote refetch or
  speculative repair was performed.

## Acceptance and architecture review

Read repository instructions, accepted ADR-081226-a66b (canonical lifecycle),
accepted ADR-083126-5e62 (protected-base quality authority), codec source/tests,
immutable admission constructors, and the exact-debt-ledger workflow. Nothing
in this round changes `Goal -> Graph -> Run -> NodeRun -> Attempt` or any
execution, authorization, Goal-store or event authority.

| Criterion | Executed evidence / limitation |
| --- | --- |
| Frozen header, supported schema/version, strict scalar hashes and signed timestamps; header-row agreement | Focused tests PASS; code constructs frozen/slotted header and re-derives it before full decode. |
| Immutable v2 snapshots and fresh flat SQL mapping, named columns, UUID hex, owner-token hygiene | Focused tests PASS, including all three binding states. Independent assertions at test_admission_codec.py:134–137 pin paired task/run columns rather than merely checking encode/decode agreement. |
| Bound, unresolved, partial and receipt-only legacy evidence without inferred identity | Focused tests PASS, including bound pair without receipt rejected as partial; DTO requires receipt identity, so none is invented. completed_at is ignored. |
| Header retains expiry/fingerprint when full decode fails; unknown format fails closed | Focused tests PASS. Codec has no clock, incoming fingerprint, classifier or claim mutation. Consumer expiry/409 precedence is outside B2 and UNVERIFIED. |
| Strict JSON, duplicate/non-object/bare nonfinite rejection; safe typed failures | Focused tests PASS, including injected corrupt raw TEXT, lossy numbers, nesting and invalid Unicode; suppressed exception chains asserted. |
| Tagged program_context and unchanged stored fingerprint | Focused tests PASS for retained tag objects and stored fingerprint; original model fingerprint computation and model_of/model_of_json materialization remain UNVERIFIED, not proven by synthetic tag fixtures. |
| Raw and production asyncpg on same migrated disposable database | UNVERIFIED this round: three PostgreSQL tests skipped. No migration-chain, session identity, SQL row residue or real DB durability claim. |
| Actual JSONB Run object and real authorized principals/Workspace/Project/Graph | UNVERIFIED: synthetic codec DTOs are not authorization or Run INSERT evidence. |
| Reachable production acceptance | UNVERIFIED: no production codec caller. Do not insert a dummy caller or activate the staged leaf to bypass the issue constraints. |
| Unchanged full integration CI | UNVERIFIED. Focused and adjacent tests pass; provenance fails. No claim that the unspecified remote test failure is repaired. |
| No SQL/HTTP/queue/assessor/scope-policy changes | This round edits this report only. Staged implementation remains inactive; no activation or parent closeout authorized. |

No new tests, source changes, or inventory-count changes were made, so no new
inventory-delta note is required. No fresh pre-fix/mutation proof is claimed.
Existing implementation, tests and ledger history are preserved.

## Disposition and handoff

**BLOCKED** by reproduced trusted-base reachability authorization failure.
The Vulture-only ledger exception does not authorize reachability/disposition
or grant changes. Accepted governance requires an owner-coordinated,
protected-base prerequisite; candidate banking cannot approve this candidate.
No develop-sync conflict exists in the initial clean tree; no merge, fetch,
GitHub mutation or policy modification was performed.

Changed file: `docs/testing/issue-1893-repair-60d3a446.md` only, committed as a
blocked evidence handoff, not integration approval.

Progress: checked 1; done 0 repairs; skipped 0 issues; errors 1 blocking gate.
Next: resolve the reachability prerequisite outside this lane and provide the
actual SHA-qualified failing test log. Then rerun authorized integration and
real PostgreSQL acceptance. Re-dispatching this same source/base without new
evidence cannot repair the protected-base prerequisite.
