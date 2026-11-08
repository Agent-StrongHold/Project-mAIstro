# Issue #860 — round 49 (job 779923b1) independent re-validation at 831cc2349

**Not promotion evidence or integration approval.** This round re-executed the
full deterministic gate battery at this round's starting head
`831cc23497319269789f8343e58356d7504f27e9` (clean on arrival; one docs-only
commit ahead of round 48's `16d25eaaf`), replayed the promotion-gate evaluator
against the committed round-43 evidence, and re-derived the external-blocker
status from this round's own dispatch capture (61 sources, captured
2026-10-09T11:42:19Z). No source, test, gate, ledger, or inventory file
changed; the only artifact is this handoff note. Inventory delta: 0 (no
collected tests added or removed).

Note on the dispatch: this round's job manifest again carried an **empty
`checks` list** (no `check-*.log` files in the job directory), so every result
below was executed by the worker directly — none is inherited from a driver
log or an earlier round's claim.

## Deterministic battery executed at `831cc2349` (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| Driver pair `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | 38 passed, 6 skipped |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites, 0 byte-identical groups |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,326/1,326 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `uv run pytest tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 16 passed |
| `gitleaks detect --log-opts=0d49d4e0..HEAD` | no leaks found (278 commits) |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`; every
  required correctness gate is `ok=true` (exactly-once task admission and
  schedule occurrence, rate limit enforcement, bounded LB failover,
  replica-2 rejoin, graceful drain, nonterminal runs after settle, task
  admission availability with ratio 1.0).
- Recorded metrics are real series, not placeholders: `requests_total`
  49,151; per-kind p95 ≤ 47.19 ms; FD series 30→38 / 29→35 (max 44/40);
  RSS +8.3% / +6.8%; status counts 200/202/401/404.
- `sustain_duration` honestly fails: observed 420.09 s against the 14,400 s
  minimum. `exact_rc_artifact` refuses the host-uvicorn-preflight topology by
  design ("not the exact production Compose image and configuration").
- `hashes.git_head` of the evidence pack is `3da4e035eb…`, verified with
  `git merge-base --is-ancestor` to be an ancestor of HEAD, so the replayed
  evidence is tied to this line of development.

## Terminal blockers unchanged and external (re-derived from this round's capture)

- Parent #89 is **open** with **zero comments** and requires "RC artifacts are
  built only from the candidate commit". A full regex sweep of all 61 captured
  sources finds no RC designation anywhere — every "RC artifact / candidate
  commit" mention is the requirement text of #860/#89 itself, not a
  designation. Linked PR #1672 remains an **open draft** (head `5daebe7e`).
- The two remaining acceptance rows — a ≥ 14,400 s sustained soak **of the
  exact RC artifact** #89 would promote — have no satisfiable object in this
  lane. `exact_rc_artifact` refuses host-preflight topology by design, and
  only a release owner can designate the RC artifact under #89. Additionally,
  a compliant ≥ 4 h soak cannot complete inside a bounded attempt (this job's
  own manifest budget is 5,400 s and background execution is prohibited), so
  the sustained soak requires a release-owner-coordinated long-running
  execution once the RC exists. Rounds 26–49 hit the identical terminal pair.
- PR status re-confirmed: #1567 (merge `394ff842`) and #1602 (merge
  `cfc515c14`) are merged into develop and both merge commits are verified
  ancestors of HEAD — their content is already in this branch. The 25-commit
  divergence behind `origin/develop` is other lanes' M8/M9 research work;
  `git diff --name-only HEAD...origin/develop` shows **zero** soak-path
  changes (`scripts/soak`, `docs/testing/soak`, soak suites, `deploy/`), so no
  re-soak or evidence invalidation follows, and the previous block was not a
  develop sync conflict.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89); inventory
delta 0 (no tests added).
