# Issue #860 — round 52 (job d1159fa35) independent re-validation at a50b09c5d

**Not promotion evidence or integration approval.** This round resolved the
previous block — job `17aaa858`: `state: failed`, `failure_kind:
provider_error` ("Request timed out"), i.e. a **provider-transport fault,
not a validation finding** (its own `checks` list is empty and its only
error is the timeout). The job manifest for this round again carried **no
`check-*.log` files**, so every result below was executed by the worker
directly at this round's starting head `a50b09c5d6f284c27039f4cdeb27c952a
e033871` (clean on arrival; exactly the dispatch head). No source, test,
gate, ledger, or inventory file changed; the only artifact is this handoff
note. Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` re-confirmed 17/17 suites against the recorded
baseline).

## Branch movement since round 51 (`16b244414` → `a50b09c5d`)

None beyond round 51's own handoff commit (`a50b09c5d`, one markdown file).
All gates below therefore ran on the same tree round 51 validated.

## Deterministic battery executed at `a50b09c5d` (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped — **includes `test_ensure_schema_fences_ddl_behind_advisory_lock`, the test behind the stale round-44 `check-3.log` failure (24 == 21 DDL-count assertion); it is green at this head, re-confirmed independently after the round-51 claim** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `uv run pytest tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 16 passed |
| `gitleaks detect --log-opts=cc6e4899d..HEAD` | no leaks found (281 commits) |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`.
- Every required correctness gate is `ok=true`: exactly-once task admission
  (12 concurrent submissions → 1 distinct run id, 11 duplicates fenced);
  exactly-once schedule occurrence (0 occurrences with multiple runs);
  rate limit enforced (200/429 split, limit 3000 / remaining 0);
  `lb_failover_bounded`; `replica_2_rejoined`; graceful drain (`drained`,
  `drain_5xx: 0`, `drain_conn_errors: 0`); nonterminal runs after settle = 0;
  task admission availability.
- `sustain_duration` honestly fails: observed 420.09 s against the
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` floor (`run_soak.py:67`, gate at
  `run_soak.py:1601-1602`). `exact_rc_artifact` refuses the
  host-uvicorn-preflight topology by design (`preflight_artifact_check`,
  `run_soak.py:730`; reason: "not the exact production Compose image and
  configuration").
- Kill window is clean of 5xx: `window_status_counts` = 200×421, 202×25,
  401×25, 404×53 only; "502" appears nowhere in the evidence JSON.
  `fd_growth`/`rss_growth` are recorded informational series (bounded:
  fd 30→44/29→40, RSS +8.3%/+6.8% over the probe window), not promotion
  gates.
- `hashes.git_head` of the evidence pack is `3da4e035eb1f…`, verified with
  `git merge-base --is-ancestor` to be an ancestor of HEAD.

## Soak-path drift since the evidence head (`3da4e035e` → HEAD)

- `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py`: only the round-43
  evidence-pack files themselves plus handoff notes — **zero soak-runtime or
  gate-code drift** since capture.
- `git diff --name-only 3da4e035eb1f..HEAD -- deploy/`: **empty**.

## Terminal blockers unchanged and external (re-derived from this round's 69-source capture, 2026-10-10T02:53Z)

- Parent **#89 is open with zero comments** ("M3-A7 — Run RC soak and
  byte-equivalent final promotion"). A two-pass regex sweep over all 69
  captured sources (705 raw hits for RC/candidate language; all 22
  designation-language matches individually inspected) finds **only
  requirement text and absence records** ("release-owner decision: designate
  the RC…") — **no RC designation exists anywhere**.
- Linked PR status re-confirmed: **#1672 open draft**, head `16b244414b01`
  (= this branch's second parent, an ancestor of HEAD);
  **#1567** merged (merge `394ff842`, verified ancestor of HEAD); **#1602**
  merged (merge `cfc515c14`, verified ancestor of HEAD); **#2100** merged on
  develop (`b950e5933a28`, **not** an ancestor of this branch — develop-side)
  adding `.gitleaksignore` fingerprints this branch already carries
  (`.gitleaksignore:69` `8185c1d0…` and `:96` `88edcc7e…`); a future develop
  merge needs the usual dedup attention (`7c6ae6149` precedent), no action
  here.
- The two remaining acceptance rows — a ≥ 14,400 s sustained soak **of the
  exact RC artifact** #89 would promote — have no satisfiable object in this
  lane: `exact_rc_artifact` refuses host-preflight topology by design, only
  a release owner can designate the RC under #89, and a compliant ≥ 4 h soak
  cannot complete inside a bounded attempt (job budget 5,400 s; background
  execution prohibited). Rounds 26–51 hit the identical terminal pair.

## Develop drift re-measured this round

`origin/develop` moved since round 51: `007f09fbd` → `01cf44a5` — which is
**exactly this round's dispatch base**, so there is **no sync conflict and
no merge mandated** by the lane brief. The one new commit is #2104
(validate exact local MCP URL authorities): `mcp_client.py` + its tests +
an inventory note. Soak-path impact of `HEAD...origin/develop` remains
`deploy/scripts/backup.sh` only (backup-permission hardening, #2105,
already noted in round 51); `git diff --name-only HEAD...origin/develop --
scripts/soak docs/testing/soak tests/test_soak_promotion_gates.py deploy/`
names nothing else on the soak path.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0
(one transient module-import hiccup inside the replay harness resolved by
retry; all recorded results are from successful executions); escalated 1
(release-owner RC designation under parent #89, then a release-owner-hosted
≥ 14,400 s production-Compose soak of that exact artifact); inventory delta
0 (no tests added).
