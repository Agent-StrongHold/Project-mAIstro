# Issue #860 — round 47 (job bcade8c52) independent re-validation at 601a1f60f

**Not promotion evidence or integration approval.** This round re-executed the
full deterministic gate battery at the round's starting head
`601a1f60f3c1048c12da0aeae592a25a694f41be` (clean on arrival, one commit ahead
of round 46's `47e956b4c`), re-verified the stale `98a11313/check-3.log`
failure against that head, replayed the promotion-gate evaluator against the
committed round-43 evidence, and re-derived the external-blocker status from
this round's own dispatch capture. No source, test, gate, ledger, or inventory
file changed; the only artifact is this handoff note. Inventory delta: 0 (no
collected tests added or removed).

Note on the dispatch: this round's own job manifest carried an **empty
`checks` list** (the driver executed no deterministic checks), so every result
below was executed by the worker directly — none is inherited from a driver
log.

## Stale driver failure re-checked at `601a1f60f` (resolved)

`98a11313/check-3.log` (verify job at `872fd2cea`) failed
`packages/maistro-core/tests/persistence/test_pg_learnings.py::
test_ensure_schema_fences_ddl_behind_advisory_lock` with `assert 24 == 21`.
Re-executing the driver's exact argv at this head:

- `uv run pytest packages/maistro-core/tests/persistence/
  test_pg_learnings.py packages/maistro-server/tests/api/
  test_tasks_concurrency_backpressure.py -q -x` → **38 passed, 6 skipped**;
  the named fence test passes in isolation (**1 passed**). Stale.

## Deterministic battery executed at `601a1f60f` (all green)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | resolved 256, checked 214 |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| Driver pytest pair (exact argv above) | 38 passed, 6 skipped |
| `check-suite-inventory.py --suite packages/maistro-core/tests` | ok |
| `check-suite-inventory.py --suite packages/maistro-server/tests` | ok |
| Full `scripts/check-suite-inventory.py` | ok: 17/17 suites |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,326/1,326 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-test-duplicates.py` | 0 byte-identical groups |
| `scripts/check-doc-links.py` | every relative link resolves |
| `scripts/check-deployment-claims.py` | OK |
| `gitleaks detect --log-opts=0d49d4e0..HEAD` | no leaks found |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | 65 passed |
| `uv run pytest tests/test_prod_stack_boot_contract.py -q` | 8 passed |
| `uv run pytest tests/test_gitleaksignore_contract.py -q` | 8 passed |

## Promotion-gate replay (executed this round)

`failed_promotion_checks()` imported live from `scripts/soak/run_soak.py` and
run against `docs/testing/soak/evidence/m3a-round43-shakedown.json`:

- Failed list is exactly `['sustain_duration', 'exact_rc_artifact']`; the
  other eight gates are `ok=true`.
- `hashes.git_head` of the evidence pack is `3da4e035eb…`;
  `git merge-base --is-ancestor` confirms it is an ancestor of HEAD, so the
  replayed evidence is tied to this line of development.

## Terminal blockers unchanged and external

Re-derived from this round's own dispatch capture: parent #89 is **open** and
requires "RC artifacts are built only from the candidate commit"; no RC
designation exists anywhere in the capture (linked PRs #1567/#1602 closed
unmerged, #1672 an open draft). The two remaining acceptance rows — a
≥ 14,400 s sustained soak **of the exact RC artifact** #89 would promote —
have no satisfiable object in this lane: `exact_rc_artifact` refuses
host-preflight topology by design (no CLI override, per
`m3a-load-profile.md`), and only a release owner can designate the RC
artifact under #89. Rounds 26–47 hit the identical terminal pair.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89); inventory delta
0 (no tests added).
