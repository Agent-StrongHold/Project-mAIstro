# Issue #860 — round 46 (job 893b9c3d) independent re-validation at 47e956b4c

**Not promotion evidence or integration approval.** This round independently
re-executed the deterministic gate battery at this round's starting head
`47e956b4cffd5242901ca41c0f8275f471610c3a` (clean on arrival, one commit ahead
of round 45's `eebc5c067`), re-verified the stale `98a11313/check-3.log`
failure against that head, replayed the promotion-gate evaluator against the
committed round-43 evidence pack, and re-derived the terminal-blocker status
from this round's own dispatch capture — trusting no earlier round's claims.
No source, test, gate, ledger, or inventory file changed; the only artifact is
this handoff note.

## Stale driver failure re-checked at `47e956b4c` (resolved)

`98a11313/check-3.log` (verify job at `872fd2cea`) failed
`packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`
with `assert 24 == 21`. Re-executing the job's exact argv at this head:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -q -x` → **38 passed, 6 skipped**. The failure is stale; the schema-fence
  fix `cd77bb81c` is an ancestor of HEAD (`git merge-base --is-ancestor` →
  true, executed this round).

## Deterministic battery re-executed at `47e956b4c` (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| Suite inventory `--suite packages/maistro-core/tests` | ok |
| Suite inventory `--suite packages/maistro-server/tests` | ok |
| Full `scripts/check-suite-inventory.py` | ok: 17/17 suites |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,326/1,326 reviewed identities banked |
| `scripts/check-doc-links.py` | 0 broken relative links |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | **81 passed** |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` imported live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`; the
  other eight gates are `ok=true` (exactly-once task admission, exactly-once
  schedule occurrence, rate-limit enforcement, LB failover bound, replica-2
  rejoin, zero nonterminal runs after settle, admission availability,
  graceful drain).
- `sustain_duration`: observed 420.09 s vs minimum 14,400 s.
- `exact_rc_artifact`: reason "not the exact production Compose image and
  configuration"; `preflight_artifact_check()` returns `ok=false` /
  `host-uvicorn-preflight` **by design** — the docstring records there is
  deliberately no CLI override, and `m3a-load-profile.md` states the harness
  is a preflight emulator that cannot sign a promotion soak.
- Evidence numbers re-read from the pack (not quoted from prior rounds):
  `requests_total` 49,151 over 5 kinds; p95 ≤ 47.19 ms per kind;
  `task_admission_ratio` 1.0; 12 concurrent task submissions → 1 distinct run
  id (11 duplicates); per-replica rate-limit probes against
  `127.0.0.1:18201`/`:18202` with `x-ratelimit-*` headers; kill/restart drain
  record present; `hashes.git_head` = `3da4e035eb…`, verified ancestor of
  HEAD.
- Findings row: load-discovered defects were fixed in-repo with tests
  (F7 learnings schema fence — the very test above — F10 LB retry fix, drain
  probe, harness hardening); external filing is prohibited in this lane.

## Terminal blockers unchanged and external

Re-derived from this round's own dispatch capture (not prior claims): parent
#89 is **open** and requires RC artifacts "built only from the candidate
commit"; no RC designation exists anywhere in the capture — linked PRs
#1567/#1602 are closed unmerged and #1672 is an open draft; the latest issue
comments are progress markers only. The two remaining acceptance rows
(≥ 14,400 s soak of the exact RC artifact that #89 would promote, and the
RC-binding half of sustained observation) therefore have no satisfiable
object in this lane: `exact_rc_artifact` refuses host-preflight topology by
design. Rounds 26–46 hit the identical terminal pair. Any further in-lane
attempt would re-run the same gates at a new head without moving acceptance.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89); inventory delta
0 (no tests added).
