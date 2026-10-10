# Issue #860 — round 55 (job 45230450) independent re-validation at 40c295a6d

**Not promotion evidence or integration approval.** This round resolves the
round-54 dispatch block: the immediately preceding attempt (job `ac078ba7`)
re-ran the full battery at this same head but **made no commit** — a clean
tree is not proof of repair. This round commits the re-validation. The
round-53 escalation (NEEDS-DEEP-REVIEW) remains **external and unchanged**:
it requires a release-owner decision under parent #89 plus a
production-hosted soak, neither of which any repair worker can supply.

The driver manifest for this round again carried an **empty `checks` list**
(no `check-*.log` files exist for job `45230450`), and the prompt's
"Validation failed" pointer referenced job `98a11313`'s `check-3.log` — a
**stale round-44 artifact** whose DDL-fence failure
(`test_ensure_schema_fences_ddl_behind_advisory_lock`, 24 != 21) predates the
current head and was re-executed green this round (below). Every result here
was executed directly by the worker at the starting head `40c295a6d`
(working tree clean on arrival, exactly the dispatch head). No source, test,
gate, ledger, or inventory file changed; the only artifact is this handoff
note. Inventory delta: 0 (no collected tests added or removed).

## Deterministic battery executed at `40c295a6d` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Stale `check-3.log` test alone: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock -q` | 1 passed — the round-44 failure does not reproduce at this head |
| Driver pair `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 38 passed, 6 skipped |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked (base `cc6e4899ddef`, candidate `40c295a6df6e`) |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-doc-links.py` | every relative markdown link resolves |

## Promotion-gate replay (executed this round, live module import)

`failed_promotion_checks()` loaded from `scripts/soak/run_soak.py` and run
against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`.
- All eight correctness gates `ok=true`: exactly-once task admission,
  exactly-once schedule occurrence, rate limit enforced,
  `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain` (`required: true, ok: true`).
- `sustain_duration` honestly fails: `observed_seconds=420.09` against
  `minimum_seconds=14400` (`PROMOTION_MIN_SUSTAIN_SECONDS`,
  `scripts/soak/run_soak.py:67`).
- `exact_rc_artifact` refuses the host-uvicorn-preflight topology by design
  (`preflight_artifact_check`, `scripts/soak/run_soak.py:730-745`):
  *"not the exact production Compose image and configuration"* — there is
  deliberately no CLI override.
- Pack hash binding (row 10 of the issue): `hashes.git_head=3da4e035eb1f…`,
  `git_diff_sha256`, `git_status_sha256`, `nginx_conf_sha256`,
  `nginx_rendered_conf_sha256`, `soak_env_sha256`,
  `postgres_image=pgvector/pgvector@…`, `python=3.12.14` — all present.
- Evidence head `3da4e035eb1f` verified ancestor of HEAD via
  `git merge-base --is-ancestor`.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/`: 6 files,
  all inside `docs/testing/soak/evidence/` — the round-43 evidence pack and
  its raw logs/metrics/conf artifacts themselves. **Zero soak-runtime, gate,
  or test-code drift; `deploy/` diff empty.**
- Develop-side diff over the same paths (`HEAD...origin/develop`): only
  `deploy/scripts/backup.sh` (#2105 backup-permission hardening; not
  soak-runtime).

## External pair re-derived from this round's own capture (2026-10-10T04:44Z, 69 sources)

The two failing rows are the issue's own terminal pair: row 3 (*"Run
sustained load long enough to observe…"*) and row 8 (*"Include at least one
long-running soak of the exact RC artifact/configuration that #89 would
promote"*).

1. **No RC exists to soak.** Parent **#89 is open with zero comments**
   (captured fresh this round: state=open, comments=0, title *"M3-A7 — Run
   RC soak and byte-equivalent final promotion"*). A designation sweep over
   all 69 captured sources found 140 broad designation-language matches and
   4 perfective candidates ("has been designated" shapes); **all 4 sit
   adjacent to a negation/requirement word** ("no designated", "not a
   designated immutable RC", "must designate", "BLOCKED: no designated
   RC") — i.e. imperative/absence text inside PR #1672's diff hunks and
   handoff prose, not a designation. No release-owner RC designation exists
   in this round's capture.
2. **A compliant soak cannot complete inside a bounded attempt.**
   `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (4 h) against this job's
   `timeout_s = 5400`, with background execution prohibited by lane rules.
   The only in-lane topology (host-preflight) is refused by
   `exact_rc_artifact` by design, so a longer in-lane run could not flip
   either failing row — it would only add a vanity duration number, which
   the issue's stop condition explicitly forbids.

## Linked-PR and develop position (re-confirmed from this round's capture)

- **#1567** closed/merged and **#1602** closed/merged: merge commits
  `394ff842`/`cfc515c14` verified ancestors of HEAD via
  `git merge-base --is-ancestor` (head SHAs `d22378795cf3`/`927a9c3c5bc6`
  are not themselves merge-reachable; ancestry is on the merge commits).
- **#1672** open draft at head `16b244414b01` — verified ancestor of HEAD.
- **#2100** closed/merged develop-side (head `b950e5933a28`, not an
  ancestor of HEAD); its soak-fixture fingerprints are carried here —
  `.gitleaksignore:69` `8185c1d0…` and `:96` `88edcc7e…` re-read this round.
- `git fetch origin` this round: `origin/develop = ed5613457` == **this
  round's dispatch base**; no new develop commits since dispatch, so this
  block was not a develop sync conflict and no merge was mandated.

## Escalation (unchanged in substance since round 26)

Resolving the two terminal rows requires exactly two external actions no
worker can take:

1. A **release owner designates the RC** under parent #89 (open, zero
   comments — no designation exists as of this round's 04:44Z capture).
2. A **release-owner-hosted ≥ 14,400 s soak of that exact Compose
   artifact**, whose observed image/configuration evidence satisfies
   `preflight_artifact_check` in a runner built for it.

Every row inside lane authority is evidenced and green at this head; the
soak harness, gates, and evidence chain show zero drift since the evidence
pack. Progress: checked 1 issue; done 0 acceptance-complete issues (8/10
rows evidenced, 2 externally blocked); skipped 0; validation-command errors
0; escalated 1 (the RC designation + production soak pair); inventory delta
0 (no tests added).
