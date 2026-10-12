---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair checkpoint — ab5e

## Frozen scope and decision

Assigned worktree `/home/dev/Git/wt/auto-1893`, clean source HEAD
`9f02c0eed07f7698fef68fa4033358c4ee7a458c`, supplied base and local
`origin/develop` both `3c761d14db944a727fa0744444bc67cfe36d49f7`.
Only #1893 was processed. This note is the only repository change; no tests,
source, grants, ledgers, gates, or production wiring changed.
Artifacts: `/home/dev/maistro/jobs/ab5edc46106e43b2b22d8385d79299ba/`.

Read repository instructions, supplied issue/CI evidence, codec, immutable
constructors, adjacent tests/PG fixture, and accepted ADRs 081426-1f7c,
082526-7f02, 082826-b601, 082826-d9f5. Reconciliation: preserve immutable
admission provenance and Goal -> Graph -> Run -> NodeRun -> Attempt; neither
DTO construction nor a test import grants execution or admission authority.
Assignment permits local staged repair, not activation or integration approval.

**BLOCKED:** fresh `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7
uv run python scripts/check-ratchet-provenance.py` exits **1**. Both
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` add
unapproved unreachable modules and dispositions (169 trusted, 171 candidate).
See `repair-provenance.log:20-29`, `quality/reachability-baseline.json` and
`quality/reachability-dispositions.json`. The exact-debt workflow runs this
gate at `.github/workflows/vulture-ratchet.yml:77`, before vulture. The allowed
vulture repair exception does not authorize reachability/disposition grants.
No candidate grant can authorize itself under the two-merge rule.

The exact requested vulture command passed with **1323 reviewed identities /
1323 findings**, so no ledger amendment is warranted. Production import search
finds only codec -> DTO and the vulture whitelist, no runtime codec consumer
(`production-references.txt`). Adding a fake caller would violate the issue.

Generic hosted `test: failure` attribution is **UNRESOLVED**. Supplied captured
#1945 checks concern `fcc8b437f209a35aa68a61d6f0a5387414938355` (test success,
exact-debt failure), not this source HEAD. Supplied driver check-0..4 logs pass,
with focused tests 201 passed / 3 skipped, not live PG proof. No unqualified
prior verification is reused. A first local snapshot-extraction attempt hit a
list/dict shape error; the corrected extraction is `captured-ci-evidence.txt`.
No remote enumeration or GitHub mutation was performed.

## Fresh executed validation

All commands used `uv run` and long timeouts. Logs are `repair-*` in the job.

- `createdb maistro_1893_ab5e` after confirming the name absent, followed by
  `DATABASE_URL=postgresql:///maistro_1893_ab5e uv run alembic upgrade head`:
  passed the real chain **001 -> 062**, PostgreSQL **18.6**. No downgrade,
  hand-built schema, or application database was used.
- Set **both** `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` to
  `postgresql:///maistro_1893_ab5e`, plus `MAISTRO_REQUIRE_PG_LEGS=1`.
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused.xml`:
  **204 passed, zero skips**. Separate `--collect-only -q` records all 204 nodes
  in `repair-focused-nodes.txt`.
- Unbound/bound/acknowledged two-pool cases used production/raw PID pairs
  **3109669/3109670**, **3109671/3109672**, **3109673/3109674** on that database
  over the Unix socket. Non-None production pools register `_register_json_codecs`.
  Each asserts one persisted scoped row, identical TEXT mappings/DTOs, and safe
  rejection of corrupt escaped-surrogate snapshots through both readers.
  Immediate SQL counts: **0 rows / 0 generations / 0 Run IDs**.
- In-process regression probe replaced only the encoder return's `task_id`
  with None, leaving source files untouched. Both bound unit round trips failed
  at `test_admission_codec.py:134`; the real bound PG INSERT failed
  `ck_task_idempotency_v2_identity`. **3 expected failures**; harness asserted
  `pytest.ExitCode.TESTS_FAILED`. See `repair-binding-mutation.log:117-125`.
- Same PG environment, `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q -rs`: **2225 passed, 3 skipped,
  6 warnings**. Skips are backend-inapplicable archive/continuation cases, not
  codec PG legs; warnings are SQLite worker callbacks after event-loop closure.
  Final SQL: revision **062**, **3 legacy rows / 0 generations / 2 Run IDs**,
  no v2 codec residue. Disposable database retained for inspection.
- `uv run ruff check .`, `uv run ruff format --check .`: passed.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`,
  `check-shipped-surface-truth.py`: all candidate checks passed; they do not
  supersede the failed trusted-base provenance gate.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **16466 nodes**, delta **0**.

## Acceptance audit

| Criterion | Evidence at this source HEAD |
| --- | --- |
| Immutable exact DTO/header and fresh named SQL mapping | Inspected constructors and codec; identity tests, three v2 round trips and fresh-flat-mapping test passed |
| UUID .hex at storage only, signed timestamps, header/row agreement | Owner/generation tests, invalid scalar/header mismatch/schema tests passed |
| Typed codes, validated hash only, safe displayed parsing chains | Error-scope, token, malformed/nested/lossy/non-UTF8 snapshot tests passed |
| Legacy bound/unresolved/partial, receipt-only and no invented identity | Legacy binding, missing receipt, unreadable evidence, whitespace and completed_at tests passed |
| Header preserves expiry/fingerprint despite full decode failure | Both named preservation tests and expired legacy header test passed; no clock or decision is introduced |
| Unknown format fails closed | Seven unknown-format cases passed, including supplied-header laundering attempts |
| Canonical snapshots, evidence tags, unchanged fingerprint | V2 byte round trips, tagged nonfinite, exact-number and Unicode tests passed |
| Duplicate keys/nonobjects/bare nonfinite and corrupt originals rejected | JSON, predecoded-value, nesting, numeric-loss and surrogate tests passed |
| Raw/production pools share real migrated schema and TEXT behavior | Three real PG cases, distinct sessions, persisted counts and mutation proof above |
| Typed-only stage; no assessment/SQL mutation/HTTP/queue/scope-policy change | Inspected pure mapping implementation; this round changes documentation only |
| Actual model_of/model_of_json materialization, encode_evidence provenance and object-valued Run JSONB INSERT | **UNVERIFIED** by these codec tests; fixtures retain tags but do not materialize task/Run models |
| Authorized principals/Workspace/Project/registered Graph and reachable production admission | **UNVERIFIED**; synthetic DTO/storage fixtures are not authorized admission; codec has no runtime consumer |
| Inclusive expiry/409 precedence and complete integration CI | **UNVERIFIED**; consumer C/F2 responsibility and hosted CI are not established by this leaf; provenance gate fails locally |

## Handoff

No new codec failure or vulture mismatch supports a source/ledger repair.
Required next: owner-coordinated trusted-base resolution for the two inactive
modules, then revalidation; obtain an exact failing test node/log for this HEAD
if the generic CI failure still applies. Do not repeatedly redispatch the same
external blocker as a vulture repair. No independent mergeability or rollout
approval is claimed.

Progress: checked **1**, validation/handoff done **1**, skipped items **0**,
blocking gate errors **1**. Commit this evidence locally; repair remains blocked.
