# Issue #860 — round 124 (job e792c98b) validation at the dispatched head 17c6409d4

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `e792c98b8b304bf59bd6532c452c6d85`, dispatched at head
`17c6409d4` (= the round-123 record commit; `git status --porcelain` empty at
start and at end + this record). The prior attempt at this lane
(`d480e984e72146f18c05fa94935139f1`) died on a provider timeout before running
any checks (`"checks": []`), so every result below was produced fresh by this
round, independently of round 123's record — no validation result is carried
forward unverified. Prior artifact read:
`/home/dev/maistro/jobs/d480e984e72146f18c05fa94935139f1/result.json`
(verdict: provider-error failure, no checks). The stale `98a11313` `check-3.log`
finding (pg_learnings schema fence) is formally re-closed at this head by the
named test below.

## Snapshot

- Start head `17c6409d4` — exactly the dispatched head; working tree clean.
- Develop base `ab8b3737fa64` verified ancestor of HEAD
  (`git merge-base --is-ancestor` passes): **no develop drift, no sync
  conflict**. The standing "BLOCKED" attention request from round 123 is not a
  merge conflict (see Disposition).
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md'` is **0 rows** — production code is
  byte-identical to the soaked head `5a59c724a`, so the round-109 evidence
  pack (`hashes.git_head = 5a59c724a…`, `git_clean = true`) remains bound at
  this head.
- Relative to the develop base, 12 non-docs files changed (the soak harness
  `run_soak.py`/`nginx-soak.conf`, the pg_learnings schema fence + test, the
  tasks backpressure + test, the gitleaksignore contract + prod-stack boot
  contract tests, `deploy/nginx.conf`, `.gitleaksignore`, one backlog test);
  **no `quality/*.json` rows were added, removed, or amended** (numstat vs
  base on `quality/` = 0 rows).

## Deterministic battery at `17c6409d4` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` + `packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`, re-run by name | **3 passed** — formally re-proves the #842 replica-selection allowance and closes the stale `98a11313` `check-3.log` finding (24 vs 21 DDL-statement assertion) at this head |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings, no unclassified; base `ab8b3737fa64`, candidate `17c6409d4899`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (reproduced live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py) applied in-process at
this head to `docs/testing/soak/evidence/m3a-round109-shakedown.json` returns
exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical to rounds
109–123. `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs pack
`sustain_seconds = 420.05`; the pack's own
`thresholds.checks.exact_rc_artifact = {ok: false, topology:
"host-uvicorn-preflight"}`. Re-verified from the raw pack document, field by
field:

- Functional gates all true: `exactly_once_task_admission` (1 distinct
  `run_id` `4dd5e99c…` across duplicate submissions),
  `exactly_once_schedule_occurrence = true`, `rate_limit_enforced = true`,
  `replica_2_rejoined = true`, `lb_failover_bounded` (observed 5xx +
  conn-errors **0** vs budget 4320.0 over a 6.58 s kill window),
  `nonterminal_runs_after_settle` (count 0; final runs 2796 completed /
  1 cancelled), `task_admission_availability` (ratio 1.0, 2764/2764 outside
  the kill window), `graceful_drain` (`required = true`, SIGTERM,
  `drained = true`, `drain_5xx = 0`, `drain_conn_errors = 0`).
- Hash binding recomputed byte-for-byte this round: sha256 of the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf` =
  `86291c53ab2a81fd…` = pack `hashes.nginx_rendered_conf_sha256`
  (**MATCH**); pack `hashes.git_head = 5a59c724a…`, `git_clean = true`.

## External blockers (re-derived from dispatch-context.json, captured 2026-10-17T12:47–12:50Z)

1. **`sustain_duration` — no authorized production window.** The promotion
   floor is a ≥4 h sustained soak (issue acceptance: "sustained load long
   enough to observe pool saturation, queue growth, lease expiry/reclaim
   …"). Round 109's 420.05 s shakedown intentionally does not satisfy it.
   A ≥4 h wall-clock soak cannot be executed inside a bounded worker job
   (background execution is prohibited; the synchronous budget is far below
   4 h), and scheduling the production observation window is a
   release-owner decision that appears nowhere in the captured state.
2. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open
   with 0 comments** — no RC candidate commit has been designated. RC PR
   #1672 is **open, `draft: true`**, head `15ce4681c4d9`, updated
   2026-10-16 — not a promotable artifact. All 1,151 comments on #860 are
   `maistro-progress` automation markers from a single account (newest
   2026-10-17T12:32:29Z, the round-123 job's `blocked` marker); **zero**
   human/release-owner comments exist anywhere in the captured scope.
   Designating an RC is a GitHub/release-owner action this worker must not
   perform (no GitHub mutations).

## Disposition

Round 123's BLOCKED determination is **confirmed by independent re-derivation
at this head**, not carried forward. It is not a develop sync conflict (base
verified ancestor), and there is nothing repairable in-repo: every
deterministic gate is green, the evidence pack is intact and hash-tied, and
the two failing promotion gates fail *correctly* — weakening them to force a
pass would falsify the release requirement this issue exists to enforce.
The remaining work requires (a) a release-owner-designated RC artifact under
#89 (unblocking #1672 from WIP/draft or designating another candidate), and
(b) an authorized ≥4 h production observation window for that exact
artifact. Until both exist, this issue stays externally blocked.

No code changes this round; this record is the only file touched.
