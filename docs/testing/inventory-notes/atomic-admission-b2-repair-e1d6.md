---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 bounded repair handoff — e1d6

## Scope and outcome

Only issue #1893 was processed in `/home/dev/Git/wt/auto-1893`, branch
`auto-1893`. Verified clean starting/source HEAD:
`cb16bcae91102dcaade6e3885b286d262eaebab8`; verified dispatch base:
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Artifacts: `/home/dev/maistro/jobs/e1d651f494ee413f91d5890961fdec68/worker-*`.
This note is the only repository change: no source, test, ledger, grant,
gate, or production activation edits are justified by the executed evidence.

**BLOCKED.** Fresh trusted-base provenance fails on two new unreachable
modules and their unauthorized dispositions: `maistro.runs.admission_identity`
and `maistro.tasks.admission_codec` (`worker-provenance.log:20-29`). Candidate
rows remain at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The blocking workflow runs
this gate at `.github/workflows/vulture-ratchet.yml:77`. The explicit Vulture
repair exception does not permit changing reachability/disposition grants.
Vulture itself passes: **1323 reviewed identities / 1323 findings**; there is
no evidence supporting a Vulture ledger amendment.

Inspected repository instructions, supplied issue body/check logs/captured
check failures, codec/identity constructors, adjacent tests and PostgreSQL
fixture, and Accepted ADRs 081226-a66b, 081426-1f7c, 082526-7f02, 082826-b601.
Reconciliation: immutable admission provenance and
`Goal -> Graph -> Run -> NodeRun -> Attempt` remain authoritative. A DTO or
codec import is not admission or execution authority. The issue's typed-only
stage does not authorize adding a fake caller to satisfy reachability.
Production source import search finds only codec -> identity types and the
Vulture whitelist, not a runtime consumer (`worker-consumers.log`).

The generic hosted **`test: failure` remains UNRESOLVED**. The captured failed
`test` check belongs to dependency #1855 at SHA `3f2c79a70d9e`, not the assigned
HEAD; its output contains no traceback. The captured #1945 failure is
`exact-debt-ledger` at `fcc8b437f209`. See `worker-captured-failures.jsonl`.
No new remote enumeration was performed. Supplied driver logs pass, but their
201 passed / 3 skipped focused result was not treated as PostgreSQL evidence.

## Fresh executed validation

Commands used long timeouts. Results apply to the source HEAD above.

- `uv sync --locked --extra dev`: passed.
- `uv run ruff check .`; `uv run ruff format --check .`: passed.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py`: **exit 1**, blocker above.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`, and
  `check-shipped-surface-truth.py`: passed. These candidate checks do not
  override trusted-base provenance.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **16466 nodes**, inventory delta **0**.
  `git diff --check`: passed.
- Confirmed database name absent, then `createdb maistro_1893_e1d651f4` and
  `DATABASE_URL=postgresql:///maistro_1893_e1d651f4 uv run alembic upgrade head`:
  real chain **001 -> 062** passed on PostgreSQL **18.6**. No downgrade,
  hand-built schema, or existing application database was used.
- Set both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_e1d651f4`, plus `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/worker-focused.xml`:
  **204 passed, zero skips**. A separate `--collect-only -q` saved all
  **204 nodes** in `worker-focused-nodes.log`.
- Real unbound/bound/acknowledged two-pool cases recorded production/raw PID
  pairs **1688314/1688317**, **1688347/1688348**, **1688349/1688351**, all on
  the dedicated database over Unix sockets. Non-null production pools use
  `_register_json_codecs`. Each asserts one persisted scoped row, identical
  TEXT/mapping/DTO reads, and safe surrogate-corruption rejection through
  both readers. Immediate final SQL: **0 rows / 0 generations / 0 Run IDs**.
- Same PostgreSQL environment, `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q -rs`: **2225 passed, 3 skipped,
  6 warnings**. Skips concern backend-inapplicable archive/continuation
  behavior, not the codec PostgreSQL tests. Warnings concern SQLite worker
  callbacks after event-loop closure. Final SQL: **3 format-1 rows / zero
  generations / 2 legacy Run IDs**, no v2 residue.
- In-process mutation replaced only the encoder return's `task_id` with None,
  without editing source. The bound and acknowledged unit round trips failed
  at `test_admission_codec.py:134`; the bound real-PostgreSQL INSERT failed
  `ck_task_idempotency_v2_identity`. **3 expected failures**, with the harness
  asserting `pytest.ExitCode.TESTS_FAILED` (`worker-binding-mutation.log`).
  These are regression-sensitivity results, not failures of the current code.

## Acceptance audit

| Criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header and immutable DTOs; fresh flat named SQL mapping | Source inspection, identity immutability tests, v2 round trips and fresh-mapping test passed |
| UUID .hex only at storage; signed timestamps; header matches row | Owner/generation, invalid-scalar, header mismatch and missing-schema tests passed |
| Typed codes, validated scope only, safe displayed exception chains | Token/scope, invalid JSON, nesting, lossy-number and surrogate tests passed |
| Legacy bound/unresolved/partial, receipt-only and announced-without-Run | Named legacy binding tests and missing-receipt/partial/whitespace cases passed; no invented identity |
| Header preserves expiry/fingerprint when full decode fails | Both named preservation tests and expired legacy header test passed; codec has no clock or incoming fingerprint |
| Unknown formats fail closed | Seven parametrizations passed, including supplied-header laundering attempts |
| Snapshot TEXT/tags/unchanged fingerprint | V2 byte round trips, tagged nonfinite, valid Unicode/exact-number and predecoded-value rejection tests passed |
| Duplicate keys, nonobjects, bare nonfinite and corrupt original data rejected | JSON rejection and nested/corrupt evidence tests passed |
| Real migrated raw/production pool contrast | Three executed PostgreSQL cases, distinct sessions, one-row assertions and mutation proof above |
| No new SQL mutation, HTTP/queue mapping, scope utility or admission decision | Mapping-only implementation inspected; no source changes in this round |
| Arbitrary permitted evidence through constructor normalization | **UNVERIFIED**: #1851 constructor uses float normalization; codec rejects lossy incoming decimals rather than preserving them |
| model_of/model_of_json materialization, encode_evidence provenance, object-valued Run JSONB INSERT | **UNVERIFIED** by these codec tests; fixtures retain tags, not materialized task/Run models |
| Real authorized principals/Workspace/Project/registered Graph and reachable admission | **UNVERIFIED**; synthetic storage fixtures are not authorized admissions, and codec has no production consumer |
| Inclusive expiry / 409 precedence and full integration CI | **UNVERIFIED** here; consumer C/F2 behavior is outside this codec, and provenance fails |

## Next required action

Obtain owner-coordinated trusted-base resolution for the inactive modules
before revalidation; candidate grants cannot authorize themselves. Obtain an
assigned-head failing test node/traceback before requesting a test repair.
Do not repeatedly redispatch this same external blocker as a Vulture repair.
The disposable database is retained for inspection. No merge, push, GitHub
mutation, integration approval, or rollout approval is claimed.

Progress: checked **1**, validation/handoff done **1**, skipped items **0**,
blocking gate errors **1**. Repair remains blocked.
