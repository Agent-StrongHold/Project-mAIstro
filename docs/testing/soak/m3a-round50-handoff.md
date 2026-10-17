# Issue #860 — round 50 (job c2ba70c14b82) independent re-validation at 3a055410d

**Not promotion evidence or integration approval.** This round resolved the
previous block — which was a **provider timeout** (job `34e20458`: `state:
failed`, `failure_kind: provider_error`), not a validation finding — by
re-executing the full battery at this round's starting head
`3a055410daaa6f53aac6ed417d018eb6148caf85` (clean on arrival). The job
manifest again carried an **empty `checks` list** (no `check-*.log` files),
so every result below was executed by the worker directly. No source, test,
gate, ledger, or inventory file changed; the only artifact is this handoff
note. Inventory delta: 0 (no collected tests added or removed).

The stale "Validation failed … check-3.log" pointer from job `98a11313` was
opened and read: it recorded
`test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`
failing (`assert 24 == 21` DDL calls behind the advisory lock). That test is
**green at this head** as part of the driver pair below — the failure is
repaired, not assumed.

## Deterministic battery executed at `3a055410d` (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped (includes the previously failing DDL-fence test) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,326/1,326 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `uv run pytest tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 16 passed |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`; every
  required correctness gate is `ok=true` (exactly-once task admission and
  schedule occurrence, rate limit enforcement, bounded LB failover with 0
  5xx/conn errors in a 5.54 s kill window, replica-2 rejoin, graceful drain,
  nonterminal runs after settle, task admission availability).
- `sustain_duration` honestly fails: observed 420.09 s against the
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` floor (`run_soak.py:67`, gate
  written at `run_soak.py:1599-1603`). `exact_rc_artifact` refuses the
  host-uvicorn-preflight topology by design (`preflight_artifact_check`,
  "deliberately no CLI override").
- Metrics are real series: 212 JSONL rows; `requests_total` 49,151 with
  status counts 200/202/401/404 and **zero 502s** (F3's run-1 502 storm was
  root-caused in round 5 to the soak-cell LB conf naming
  (`host.docker.internal` IPv6/IPv4 flapping into `max_fails`), fixed by the
  rendered IPv4-literal conf; production `deploy/nginx.conf` uses compose
  service names and is immune).
- `hashes.git_head` of the evidence pack is `3da4e035eb…`, verified with
  `git merge-base --is-ancestor` to be an ancestor of HEAD, and
  `git diff --name-only 3da4e035eb1f..HEAD -- scripts/soak packages/ deploy/
  tests/test_soak_promotion_gates.py` is **empty** — the replayed evidence
  is tied to this line of development with no soak-path drift since capture.

## Terminal blockers unchanged and external (re-derived from this round's capture)

- Parent #89 is **open** with **zero comments** and requires "RC artifacts
  are built only from the candidate commit". A regex sweep over all 61
  captured sources finds no RC designation — every hit outside the
  requirement text is an *absence record* inside PR #1672's own diff
  (prior rounds' handoff notes). Linked PR #1672 remains an **open draft**
  (head `5daebe7e`, `draft: true`).
- The two remaining acceptance rows — a ≥ 14,400 s sustained soak **of the
  exact RC artifact** #89 would promote — have no satisfiable object in this
  lane: `exact_rc_artifact` refuses host-preflight topology by design, only
  a release owner can designate the RC under #89, and a compliant ≥ 4 h soak
  cannot complete inside a bounded attempt (job budget 5,400 s; background
  execution prohibited). Rounds 26–50 hit the identical terminal pair.
- PR status re-confirmed from the capture: #1567 and #1602 are
  `merged: true`, and both merge commits (`394ff842`, `cfc515c14`) are
  verified ancestors of HEAD — their content is already in this branch.
- Develop drift re-measured after `git fetch origin develop`:
  `origin/develop` is exactly `0d49d4e0` — the dispatch base itself. The
  branch is 329 commits ahead / 25 behind the pre-fetch tracking ref; the
  25 commits are other lanes' M8/M9 research work with **zero** soak-path
  changes (`git diff --name-only HEAD...origin/develop -- scripts/soak
  docs/testing/soak tests/test_soak_promotion_gates.py deploy/` is empty).
  The previous block was **not** a develop sync conflict; no merge is
  required by the lane brief.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89, then a
release-owner-hosted ≥ 14,400 s production-Compose soak); inventory delta 0
(no tests added).
