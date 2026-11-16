---
inventory-delta:
  packages/maistro-core/tests: +20
---

# Issue #1893 repair — job 4302

## Frozen scope

- Assigned issue: #1893; writer in `/home/dev/Git/wt/auto-1893`.
- Starting head: `0fb5143432844f8f10f4e0453fe1069f9612cdba` (clean).
- Supplied develop base: `e1b13dcd15dedd637404c38dfe1900921aba2b8c`.
- Process only existing codec, adjacent identity/schema/tests and their validation;
  the explicit vulture repair allowance does not authorize other ledger edits.
- Snapshot evidence: job `4302e26013204e46b01b73a7e97a9ef6` dispatch-context.json
  and check-0 through check-4.log. No remote enumeration or mutations.
- Driver reports lint/format passed; focused tests 181 passed, 3 skipped;
  inventory core count 15091. These are not PostgreSQL acceptance proof.
- Ambiguity: issue prohibits activation while requesting runtime reachability.
  Preserve staged pure codec scope and report unmet integration gates rather than
  introduce a consumer or change authorization. Assignment fixes owner/base for
  this local repair only, not rollout readiness.

## Progress

The bound-pair encoding repair is already present and matches migration 055.
Executed the exact requested vulture scan: PASS, 1328 reviewed / 1328 found;
there is no evidenced vulture ledger amendment to make. Executed ratchet
provenance with the supplied resolved develop base: FAIL for unauthorized
reachability/dispositions of admission_identity and admission_codec (trusted
merge base b1f17b8d6246). This is not vulture debt and remains out of scope.

Captured reviews identify lone-surrogate canonicalization as another defect.
Inspecting the current codec confirms no UTF-8 validation at decode. Next:
reproduce that exact storage-boundary failure, then repair only B2 decoding
if confirmed. Constructor behavior (#1851) remains a separate dependency.
A dispatch extraction command printed the relevant reviews, then failed with
AttributeError because check-runs data is a list rather than a mapping; no
hosted test traceback has been established. Do not guess a CI-test fix.

Read accepted ADRs 081426-1f7c, 082526-7f02, 082826-b601, 082826-d9f5.
The repair changes only decoding validity, not execution, admission provenance,
identity ownership, or scheduling; no ADR reconciliation changes are needed.

Regression executed before the production edit:
`uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q
-k 'non_utf8_snapshot or valid_unicode_snapshot'` => **16 failed, 4 passed**.
All negative cases failed with DID NOT RAISE AdmissionRowDecodeError. Inputs
are escaped lone high/low surrogates in values, nested keys and arrays, across
legacy request and all three v2 snapshots; injected directly as storage TEXT.
The four positive controls preserve paired surrogates, non-ASCII Unicode and
literal backslash-u evidence. Log: `unicode-before.log` in this job directory.

Repair: require the canonicalized decoded snapshot to encode as UTF-8 before
returning it. UnicodeEncodeError is a ValueError and is converted through the
existing safe INVALID_SNAPSHOT boundary (no unsafe displayed exception chain).
No constructor or encoder input-validation policy changed. Extended the three
existing migrated-pool tests to inject escaped-surrogate TEXT into each v2
snapshot, read it through both codecs, and require typed rejection with intact
header fingerprint. +20 new collected nodes; no new mocked durability claims.

Created dedicated disposable PostgreSQL database `maistro_1893_4302` and ran
`DATABASE_URL=postgresql:///maistro_1893_4302 uv run alembic upgrade head`:
PASS through real migration chain to 060. No downgrade/destructive chain tests
were needed for this codec-only repair. Set MAISTRO_TEST_PG_DSN and
MAISTRO_TEST_DATABASE_URL both to `postgresql:///maistro_1893_4302` and
MAISTRO_REQUIRE_PG_LEGS=1. Executed `uv run pytest
packages/maistro-core/tests/tasks/test_admission_codec.py
packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
-o junit_family=legacy --junitxml=<job>/focused.xml`: **204 passed, no skips**.
All three states persisted on the real migrated schema; both registered and
raw pools rejected corrupt escaped-surrogate snapshots in all three columns.
Logs: `migrate.log`, `focused.log`, `focused.xml` in this job directory.

`uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3137 files).
`uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).

