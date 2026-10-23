# #1893 verification round — job 9de5cfe5

Snapshot: issue #1893 only; assigned branch `auto-1893`, clean starting HEAD
`4e43df759aad9627dcb9b66fba33e086c5869972` (identical to the dispatch-context
PR #1945 head), develop base `5df964aba0ae5bf570ca7d8b78ee5e59520dce3f`.
Evidence sources: job `9de5cfe5e8ac43839bdf5610774f0045` driver logs
check-0..4, the prior result artifact
`a53d685662d34e0f8ea043041af530ba/result.json`, and this round's own reruns.
One read-only `git fetch origin`: **origin/develop advanced to `5df964aba`**
(seven commits: #2103 docs, #2101 rsi containment, #2098 anyio lock retire,
#2100 soak fingerprints, three WIP imports). `git log HEAD..origin/develop --
quality/` shows only two `quality/ac-state-notes/*.json` additions (WIP
commits); **no reachability authorization for `maistro.runs.admission_identity`
or `maistro.tasks.admission_codec` landed on the trusted base**, so the
two-merge blocker stands and there is no merge to perform for it.

No production code, ledger, grant, gate or test file was edited this round.
The named CI gate failure (`test: failure`) was refuted further with legs no
prior round had run, and the live-PostgreSQL durability evidence was
re-produced on a fresh disposable database.

## Driver checks (all five pass)

`uv sync --locked --extra dev` (note: it uninstalls `maistro-bootstrap`;
use `--extra bootstrap` before running gates that import it), `ruff check .`,
`ruff format --check .` (3238 files), focused
`pytest packages/maistro-core/tests/runs/test_root_admission_identity.py
packages/maestro-core/tests/tasks/test_admission_codec.py -q` → **201 passed,
3 skipped**, `check-suite-inventory.py --suite packages/maistro-core/tests` →
**16298 node IDs match the recorded inventory**.

## exact-debt-ledger (vulture-ratchet.yml:30,77)

- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → **exit 1**, both sub-gates:
  reachability-dispositions (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec`: NEW disposition absent from trusted ledger
  and not covered by an already-landed reachability authorization) and
  reachability (same two modules: NEW unreachable module absent from trusted
  base and not previously authorized). `ratchet_provenance.load_authorizations`
  reads `quality/ratchet-authorizations.json` **from the merge base**
  (cc6e4899), so a branch-side grant can never authorize its own
  introduction — confirmed by reading
  `scripts/check-reachability-provenance.py:60-63`.
- The other two legs of the same job pass with CI's exact arguments:
  `check-shipped-surface-truth.py` → exit 0; `check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → exit 0,
  1323 reviewed identities → 1323 findings. No vulture amendment is warranted;
  the lane brief's ledger exception does not extend to
  `quality/reachability-*.json`, and no alternative configuration passes:
  removing the two rows makes `check-reachability-provenance.py` fail with
  "current unreachable module missing from candidate baseline" instead. The
  issue forbids wiring the modules into production (B2 exit: typed
  representation only, no `_assess` change), so the grant on develop — or
  stage-C wiring — is the only sanctioned resolution. It remains outside
  writer authority (no GitHub mutations).

## CI `test: failure` (ci.yml test job) — refuted at this head

Legs executed in CI's environment (`REQUIRE_AUTH=false`,
`MAISTRO_DRY_RUN=1`), the ones no earlier round had covered:

- Cross-suite leakage leg, exactly as written in ci.yml:
  `pytest tests/ packages/hive-conductor/backend/tests
  packages/maistro-design/tests -q --timeout=60` → **9178 passed, 148
  skipped** (555 s, one process).
- `check-suite-inventory.py` (all suites) → **17 suites match**.
- `check-test-duplicates.py` → 0 byte-identical groups.
- OpenAPI coupling leg: `dump-hive-openapi.py` (226 paths, 132 schemas) →
  `npm run gen:api` → `git diff --exit-code -- types.gen.ts` → clean.

The seven pytest legs (server/turing/turing-backend/design/ext-harness/
ext-sdk/root) were already proven at `b21becd66`; `git diff e75dc68..HEAD --
packages/ quality/` is empty, so that evidence transfers to this head. The
npm lint/build/test/audit legs were not run locally (no Node-native need: the
branch touches no frontend file or lockfile, and the backend↔frontend
coupling point — the generated-types diff — is clean); recorded as
unverified-local, not as passing.

## Live PostgreSQL durability — re-produced on a fresh disposable DB

Docker was unavailable this round (stale `/var/run/docker.sock`, no daemon),
so the disposable database was created on the local PostgreSQL **18.6**
server instead of a pgvector:pg18 container — same major version the prior
round proved:

- `CREATE ROLE auto1893 LOGIN PASSWORD …; CREATE DATABASE auto1893_durability
  OWNER auto1893;` (pgvector 0.8.1 available on the server).
- `DATABASE_URL=postgresql://auto1893:…@127.0.0.1:5432/auto1893_durability
  uv run alembic upgrade head` → the real chain **001 → 061**, exit 0.
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=MAISTRO_TEST_DATABASE_URL=…`
  over both focused files → **204 passed, 0 skipped** (1.5 s).
- `pg_catalog`: `ck_task_idempotency_v2_identity` present on
  `task_idempotency` with exactly the both-or-neither binding rule and
  `task_id = receipt_id`, plus acknowledged ⇒ bound.
- Live INSERT of `encode_admission_record` output (bound record) satisfies
  the CHECK; a corrupted binding (`task_id ≠ receipt_id`) and a one-sided
  pair (`run_id` NULL) are each rejected by the CHECK; cleanup leaves
  **0 residue rows**.

`packages/` and `quality/` are byte-identical to `e75dc68` (the prior live-PG
head), so the prior round's in-memory regression replay (43 failed / 85
passed against the pre-repair codec) also transfers unchanged.

## Other checks

- No premature-closure directive against #1893 anywhere in
  `git log origin/develop..HEAD --format='%s%n%b'` (grep for
  `(closes|fixes|resolves) #?1893` → no match).
- `mypy` on both new source modules → no issues.
- No test added this round, so no `inventory-delta` note is required;
  `check-suite-inventory.py` confirms the recorded inventory still matches.

## Residual (unchanged)

1. exact-debt-ledger fails on reachability/disposition provenance until the
   authorization lands on `origin/develop` and develop is merged into this
   branch (two-merge rule). Documented, not circumvented.
2. Snapshot finite-number precision (`9007199254740993.0` lossy through the
   #1851 dependency) remains a recorded coordinated dependency repair outside
   codec scope.
3. The disposable DB `auto1893_durability` and role `auto1893` were dropped
   after evidence capture; recreate via the two SQL statements plus
   `alembic upgrade head` if a later round needs to repeat the durability
   legs.
