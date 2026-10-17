# Issue #860 — round 59 (job 2adbd51b) independent re-validation at 128a0405

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `128a0405add8b2e98d2582ae47cf86af99ad15ec`
(working tree clean on arrival, exactly the dispatch head) and re-derives the
terminal external pair from this round's own 69-source capture
(2026-10-10T06:30–06:33Z, dispatch-context sha256 `ce3d9eba08ed8110…`). The
round-53 escalation (NEEDS-DEEP-REVIEW) remains **external and unchanged**:
acceptance rows 3 and 8 require a release-owner RC designation under parent
#89 plus a release-owner-hosted ≥14,400 s soak of the exact production Compose
artifact, neither of which any repair worker can supply.

Prior-run facts resolved this round: the immediately preceding job `c96c9c7e`
died on a **provider timeout** (`failure_kind: provider_error`, `checks: []`,
agent_exit 0) before touching the tree — its head was this same `128a0405`, so
nothing was lost or salvaged; and this round's driver manifest again carried an
**empty `checks` list** (no `check-*.log` files exist for job `2adbd51b`),
superseded by direct full-battery execution below. The prompt's "Validation
failed" pointer again referenced job `98a11313`'s `check-3.log` — the same
**stale round-44 artifact** whose DDL-fence failure predates the current head
and was re-executed green this round (below). No source, test, gate, ledger, or
inventory file changed; the only artifact is this handoff note. Inventory
delta: 0 (no collected tests added or removed).

## Deterministic battery executed at `128a0405` (all green, this round)

| Gate | Result |
| --- | --- |
| `git fetch origin` + `rev-parse origin/develop` | `1f328be9` == this round's dispatch base. It is **not** an ancestor of HEAD (merge-base `cc6e4899`): the 12 develop-side commits are the security/WIP batch `60c011a45..1f328be96` (296 files). Only soak-adjacent path in the batch is `deploy/scripts/backup.sh` (#2105); zero develop-side overlap with `scripts/soak/`. This lane's failures were provider timeouts / empty driver checks, never a sync conflict, so per the dispatch rule **no merge is mandated** |
| Evidence-head ancestry `git merge-base --is-ancestor 3da4e035 HEAD` | true |
| Soak-path drift `git diff --name-only 3da4e035..HEAD -- scripts/soak/ deploy/ tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py` | empty — runtime/gate/deploy trees byte-identical since the evidence head |
| Stale `check-3.log` failure file: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 37 passed, 6 skipped — the round-44 DDL-fence failure does not reproduce at this head |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py tests/test_release_guard.py -q` | 105 passed |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match recorded inventory (30,805 unique identities) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1057) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `uv run radon cc packages/*/src -i third_party --min B --total-average` (quality.yml:834) | 12,732 blocks, average A (2.968) |
| `scripts/check-doc-links.py` | Every relative markdown link resolves (0 broken) |

## Promotion replay (live gate code, this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`:

- `sustain_duration`: observed 420.09 s vs `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (`run_soak.py:67`) — `ok: false`. No env/CLI override exists (the constant is
  read directly by the gate; `os.environ` appears only as subprocess plumbing).
- `exact_rc_artifact`: `ok: false`, `topology: host-uvicorn-preflight`, reason
  "not the exact production Compose image and configuration" — the refusal in
  `preflight_artifact_check` is deliberate and carries no CLI override.
- All 8 correctness gates `ok: true` (`exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, `graceful_drain` with `drain_5xx: 0`,
  SIGTERM required and drained, no escalation).
- Pack provenance: `hashes.git_head = 3da4e035eb1f46093d507db0f90b131a3a8d6dbe`;
  file added once by `215bdec8a` and never modified; `3da4e035` is an ancestor
  of this round's HEAD.

## External pair re-derived from this round's own capture

- Parent #89 "M3-A7 — Run RC soak and byte-equivalent final promotion":
  **open, 0 comments** — no RC designation exists at the promotion authority.
- PR #1672 (this issue's soak implementation PR): **open draft** at
  `16b244414b` — not merged, not a designation.
- PRs #1567, #1602, #2100: closed **merged**; none designates an RC artifact.
- Designation-language regex (`release.candidate|\bRC\b|designat|promote
  the|…`) across all 754 captured #860 comment records: **0 hits**. Most recent
  comment activity (06:06–06:14Z) is driver progress markers for job
  `050a5645` only.

## Why neither failing row is reachable in-lane

Satisfying `sustain_duration` requires one continuous ≥14,400 s soak of the
exact RC artifact; the lane job budget is 5,400 s and background execution is
prohibited, so no in-lane run can flip the row. Satisfying
`exact_rc_artifact` additionally requires a release-owner RC designation under
parent #89 (still open, 0 comments) — a governance act outside this lane's
authority. Weakening either gate is prohibited. The escalation routing
(NEEDS-DEEP-REVIEW) is therefore unchanged.
