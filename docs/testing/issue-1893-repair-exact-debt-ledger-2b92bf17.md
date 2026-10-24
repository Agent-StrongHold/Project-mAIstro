# Issue #1893 — exact-debt-ledger repair round at 2b92bf17

**Verdict: BLOCKED stands. The two-merge provenance wall is the sole
`exact-debt-ledger` failure; every in-tree repair path is closed by verified
evidence, and every other acceptance leg is green at this head — including a
fresh live-PostgreSQL proof of the three durability legs this round.**

Entry state: branch `auto-1893`, exact head
`2b92bf1718e4240cd9a0882d89366ea3ab1f0476`, working tree clean. Only this
record is added; no source, test, ledger, or gate file is modified.

## CI job `exact-debt-ledger`, re-run locally with CI's exact arguments

Workflow: `.github/workflows/vulture-ratchet.yml` → `exact-debt-ledger`
(85 lines; three gate steps; `RATCHET_BASE_REV` resolves to `origin/develop`
for a PR run).

| Step | Result at `2b92bf17` |
| --- | --- |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | **FAIL (rc=1)** — exactly `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`, via both `reachability-dispositions` ("NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization", 169 → 171) and `reachability` ("NEW unreachable module absent from trusted base and not previously authorized", 171 unreachable of 1403). All seven other ratchets OK. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (rc=0). |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS (rc=0)** — `1322 reviewed identities -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`. The ledger is exact: zero unbanked identities to bank and zero eliminated identities to prune, so the round brief's named amendment target (`quality/vulture-baseline.json`) has no genuine rows; amending it would fabricate findings and break exactness. |

## Root cause, re-derived this round (not assumed)

1. **Base grant state.** `git show ab8b3737:quality/ratchet-authorizations.json`
   parsed: `reachability` carries 11 rows (#61 ×4, #458 ×2, #492, #1172,
   #1142, #1154 ×2) — neither #1893 identity; **`reachability-dispositions`
   carries no rows at all**. Both #1893 grant rows exist only on this branch
   (added at `6af21c54e`, owner/issue/reason complete).
2. **Base-only grant loading is deliberate.**
   `scripts/ratchet_provenance.py::load_authorizations` (lines 478–518) reads
   the authorizations file via `resolve_baseline(..., base=...)`; its
   docstring states the two-merge consequence explicitly: "a new grant does
   not take effect in the change that introduces it." Candidate-side ledger
   edits therefore cannot turn this job green — confirmed by re-running the
   gate (FAIL above) on a tree that already contains the grants.
3. **The develop side is unmoved (live).** `git ls-remote origin
   refs/heads/develop` → `ab8b3737fa64f8d840f421ef87ca506c509444ff`, equal to
   `git merge-base HEAD origin/develop`; `git fetch origin develop` is a
   no-op. Branch is 0 behind / 376 ahead — **no develop sync conflict exists**,
   and no merge-queue ref has landed the grant yet.
4. **Scanner classification is factually correct.** Grep of `packages/*/src`:
   the only src-side reference to either module outside themselves is
   `_vulture_whitelist.py:105` importing `AdmissionAssessment` — the
   sanctioned scan-support whitelist file (itself a known-unreachable module
   banked under grant #1142), not a runtime importer. There is no missed
   production import edge to surface.
5. **In-tree options, each closed on evidence:**
   - *Delete the two modules* — destroys the issue-mandated B2 deliverable
     (`admission_codec.py`, `admission_identity.py` are named deliverables in
     the issue body).
   - *Wire them into production* — forbidden by the issue ("C is the
     consumer"; "No production activation … is authorized"). Attempted once
     (`29e3be4`) and reverted at `0eacd9a4` as a broken reachability hack.
   - *Package-export re-export* — the issue states "package exports are not
     runtime reachability"; an `__init__` re-export would be scanner gaming.
   - *`_EXCLUDED_PACKAGE_PYTHON` / gate edits* — prohibited gate
     modification; the exclusion valve covers non-src-root Python only.
   - *Vulture ledger amendment* — nothing to amend (exact 1322==1322 above).

## Issue acceptance legs, re-verified at this head

- **B2 deliverables present:** `packages/maistro-core/src/maistro/tasks/admission_codec.py`
  (662 lines), `packages/maistro-core/src/maistro/runs/admission_identity.py`
  (517), `packages/maistro-core/tests/tasks/test_admission_codec.py`,
  `packages/maistro-core/tests/runs/test_root_admission_identity.py`.
- **Mandated interfaces present:** `AdmissionRowHeader`
  `@dataclass(frozen=True, slots=True)` with the six specified scalar fields;
  `decode_admission_header(row: Mapping[str, object])`;
  `decode_admission_record(...)`; `encode_admission_record(...)`;
  `AdmissionDecodeCode(StrEnum)`; `AdmissionRowDecodeError(ValueError)` with
  `code` and `scope_key` validated against `_HEX64_RE` before exposure
  (admission_codec.py lines 127–207).
- **All 10 prospective issue test names present** (including the async
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots`).
- **Focused pytest (no PG env):** `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q` →
  **201 passed, 3 skipped**; the 3 skips are exactly the PG legs.
- **PG durability legs proven live this round** (supersedes prior claim;
  issue forbids counting skips as durability proof):
  - Fresh disposable DB `adm1893_r1792248850` created on the running
    `maistro-postgres` container (127.0.0.1:5433).
  - `DATABASE_URL=… uv run alembic upgrade head` ran the real migration chain
    to head (`063`, "canonical Goal store" migration last); 75 public tables.
  - `MAISTRO_REQUIRE_PG_LEGS=1` + `MAISTRO_TEST_PG_DSN` +
    `MAISTRO_TEST_DATABASE_URL` (same DB) → focused pair: **204 passed,
    0 skipped, 0 failed**, including the three
    `test_raw_and_production_pool_codecs_read_identical_text_snapshots[*]`
    legs (raw asyncpg pool vs production `_register_json_codecs` pool on one
    migrated row; TEXT snapshots read identically).
  - DB dropped afterward (disposable lifecycle respected).
  - Note: a first attempt appeared to fail with the legs' fail-closed guard;
    cause was a shell one-line `export A=… B="$A"` expansion artifact in the
    harness, not the tests — with the same DSN exported separately the legs
    pass deterministically. Recorded here so the transient is not mistaken
    for a regression.
- **mypy:** `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` → clean.
- **ruff:** `uv run ruff check .` PASS; `uv run ruff format --check .` PASS
  (3301 files already formatted).
- **Suite inventory:** driver check-4 at this head: `ok
  packages/maistro-core/tests: 16567`, 0 duplicate-evidence groups.
- **Driver logs (check-0..4):** sync OK, ruff PASS ×2, focused pytest
  346 passed / 3 skipped, inventory ok.

## Unblock path (outside worker authority)

Land the #1893 reachability/reachability-dispositions grant on `develop` via
a separate reviewed grant-only PR (rows already exist on this branch in the
required owner/issue/reason form), then merge `develop` into `auto-1893` so
`load_authorizations` sees them at the new merge base. Both steps are GitHub
mutations, which this worker is prohibited from performing. Until then,
merge-queue `exact-debt-ledger` keeps failing on exactly these two
identities; all other legs of the job are green and exact.
