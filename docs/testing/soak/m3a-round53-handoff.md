# Issue #860 — round 53 (job 3a4e428e4) independent re-validation at 7dc161a22

**Not promotion evidence or integration approval.** This round was dispatched
to resolve the round-52 block (worker requested attention: BLOCKED). The
block was re-examined from scratch and is confirmed **external** — it cannot
be discharged by any repair worker; it requires a release-owner decision
under parent #89 plus a production-hosted soak. This handoff records the
fresh evidence and escalates accordingly (verdict: NEEDS-DEEP-REVIEW, not a
retryable repair).

The driver manifest for this round again carried an **empty `checks` list**
(no `check-*.log` files were produced for this job), so every result below
was executed by the worker directly at this round's starting head
`7dc161a22fe0d9b2877c7186bf542565e073e880` (working tree clean on arrival;
exactly the dispatch head). The only reference to `check-*.log` in the lane
brief — a round-44 DDL-fence failure — is stale and was re-verified green
directly (see battery). No source, test, gate, ledger, or inventory file
changed; the only artifact is this handoff note. Inventory delta: 0 (no
collected tests added or removed).

## Deterministic battery executed at `7dc161a22` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped — includes `test_ensure_schema_fences_ddl_behind_advisory_lock`, the test behind the stale round-44 `check-3.log` (`24 == 21` DDL-count assertion); green at this head, independently re-confirmed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked — no amendment needed |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`.
- Every correctness gate is `ok=true`: exactly-once task admission
  (12 concurrent submissions → 1 distinct run id), exactly-once schedule
  occurrence (0 multi-run occurrences), rate limit enforced (200/429 split),
  `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`,
  `graceful_drain`.
- `sustain_duration` honestly fails: observed 420.09 s against
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`run_soak.py:67`, gate at
  `run_soak.py:1601-1602`).
- `exact_rc_artifact` refuses the host-uvicorn-preflight topology by design
  (`preflight_artifact_check`, `run_soak.py:730-745`): *"There is
  deliberately no CLI override: an exact-RC runner needs its own observed
  image/configuration evidence before this gate can be satisfied."*
- `hashes.git_head` of the evidence pack is `3da4e035eb1f…`, verified with
  `git merge-base --is-ancestor` to be an ancestor of HEAD.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py`: only the round-43
  evidence-pack files themselves plus round-43…52 handoff notes — **zero
  soak-runtime or gate-code drift** since capture.
- `git diff --name-only 3da4e035eb1f..HEAD -- deploy/`: **empty**.
- `git diff --name-only HEAD...origin/develop -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/`: only
  `deploy/scripts/backup.sh` (develop-side #2105 backup-permission
  hardening; not soak-runtime).

## Why the block cannot be resolved in-lane (re-derived from this round's 69-source capture, 2026-10-10T03:21Z)

The two failing rows are the issue's own terminal pair: *"Run sustained load
long enough to observe …"* and *"Include at least one long-running soak of
the exact RC artifact/configuration that #89 would promote."*

1. **No RC exists to soak.** Parent **#89 is open with zero comments**
   ("M3-A7 — Run RC soak and byte-equivalent final promotion"). A regex
   sweep over all 69 captured sources found 16 sources carrying
   RC/candidate language and exactly **one** designation-language match —
   a gitleaks-fingerprint diff hunk in PR #1672's file listing, not a
   designation. **No release-owner RC designation exists anywhere in the
   capture.** The soak's object ("the exact RC artifact that #89 would
   promote") does not exist; fabricating a candidate in-lane would violate
   the gate's own evidence rule (observed image/configuration from an
   exact-RC runner) and the issue's stop condition.
2. **A compliant soak cannot complete inside a bounded attempt.**
   `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (4 h) against a 5,400 s job
   budget, with background execution prohibited by lane rules. Even the
   best available in-lane topology (host-preflight) is refused by
   `exact_rc_artifact` by design, so a longer in-lane run could not
   flip either failing row — it would only add a vanity duration number,
   which the issue's stop condition explicitly forbids.

Rounds 26–52 hit the identical terminal pair; this round re-derived it from
fresh evidence rather than inheriting the claim.

## Linked-PR and develop position (re-confirmed this round)

- **#1672** open draft, head `16b244414b01` — an ancestor of this branch
  (second parent of `16b244414`).
- **#1567** merged (merge `394ff842`) and **#1602** merged (merge
  `cfc515c14`) — both verified ancestors of HEAD via
  `git merge-base --is-ancestor`.
- **#2100** merged develop-side (`b950e5933a28`, **not** an ancestor of
  HEAD); its soak-fixture fingerprints are already carried here
  (`.gitleaksignore:69` `8185c1d0…`; `:96` `88edcc7e…` block).
- Latest #860 comments are bot progress markers only (last:
  2026-10-10T03:05:10Z, the round-52 blocked marker).
- `origin/develop` == `01cf44a5` == **this round's dispatch base**. The
  branch is 9 commits behind develop (MCP-authority #2104 et al.) with
  `deploy/scripts/backup.sh` as the only soak-adjacent overlap, but the
  lane brief mandates a develop merge **only for a develop sync conflict**,
  and the block was a worker BLOCKED request on the external terminal pair —
  not a conflict. No merge performed.

## Escalation (unchanged in substance since round 26, now routed for review)

Resolving the two terminal rows requires exactly two external actions no
worker can take:

1. A **release owner designates the RC** under parent #89 (currently open
   with zero comments — no designation exists).
2. A **release-owner-hosted ≥ 14,400 s soak of that exact Compose
   artifact**, whose observed image/configuration evidence satisfies
   `preflight_artifact_check` in a runner built for it.

Every row inside lane authority is evidenced and green at this head; the
soak harness, gates, and evidence chain show zero drift since the evidence
pack. Progress: checked 1 issue; done 0 acceptance-complete issues (8/10
rows evidenced, 2 externally blocked); skipped 0; validation-command errors
0; escalated 1 (the RC designation + production soak pair); inventory delta
0 (no tests added).
