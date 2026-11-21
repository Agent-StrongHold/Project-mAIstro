# Issue #860 — round 54 (job 3982369102) independent re-validation at ded737b56

**Not promotion evidence or integration approval.** This round was dispatched
to resolve the round-53 escalation (worker requested attention:
NEEDS-DEEP-REVIEW). The escalation was re-examined from scratch and is
confirmed **external and unchanged**: it cannot be discharged by any repair
worker; it requires a release-owner decision under parent #89 plus a
production-hosted soak. Verdict remains NEEDS-DEEP-REVIEW — a further BLOCKED
repair loop cannot substitute for the review the escalation requests.

The driver manifest for this round again carried an **empty `checks` list**
(no `check-*.log` files were produced for this job), so every result below
was executed by the worker directly at the starting head `ded737b56` (the
round-53 end head; working tree clean on arrival, exactly the dispatch head).
No source, test, gate, ledger, or inventory file changed; the only artifact
is this handoff note. Inventory delta: 0 (no collected tests added or
removed).

## Deterministic battery executed at `ded737b56` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped — the stale round-44 `check-3.log` DDL-fence test (`test_ensure_schema_fences_ddl_behind_advisory_lock`) re-confirmed green |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-doc-links.py` | 2,284 markdown files, 0 broken relative links |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`.
- All eight correctness gates `ok=true` in the pack's
  `thresholds.checks`: exactly-once task admission, exactly-once schedule
  occurrence, rate limit enforced, `lb_failover_bounded`,
  `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `graceful_drain`.
- `sustain_duration` honestly fails: `observed_seconds=420.09` against
  `minimum_seconds=14400` (`PROMOTION_MIN_SUSTAIN_SECONDS`, `run_soak.py:67`).
- `exact_rc_artifact` refuses the host-uvicorn-preflight topology by design
  (`preflight_artifact_check`, `run_soak.py:730-745`): *"There is
  deliberately no CLI override: an exact-RC runner needs its own observed
  image/configuration evidence before this gate can be satisfied."*
- `hashes.git_head` of the pack is `3da4e035eb1f…`, verified this round via
  `git merge-base --is-ancestor` to be an ancestor of HEAD.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/`: only
  evidence-pack/handoff markdown under `docs/testing/soak/` — **zero
  soak-runtime or gate-code drift** since capture; `deploy/` diff is empty.
- Develop-side diff over the same paths (`HEAD...origin/develop`): only
  `deploy/scripts/backup.sh` (#2105 backup-permission hardening; not
  soak-runtime).

## External pair re-derived from this round's own capture (2026-10-10T03:45Z, 69 sources)

The two failing rows are the issue's own terminal pair: *"Run sustained load
long enough to observe …"* and *"Include at least one long-running soak of
the exact RC artifact/configuration that #89 would promote."*

1. **No RC exists to soak.** Parent **#89 is open with zero comments**
   (captured fresh this round: `issues/89` state=open, comments=0). A
   designation-language sweep over all 69 captured sources (2,310 broad
   RC-token hits across 16 sources) found 16 designation-regex matches and
   **every one is imperative/requirement text** ("release owner designates
   the RC…", "Resolution requires a release-owner decision: designate the
   RC…") inside PR #1672's file-diff hunks — i.e. the lane's own handoff
   prose, not a designation. No release-owner RC designation exists in the
   capture.
2. **A compliant soak cannot complete inside a bounded attempt.**
   `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (4 h) against a 5,400 s job
   budget, with background execution prohibited by lane rules. The only
   in-lane topology (host-preflight) is refused by `exact_rc_artifact` by
   design, so a longer in-lane run could not flip either failing row — it
   would only add a vanity duration number, which the issue's stop
   condition explicitly forbids.

## Linked-PR and develop position (re-confirmed this round)

- **#1567** merged (merge `394ff842`) and **#1602** merged (merge
  `cfc515c14`): both merge commits verified ancestors of HEAD via
  `git merge-base --is-ancestor`. Note: the PR *head* SHAs
  (`d22378795cf3`, `927a9c3c5bc6`) are themselves not merge-reachable —
  their content landed via the verified merge commits — so ancestry is
  claimed (and verified) on the merge commits, not the head SHAs.
- **#1672** open draft, head `16b244414b01` — an ancestor of HEAD.
- **#2100** merged develop-side (`b950e5933a28`, not an ancestor of HEAD);
  its soak-fixture fingerprints are carried here (`.gitleaksignore:69`
  `8185c1d0…`; `:96` `88edcc7e…` — re-read this round).
- `origin/develop` moved `01cf44a5` → `790f343` since round 53 and equals
  **this round's dispatch base** (security batch #2098/#2101/#2103–#2106;
  10 develop-side commits). Only soak-adjacent overlap is
  `deploy/scripts/backup.sh`. The lane brief mandates a develop merge only
  for a develop sync conflict; this block was the external terminal pair,
  not a conflict. No merge performed.

## Escalation (unchanged in substance since round 26)

Resolving the two terminal rows requires exactly two external actions no
worker can take:

1. A **release owner designates the RC** under parent #89 (open, zero
   comments — no designation exists as of this round's 03:45Z capture).
2. A **release-owner-hosted ≥ 14,400 s soak of that exact Compose
   artifact**, whose observed image/configuration evidence satisfies
   `preflight_artifact_check` in a runner built for it.

Every row inside lane authority is evidenced and green at this head; the
soak harness, gates, and evidence chain show zero drift since the evidence
pack. Progress: checked 1 issue; done 0 acceptance-complete issues (8/10
rows evidenced, 2 externally blocked); skipped 0; validation-command errors
0; escalated 1 (the RC designation + production soak pair); inventory delta
0 (no tests added).
