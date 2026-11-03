# Issue #860 — round 129 (job 49a70dea) repair validation at the dispatched head 8b979c430

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `49a70dea58cf4d18bec329ad5f9d3206` (repair stage), dispatched
at head `8b979c43083caa5f4b212e69d314a4def9046145` (= the round-128 record
commit; `git status --porcelain` empty at start and at end + this record). The
prior repair attempt (job `afd4fa2327fe4c01ad73de7c09fc531f`) died on a
provider timeout (`result.json`: `failure_kind: provider_error`, agent timed
out) before executing anything, so no claim from that attempt existed to carry
forward. Every result below was produced fresh by this round at `8b979c430`,
independently of round 128's record, which was treated as claims to re-prove,
not evidence.

## Snapshot

- Start head `8b979c43083caa5f4b212e69d314a4def9046145` — exactly the
  dispatched head; working tree clean.
- Develop base `ab8b3737fa64` verified ancestor of HEAD
  (`git merge-base --is-ancestor` exits 0). Post-dispatch `git fetch origin
  develop` produced no new develop objects; `origin/develop` still resolves to
  `ab8b3737fa64`, also an ancestor of HEAD: **no develop drift, no sync
  conflict**.
- **Production identity binding intact**: `git diff --numstat
  5a59c724a..HEAD -- ':!docs' ':!*.md' ':!quality'` is **0 rows** and
  `git diff --numstat 5a59c724a..HEAD -- scripts/soak/` is **0 rows** —
  production and soak-gate code are byte-identical to the soaked head
  `5a59c724a`, so the round-109 evidence pack (`hashes.git_head = 5a59c724a…`,
  `git_clean = true`) remains bound at this head and the checks below ran the
  exact gate code the pack was validated with. The files that differ from
  `5a59c724a` are round-record documentation only.
- Relative to the develop base, `git diff --numstat ab8b3737fa64..HEAD --
  quality/` is **0 rows**: the vulture ledger is untouched this round.

## Stale verifier finding — re-tested, non-reproducing

