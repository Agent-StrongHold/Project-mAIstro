# Issue #1893 — exact-debt-ledger repair round at 3c59d681a

**Verdict: BLOCKED stands, re-proven independently this round. The two-merge
provenance wall remains the sole `exact-debt-ledger` failure; the vulture
ledger is exact with zero amendable rows; and the three PostgreSQL durability
legs are re-proven live on a fresh disposable database migrated through the
real chain (204 passed / 0 skipped).**

Entry state: branch `auto-1893`, exact head
`3c59d681a0adbee35224f620f86e87089417c0ca`, working tree clean. Only this
record is added; no source, test, ledger, or gate file is modified.

## Driver deterministic checks (job 15093b714b084d66850607e120dcecd6)

All five driver checks green at this head: `uv sync --locked --extra dev`,
`ruff check .` (all checks passed), `ruff format --check .` (3301 files
formatted), focused pytest over the four issue-named files (**346 passed,
3 skipped** — the skips are the PG-gated durability legs), and
`check-suite-inventory.py --suite packages/maistro-core/tests`
(ok: 16567 unique node identities).

## CI job `exact-debt-ledger`, re-run locally with CI's exact arguments

Workflow: `.github/workflows/vulture-ratchet.yml` → `exact-debt-ledger`;
`RATCHET_BASE_REV` resolves to `origin/develop` for a PR run.

| Step | Result at `3c59d681a` |
| --- | --- |
| `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py` | **FAIL (rc=1)** — exactly `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`, via both `reachability-dispositions` ("NEW disposition absent from trusted ledger and not covered by an already-landed reachability authorization", 169 → 171) and `reachability` ("NEW unreachable module absent from trusted base and not previously authorized", 171 of 1403). All seven other ratchets OK. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS (rc=0) — matrix complete. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **PASS (rc=0)** — `1322 reviewed identities -> 1322 findings`, `unclassified: 0`, `never_allowlist: 0`. The ledger is exact: zero unbanked identities to bank and zero eliminated identities to prune, so the round brief's named amendment target (`quality/vulture-baseline.json`) has no genuine rows; amending it would fabricate findings. |

## Root cause, re-derived this round (not assumed)

1. **Base grant state.** `git show ab8b3737:quality/ratchet-authorizations.json`
   contains **zero** rows matching `admission_identity`/`admission_codec`
   (grep rc=1); the branch's own grant rows (added at `6af21c54e`, with
   owner/issue/reason) exist only candidate-side.
2. **Base-only grant loading is deliberate.**
   `scripts/ratchet_provenance.py::load_authorizations` (lines 478–509)
   resolves the authorizations file against the base revision; its docstring
   states the two-merge consequence verbatim: "a new grant does not take
   effect in the change that introduces it." Confirmed empirically: the gate
   still fails on a tree that already contains the grants.
3. **The develop side is unmoved (live).** `git ls-remote origin
   refs/heads/develop` → `ab8b3737fa64f8d840f421ef87ca506c509444ff` = merge
   base; branch is 377 ahead / 0 behind. No develop-sync conflict exists to
   resolve, and the grant is not in flight on any queue ref.
4. **Hygiene note (no action taken).** This worktree has a stale local branch
   named `refs/heads/origin/develop` that makes `git rev-parse origin/develop`
   print an ambiguity warning; both it and `refs/remotes/origin/develop`
   resolve to `ab8b3737`, so base resolution is unaffected. Branch deletion is
   outside writer authority, so it is recorded here instead of removed.

## PG durability legs re-proven live (fresh disposable DB)

- Database: `adm1893_r1792250719` on the running `maistro-postgres`
  (pgvector/pgvector:pg18, PostgreSQL 18.6, 127.0.0.1:5433), created fresh and
  migrated with `DATABASE_URL=… uv run alembic upgrade head` through the real
  chain (final `alembic_version` = **063**, `select count(*) from
  alembic_version` = 1).
- Command: `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` both pointing
  at that same DB (server identity compared inside the test via
  `current_database()/inet_server_addr()/inet_server_port()`), plus
  `MAISTRO_REQUIRE_PG_LEGS=1` so a silent skip is impossible:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → **204 passed, 0 skipped**.
- Row hygiene: `select count(*) from task_idempotency` = **0** after the run
  (the two-pool test deletes its rows); the disposable DB was dropped after
  the proof.

### Negative evidence recorded: harness export artifact, not a regression

The first live attempt this round produced `3 failed` on
`test_raw_and_production_pool_codecs_read_identical_text_snapshots[*]` with
"MAISTRO_REQUIRE_PG_LEGS requires MAISTRO_TEST_PG_DSN and
MAISTRO_TEST_DATABASE_URL". Root cause was the harness, not the tests: the
one-line form `export MAISTRO_TEST_PG_DSN=… MAISTRO_TEST_DATABASE_URL="$MAISTRO_TEST_PG_DSN"`
expands `$MAISTRO_TEST_PG_DSN` **before** any assignment in the command takes
effect, so the test process saw the DSN set (the `pg_pool` fixture built a
real pool) but `MAISTRO_TEST_DATABASE_URL` empty. Proven with a probe test in
the same directory requesting `pg_pool`: `DSN='postgresql://…' URL=''`. Two
separate `export` statements make both legs pass. This is the same artifact
recorded at `2b92bf17`; it must not be misread as a codec or fixture
regression.

## Issue acceptance re-check against production behavior

- All ten issue-named prospective tests exist (one `def` each) and pass in
  `packages/maistro-core/tests/tasks/test_admission_codec.py`.
- `admission_codec.py` implements exactly the required surface:
  `AdmissionDecodeCode(StrEnum)` with the six named values; `AdmissionRowHeader`
  `@dataclass(frozen=True, slots=True)`; `decode_admission_header`,
  `decode_admission_record(row, *, header)`, `encode_admission_record`;
  `AdmissionRowDecodeError(ValueError)` carrying `code` and `scope_key`
  (nulled unless it matches the hex64 digest), with parsing chains suppressed
  (`raise … from None` at every raiser).
- Scope: `grep -c "INSERT|UPDATE |DELETE FROM|httpx|APIRouter|.execute("` over
  both new modules → 0 matches; the diff vs `ab8b3737` adds no SQL mutation,
  HTTP mapping, or queue change. `_vulture_whitelist.py` additions are
  sanctioned scan-support references (the #1142 pattern).
- mypy: `uv run mypy packages/maistro-core/src` → "Success: no issues found in
  791 source files" after `uv sync --locked --all-extras`. (Under
  `--extra dev` alone, 5 `import-not-found` errors appear for
  `maistro_bootstrap` modules — the documented missing-extras artifact, not a
  code defect.)

## Conclusion

Every acceptance leg that a worker can prove locally is green at this head;
the sole failing CI step fails only because a candidate cannot authorize its
own grant — the documented two-merge design. Unblocking requires a
grant-only PR into `develop` (or queue ref) followed by merging that base
into `auto-1893`; both are GitHub mutations outside worker authority. No
in-tree repair action remains: the vulture ledger has no unbanked or
eliminated identities, and the reachability rows are already dispositioned and
granted candidate-side.