## Final validation and acceptance boundaries

- PostgreSQL session PID pairs (production/raw), as recorded in focused.xml:
  unbound 2505208/2505210, bound 2505213/2505215, acknowledged
  2505306/2505372. All use `maistro_1893_4302` on the local Unix socket; each
  test requires a non-None production pool. Each observes exactly 1 scoped
  row; final SQL after focused tests shows migration 060, **0 admission rows,
  0 generations, 0 Run identities** after test cleanup.
- With the same mandatory PG environment, `uv run pytest
  packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q`:
  **2071 passed, 3 skipped, 6 warnings**. Warnings are aiosqlite callbacks
  after event-loop closure, not codec failures; skipped adjacent tests do not
  count as durability evidence. See adjacent.log.
- `uv run pytest` of the two focused files with `--collect-only -q`: **204
  nodes**, exact IDs retained in collected-nodes.log.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, **15111 nodes** (+20).
- Re-ran the exact vulture command after changes: PASS, **1328/1328**.
  No reviewed retained identity requires amendment; no ledger modified.
- `uv run python scripts/check-reachability.py`,
  `check-reachability-dispositions.py`, `check-promotion-surface.py`: PASS.
  These candidate scans do not authorize newly banked baseline debt.
- Re-ran `RATCHET_BASE_REV=e1b13dcd15dedd637404c38dfe1900921aba2b8c
  uv run python scripts/check-ratchet-provenance.py`: **FAIL**, unauthorized
  admission_identity/admission_codec reachability and dispositions, unchanged.
  Logs retained as provenance.log and named gate logs in the job directory.
- `uv run python scripts/check-radon-baseline.py`: PASS, **138/138** blocks.
  `git diff --check`: PASS.

All ten named prospective codec tests execute in the focused suite: canonical
v2 bytes/bound-pair identity, owner UUID hex, legacy bound/unbound/partial
separation, expiry/header preservation, fingerprint preservation despite full
decode failure, unknown-format rejection, tagged nonfinite preservation,
strict JSON rejection, real raw/registered-pool TEXT round trips. Header
mismatch/scalar validation and safe errors are additionally exercised. New
Unicode tests fail on the starting source for the named defect, then pass
with the UTF-8 validation repair. This is typed representation proof only.

Production consumer reachability remains absent by the staged contract;
no fake caller, new admission path, activation, grant or ledger adjustment
was introduced. Authorized end-to-end admission, model_of/model_of_json
materialization, Run JSONB object writes, live expiry/409 precedence and full
hosted CI remain **UNVERIFIED** by this leaf. The generic supplied `test:
failure` has no established traceback and is not reproduced by focused or
adjacent tests; the Unicode repair is supported by separate actual evidence,
not claimed as a fix of that unspecified CI failure.

Residual dependency: direct #1851 CanonicalJsonObject construction still
normalizes finite precision and accepts lone surrogates before B2 sees the
input. Reproduced with `uv run python` at this repaired tree: constructor
input `{"n":9007199254740993.0}` becomes `{"n":9007199254740992.0}`;
escaped lone-surrogate input becomes a string raising UnicodeEncodeError
when encoded as UTF-8. B2 now rejects unusable canonical text when decoding stored snapshots;
it cannot recover information lost before encoder input. Constructor repair
and coordinated trusted-base consumer/authorization belong to the dependency
owners, not this bounded codec repair. The previously recorded production
activation policy remains untouched.

Disposition: **BLOCKED**, despite completed local codec repair. Next requires
coordinated trusted-base authorization/integration and an actual hosted test
failure trace. Progress: checked 1, repaired 1, skipped 0 issues; 1 required
gate failed. No GitHub mutation or integration approval.