The verifier failure carried into this lane
(`/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`:
`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) was
recorded at ancestor head `872fd2ce` on 2026-10-10. Re-executed fresh at
`8b979c430`:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -q` → **37 passed, 6 skipped** (rc=0).
- By-name re-run of `test_ensure_schema_fences_ddl_behind_advisory_lock` →
  **passes**: the test now asserts exact equality
  (`assert len(body) == len(expected_ddl)`, test line 191) against the full 24
  fenced statements, including the three Gauntlet audit columns
  `validated_evaluator_version`, `validation_run_ids`,
  `validation_content_hash` (test lines 177–179), matching the production
  `ensure_schema` body one-for-one inside the `pg_advisory_xact_lock` fence.
  The fence (#860 F7: one transaction, advisory lock first, all DDL inside)
  holds statement-by-statement. The finding is stale, not a live defect at
  this head.

## Deterministic battery at `8b979c430` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed (rc=0) |
| `uv run ruff format --check .` | 3,301 files already formatted (rc=0) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** in 2.46s |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -q` | **26 passed** in 2.09s |
| `uv run pytest tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance -q` | **passed** — documents honestly that each replica enforces its own allowance; `packages/maistro-server/src/maistro_server/api/rate_limit.py` states the N-replica aggregate is N× the configured limit and is "deliberately NOT advertised as cluster-wide" |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | **rc=0**: 1,322 reviewed identities → 1,322 findings, 0 unclassified, 0 never-allowlist; base `ab8b3737fa64`, candidate `8b979c43083c`; ledger unamended |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 backlog items parse, statuses/gaps/citations resolve (rc=0) |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves (rc=0) |
| `uv run python scripts/check-promotion-surface.py` | promotion surface: ok (rc=0) |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (re-derived live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py, imported in-process at
this head) applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json`
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical to
rounds 109–128. Re-verified from the raw pack document, field by field, this
round:

- Functional gates all hold in the pack:
  `exactly_once_tasks` (`ok: true` — 12 concurrent submissions → 12 delivered,
  1 distinct run id, 11 duplicate ids rejected),
  `exactly_once_schedule_claim` (`ok: true` — 1 occurrence → 1 run, 0
  multi-run occurrences, probe run cleanup terminal=cancelled),
  `rate_limit` probed on both direct replicas (authenticated 200×200 / 429×600
  with `x-ratelimit-limit: 3000` headers exhausted to 0 remaining),
  `kill_restart` (SIGTERM, `drained: true`, `drain_5xx: 0`,
  `drain_conn_errors: 0`, `rejoined: true`, `escalated: false`),
  `nonterminal_runs = "0"`, `final_runs_by_status = completed=2796
  cancelled=1`, FD growth bounded (30→36 / 29→34, max 41/39).
- Hash binding recomputed byte-for-byte this round: sha256 of the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf` = `86291c53ab2a81fd…` =
  pack `hashes.nginx_rendered_conf_sha256` (**MATCH**); pack `hashes.git_head
  = 5a59c724a…`, `git_clean = true`; and this HEAD's production tree is
  byte-identical to that pack head (0 diff rows above).
- `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs pack `sustain_seconds = 420.05`:
  `sustain_duration` fails **correctly** — round 109 was an intentional 420 s
  shakedown, not the required ≥4 h sustained soak.
- `exact_rc_artifact` fails **correctly**: the pack's topology is
  `host-uvicorn-preflight`, not "the exact production Compose image and
  configuration", because no RC artifact has been designated (below).

## External blockers (re-derived from this job's own dispatch-context.json, captured 2026-10-17T14:53:15Z — fresher than round 128's capture)

1. **`sustain_duration` — no authorized production window.** The promotion
   floor is a ≥4 h sustained soak (issue acceptance: "sustained load long
   enough to observe pool saturation, queue growth, lease expiry/reclaim
   …"). Round 109's 420.05 s shakedown intentionally does not satisfy it.
   A ≥4 h wall-clock soak cannot be executed inside a bounded worker job
   (background execution is prohibited), and scheduling the production
   observation window is a release-owner decision.
2. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comments** in this capture (updated 2026-09-22) — no RC candidate commit
   has been designated. RC PR #1672 is **open, `draft: true`, `merged:
   false`**, head `15ce4681c4d9` — not a promotable artifact. All 1,165
   comments on #860 in the captured scope are `maistro-progress` automation
   markers (newest `…:blocked` 2026-10-17T14:33:36Z); **zero**
   human/release-owner comments exist. Linked PRs #1567, #1602 and #2100 are
   closed **and merged**; #1672 remains the only unmerged soak-related PR.
   Designating an RC is a GitHub/release-owner action this worker must not
   perform (no GitHub mutations).

## Disposition

Round 128's NEEDS-DEEP-REVIEW block is **confirmed by independent
re-derivation at this head**, not carried forward. It is not a develop sync
conflict (both the lane base and the post-fetch `origin/develop` are ancestors
of HEAD). The one concrete verifier failure on this lane
(`test_pg_learnings.py` at `872fd2ce`) was re-executed and passes at this
head. There is nothing repairable in-repo: every deterministic gate is green,
the evidence pack is intact and hash-tied, production and soak-gate code are
byte-identical to the pack-bound head, and the two failing promotion gates
fail *correctly* — weakening them to force a pass would falsify the release
requirement this issue exists to enforce. The remaining work requires (a) a
release-owner-designated RC artifact under #89 (unblocking #1672 from
WIP/draft or designating another candidate), and (b) an authorized ≥4 h
production observation window for that exact artifact. Until both exist, this
issue stays externally blocked.

No code changes this round; this record is the only file touched.

Progress: `{checked: 9, done: 9, skipped: 0, errors: 0}` — 9 deterministic
gates/checks re-executed green, stale finding re-tested non-reproducing,
promotion gates re-derived live, external blockers re-derived from a fresher
capture. The single remaining action is outside this worker's authority.
