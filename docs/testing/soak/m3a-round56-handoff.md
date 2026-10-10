# Issue #860 — round 56 (job a19d8898) independent re-validation at 7f8608a47

**Not promotion evidence or integration approval.** This round re-executes the
full battery at the dispatch head `7f8608a4717a65c0d46a72f77a0f9fc3fa691738`
(working tree clean on arrival, exactly the dispatch head) and re-derives the
terminal external pair from this round's own 69-source capture
(2026-10-10T05:18Z). The round-53 escalation (NEEDS-DEEP-REVIEW) is
**external and unchanged**: it requires a release-owner decision under parent
#89 plus a production-hosted soak, neither of which any repair worker can
supply.

The driver manifest for this round again carried an **empty `checks` list**
(no `check-*.log` files exist for job `a19d889873bd48a7963b9b6e2e6962ad`),
and the prompt's "Validation failed" pointer again referenced job
`98a11313`'s `check-3.log` — the same **stale round-44 artifact** whose
DDL-fence failure (`test_ensure_schema_fences_ddl_behind_advisory_lock`,
24 != 21) predates the current head and was re-executed green this round
(below). No source, test, gate, ledger, or inventory file changed; the only
artifact is this handoff note. Inventory delta: 0 (no collected tests added
or removed).

## Deterministic battery executed at `7f8608a47` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Stale `check-3.log` test alone: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock -q` | 1 passed — the round-44 failure does not reproduce at this head |
| Driver pair `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 38 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-doc-links.py` | 0 broken relative links |

## Promotion-gate replay (executed this round, live module import)

`failed_promotion_checks()` loaded from `scripts/soak/run_soak.py` and run
against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`.
- All eight correctness gates `ok=true` in the pack: exactly-once task
  admission, exactly-once schedule occurrence, rate limit enforced
  (`200:200, 429:600` on the limited path), `lb_failover_bounded`,
  `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `graceful_drain`; kill-window `drain_5xx: 0`.
- `sustain_duration` honestly fails: `observed_seconds=420.09` (requested
  420) against `minimum_seconds=14400` (`PROMOTION_MIN_SUSTAIN_SECONDS`,
  `scripts/soak/run_soak.py:67`).
- `exact_rc_artifact` refuses the host-uvicorn-preflight topology by design
  (`preflight_artifact_check`, `scripts/soak/run_soak.py:730-743`): *"not
  the exact production Compose image and configuration"* — there is
  deliberately no CLI override.
- Pack hash binding (row 10 of the issue): `hashes.git_head=3da4e035eb1f…`,
  `git_diff_sha256`, `git_status_sha256`, `nginx_conf_sha256`,
  `nginx_rendered_conf_sha256`, `soak_env_sha256`,
  `postgres_image=pgvector/pgvector@sha256:2358fcba…`, `python` — all present.
- Evidence head `3da4e035eb1f` verified ancestor of HEAD via
  `git merge-base --is-ancestor`.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/`: 16 files,
  **all inside `docs/testing/soak/`** — the round-43 evidence pack (6 files
  under `evidence/`) plus handoff notes `m3a-round43…round55-handoff.md`.
  **Zero soak-runtime, gate, or test-code drift; `deploy/` diff empty.**

## External pair re-derived from this round's own capture (2026-10-10T05:18Z, 69 sources)

The two failing rows are the issue's own terminal pair: row 3 (*"Run
sustained load long enough to observe…"*) and row 8 (*"Include at least one
long-running soak of the exact RC artifact/configuration that #89 would
promote"*).

1. **No RC exists to soak.** Parent **#89 is open with zero comments**
   (captured fresh this round: state=open, comments=0, title *"M3-A7 — Run
   RC soak and byte-equivalent final promotion"*). A designation sweep over
   all 69 captured sources found 284 broad designation-language matches and
   11 perfective-candidate windows; **all 11 windows are explicit negations**
   ("No immutable RC image/configuration is designated…", "no … designated
   in the assignment", "was designated by this assignment" inside negative
   sentences) in PR #1672's diff hunks — absence statements, not a
   designation. No release-owner RC designation exists in this round's
   capture.
2. **A compliant soak cannot complete inside a bounded attempt.**
   `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (4 h) against this job's
   `timeout_s = 5400` (1.5 h), with background execution prohibited by lane
   rules. The only in-lane topology (host-preflight) is refused by
   `exact_rc_artifact` by design, so a longer in-lane run could not flip
   either failing row — it would only add a vanity duration number, which
   the issue's stop condition explicitly forbids.

## Linked-PR and develop position (re-confirmed from this round's capture + git)

- **#1567** closed/merged and **#1602** closed/merged: merge commits
  `394ff842`/`cfc515c14` verified ancestors of HEAD via
  `git merge-base --is-ancestor` (head SHAs `d22378795cf3`/`927a9c3c5bc6`
  are not themselves merge-reachable; ancestry is on the merge commits).
- **#1672** open draft at head `16b244414b01` — verified ancestor of HEAD.
- **#2100** closed/merged develop-side (head `b950e5933a28`, not an
  ancestor of HEAD); its soak-fixture fingerprints are carried here —
  `.gitleaksignore:69` `8185c1d0…` and `:96` `88edcc7e…` re-read this round.
- `git fetch origin`: `origin/develop = ed5613457` == **this round's
  dispatch base**; no new develop commits since dispatch, so this round's
  block was not a develop sync conflict and no merge was mandated.

## Escalation (unchanged in substance since round 26)

Resolving the two terminal rows requires exactly two external actions no
worker can take:

1. A **release owner designates the RC** under parent #89 (open, zero
   comments — no designation exists as of this round's 05:18Z capture).
2. A **release-owner-hosted ≥ 14,400 s soak of that exact Compose
   artifact**, whose observed image/configuration evidence satisfies
   `preflight_artifact_check` in a runner built for it.

Every row inside lane authority is evidenced and green at this head; the
soak harness, gates, and evidence chain show zero drift since the evidence
pack. Progress: checked 1 issue; done 0 acceptance-complete issues (8/10
rows evidenced, 2 externally blocked); skipped 0; validation-command errors
0; escalated 1 (the RC designation + production soak pair); inventory delta
0 (no tests added).
