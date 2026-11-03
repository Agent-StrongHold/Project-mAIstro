# Issue #860 — round 51 (job 53b66e48fe8e) independent re-validation at 16b244414

**Not promotion evidence or integration approval.** This round resolved the
previous failure — job `2a747750`: `state: failed`, `failure_kind:
worker_error` ("expected one MAISTRO_RESULT JSON line in final assistant
message"), i.e. a **reporting-format fault, not a validation finding** (its
own `checks` list is empty and its only error is the missing result record).
The job manifest again carried an **empty `checks` list** (no `check-*.log`
files in the round-51 job directory), so every result below was executed by
the worker directly at this round's starting head
`16b244414b010072faa1237698fb1eed6c3c258e` (clean on arrival). No source,
test, gate, ledger, or inventory file changed; the only artifact is this
handoff note. Inventory delta: 0 (no collected tests added or removed).

## Branch movement since round 50 (`3a055410d` → `16b244414`)

Two develop-sync merges, both content-verified:

- `5c4370e87` merges `0d49d4e06` (develop tip at round 50): M8/M9 research
  work, workflow changes, and package additions. This is why the broad
  `packages/` fence is now non-empty (see below).
- `16b244414` merges `cc6e4899d` (actions/upload-artifact 4→6, #2096):
  `.github/workflows/*.yml` only.

## Deterministic battery executed at `16b244414` (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped (includes the previously failing DDL-fence test) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked (count moved 1,326 → 1,323 with the develop merges; ledger matches scan) |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `uv run pytest tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 16 passed |
| `gitleaks detect --log-opts=cc6e4899d..HEAD` | no leaks found (280 commits) |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`; every
  required correctness gate is `ok=true` (exactly-once task admission: 12
  concurrent submissions → 1 distinct run id; exactly-once schedule
  occurrence: 0 occurrences with multiple runs; rate limit enforced with
  200/429 split; bounded LB failover; replica-2 rejoin; graceful drain with
  0 drain-5xx/conn errors; nonterminal runs after settle = 0; task admission
  availability).
- `sustain_duration` honestly fails: observed 420.09 s against the
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` floor (`run_soak.py:67`, gate at
  `run_soak.py:1601-1602`). `exact_rc_artifact` refuses the
  host-uvicorn-preflight topology by design (`preflight_artifact_check`,
  `run_soak.py:730`).
- Metrics are real series: 212 JSONL rows; **zero `"502"` strings** in the
  metrics JSONL and the evidence JSON; `kill_restart.window_status_counts`
  shows 200/202/401/404 only inside the 5.54 s kill window.
- `hashes.git_head` of the evidence pack is `3da4e035eb…`, verified with
  `git merge-base --is-ancestor` to be an ancestor of HEAD.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py`: only the round-43
  evidence-pack files themselves plus handoff notes 43–50 — **zero
  soak-runtime or gate-code drift** since capture.
- `git diff --name-only 3da4e035eb1f..HEAD -- deploy/`: **empty**.
- The broad `packages/` fence is now non-empty (develop merges): the
  round-43 evidence pack was not captured against the current package set —
  which is exactly what `exact_rc_artifact` already refuses, and why any
  future promotion requires a fresh soak of the exact RC artifact.

## Terminal blockers unchanged and external (re-derived from this round's capture)

- Parent #89 is **open** with **zero comments** (capture: 69 sources,
  2026-10-10T02:29:37Z). A regex sweep over all captured sources
  (`RC[-_ ]?(artifact|candidate|designat*|build)|candidate commit|release
  candidate`, 354 hits) finds only requirement text and absence records —
  **no RC designation exists anywhere**. Linked PR #1672 remains an **open
  draft** and its head now equals this branch's HEAD (`16b244414b01`).
- The two remaining acceptance rows — a ≥ 14,400 s sustained soak **of the
  exact RC artifact** #89 would promote — have no satisfiable object in this
  lane: `exact_rc_artifact` refuses host-preflight topology by design, only
  a release owner can designate the RC under #89, and a compliant ≥ 4 h soak
  cannot complete inside a bounded attempt (job budget 5,400 s; background
  execution prohibited). Rounds 26–50 hit the identical terminal pair.
- PR status re-confirmed from the capture: #1567 (`merged: true`, merge
  `394ff842`) and #1602 (`merged: true`, merge `cfc515c14`) are verified
  ancestors of HEAD — their content is already in this branch. #2100
  (`merged: true` 2026-10-10T02:09:32Z, `b950e5933a28`) is **not** an
  ancestor of this branch: it lives on develop and adds `.gitleaksignore`
  fingerprints for this lane's two historical soak fixtures so protected-
  branch `--all` scans stay clean. This branch already carries those exact
  fingerprints (`.gitleaksignore:69` and `:96`); a future develop merge will
  need the usual dedup attention (`7c6ae6149` precedent) but no action is
  required in this branch now.
- Develop drift re-measured after `git fetch origin develop`:
  `origin/develop` is exactly `007f09fbd` — **the dispatch base itself**, so
  there is no new develop movement to merge and the previous failure was
  not a sync conflict (no merge mandated by the lane brief). The 8 commits
  on develop since merge-base `cc6e4899d` were diffed: soak-path impact is
  `deploy/scripts/backup.sh` only (backup-permission hardening, not soak
  runtime); `git diff --name-only HEAD...origin/develop -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/` names
  nothing else on the soak path.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89, then a
release-owner-hosted ≥ 14,400 s production-Compose soak); inventory delta 0
(no tests added).
