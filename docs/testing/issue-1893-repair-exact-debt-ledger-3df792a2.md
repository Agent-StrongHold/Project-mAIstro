# Issue #1893 — exact-debt-ledger repair re-verification at 3df792a2

**Verdict: the two-merge wall persists; every other acceptance leg is proven,
including the PostgreSQL round-trip legs, which this round re-proved live on a
fresh disposable database.** This record independently re-verifies the prior
round's claims at the current head instead of assuming them, and adds one new
piece of evidence: the three skipped PG-marked codec tests were executed
against a real, freshly migrated PostgreSQL 18 database with
`MAISTRO_REQUIRE_PG_LEGS=1` (skips converted to failures), then the database
was dropped.

## Scope and starting state

- Only issue #1893, worktree `/home/dev/Git/wt/auto-1893`, branch `auto-1893`,
  exact starting head `3df792a2d35ab1f41589ba33b384d89a894e553c` (clean at
  start; only this report is added by this round — no source or test change).
- `git fetch origin` (read-only): `refs/remotes/origin/develop` unchanged at
  `ab8b3737fa64…`; `git merge-base HEAD origin/develop` = `ab8b3737…`, so the
  branch already contains the develop tip and no sync/merge is pending. (Note:
  a stale local `refs/heads/develop` at `9fe61e21` is an *ancestor* of HEAD —
  an old M7 WIP branch pointer, not new develop work; and an ambiguous local
  branch literally named `origin/develop` also sits at `ab8b3737…`. Neither
  changes the trusted base the gates resolve.)

## The three exact-debt-ledger steps, executed locally with CI's exact arguments

CI job definition: `.github/workflows/vulture-ratchet.yml` → `exact-debt-ledger`,
with `RATCHET_BASE_REV` resolving to `origin/develop` for a PR run.

| Step | Command | Result at `3df792a2` |
| --- | --- | --- |
| 1 | `uv run python scripts/check-ratchet-provenance.py` | **FAIL (rc=1)** — exactly two identities, unchanged from the hosted run: `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`, via `FAIL: reachability dispositions moved away from trusted state` ("NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization") and `FAIL: reachability ratchet moved away from trusted state` ("NEW unreachable module absent from trusted base and not previously authorized"), summarized as `FAIL: ratchet provenance inventory is incomplete`. All seven other ratchets (adr-status-language, citation-status, promotion-surface, shell-execution, contract-markers, enumerations, lifecycle) OK with no candidate-approved expansion. |
| 2 | `uv run python scripts/check-shipped-surface-truth.py` | PASS — "Shipped-surface truth matrix is complete." |
| 3 | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS (rc=0)** — `1322 reviewed identities -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`. The vulture ledger is exact; the lane brief's named repair target (amending `quality/vulture-baseline.json`) has no genuine targets — there are no unbanked identities to bank and no eliminated identities to prune. |

Hosted corroboration (no new API calls): the dispatch capture for head
`0eacd9a4` (the commit immediately before this head's docs-only commit) records
`exact-debt-ledger` conclusion `failure`; the local step-1 output above matches
the prior round's hosted-log transcript verbatim in step, gate, and identities.

## Root cause, re-confirmed from source rather than prior claims

- `scripts/ratchet_provenance.py::load_authorizations` reads
  `quality/ratchet-authorizations.json` **from the base revision**
  (`resolve_baseline(path, base=…)` → merge-base), and its docstring states the
  consequence deliberately: "a new grant does not take effect in the change
  that introduces it … two merges — the grant, then the regression it permits."
- `git show ab8b3737:quality/ratchet-authorizations.json` → the base's
  `reachability` grants do **not** contain either identity (they contain the
  eleven pre-existing events/interop/entra/strike-recovery/vulture-whitelist/
  graph entries); the branch adds exactly the two #1893 rows.
- Therefore both provenance sub-gates fail by design until the grant lands on
  develop. Candidate-side edits (ledger, dispositions, grant, `--update`)
  cannot change the verdict; this is the documented two-merge wall
  (AGENTS.md, docs/quality-gates.md).

In-tree options were re-examined and remain closed: deleting the modules would
destroy the B2 deliverable; wiring them into production to become reachable
violates the issue's own stage constraints (B2 is the inactive contract leaf;
"C is the consumer"; "no baseline/grant/gate modifications to make an unwired
slice green") and was already tried and reverted at `29e3be4`/`0eacd9a4`;
amending the vulture ledger would fabricate a row the scanner does not report.
Unblock remains outside worker authority: land the #1893 reachability
authorization on develop via a separate reviewed PR (the text exists in this
branch for review), then merge develop into `auto-1893`.

## New evidence this round: PostgreSQL legs proven live

Per the issue, skipped/fake PG must not count as durability proof, and B1 (on
this branch) supplies the forward schema the round-trip test needs. Executed:

1. Created a fresh disposable database `adm1893_r1792245817` on the local
   `pgvector/pgvector:pg18` container (`maistro-postgres`, 127.0.0.1:5433).
2. `DATABASE_URL=postgresql://…@127.0.0.1:5433/adm1893_r1792245817 uv run
   alembic upgrade head` — the full real migration chain, ending at `062 -> 063`;
   `\d task_idempotency` confirmed the B1 forward columns (`format_version`,
   `generation_id`, `acknowledged_at`, TEXT snapshots).
3. `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` both pointing at that
   same database, `MAISTRO_REQUIRE_PG_LEGS=1` (so a skip would fail):
   - `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
     → **131 passed, 0 skipped**, including the three parametrized
     `test_raw_and_production_pool_codecs_read_identical_text_snapshots` legs
     (`unbound`, `bound`, `acknowledged`): raw vs production-codec pools read
     byte-identical TEXT snapshots, decode to the exact immutable DTO, and
     corrupted surrogate JSON fails typed with suppressed chains while the
     header keeps its scalars.
   - `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
     → **73 passed, 0 skipped**.
4. Dropped the disposable database; the temporary credentials file was removed.

Without PG env, the same suites report `201 passed, 3 skipped` — the three
skips are exactly the PG legs proven above.

## Acceptance status for the B2 leaf (re-checked this round)

- Public codec surface matches the issue spec exactly: `AdmissionDecodeCode`
  with the six specified values, `AdmissionRowDecodeError(ValueError)` carrying
  `code` + validated-hex-only `scope_key` with suppressed exception chains,
  frozen/slotted `AdmissionRowHeader` with the six specified fields,
  `decode_admission_header`, `decode_admission_record`, `encode_admission_record`.
- All 10 prospective test names from the issue body are present (grep 10/10)
  and pass.
- `admission_codec.py` imports only stdlib + `maistro.runs.admission_identity`
  DTOs: no SQL mutation, no HTTP mapping, no queue change.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3301 files);
  `uv run mypy` on both changed modules PASS.
- Driver checks for this job (check-1..4 logs): ruff PASS, format PASS,
  focused pytest 346 passed / 3 skipped, suite inventory `ok` at 16567 node IDs.

## Inventory note

No test was added, removed, or renamed by this round (docs-only change), so no
`docs/testing/inventory-notes/` delta is required; the suite inventory check
remains at the recorded 16567 identities.

## Residual risk

The merge-queue `exact-debt-ledger` evaluation will keep failing on exactly the
two reachability provenance identities until the grant lands on develop and is
merged into this branch. Everything else this job measures — shipped-surface
truth and the vulture per-identity ledger — is green and exact at this head.
