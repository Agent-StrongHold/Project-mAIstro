# Issue #860 — round 45 (job f76354d2) independent re-validation at eebc5c067

**Not promotion evidence or integration approval.** This round independently
re-executed every deterministic gate at this round's starting head
`eebc5c0671b36cb1cd12fcc2a1238a9cad5b4034` (clean on arrival) instead of
trusting the round-44 record, replayed the promotion-gate evaluator against the
committed round-43 evidence pack, and re-derived the terminal-blocker status
from this round's own dispatch capture. No source, test, gate, ledger, or
inventory file changed; the only artifact is this handoff note.

## Deterministic driver sequence re-executed at `eebc5c067` (all green)

Exact `98a11313` check argv, in order, executed by this round's worker:

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | resolved; idempotent on second run |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q -x` | **38 passed, 6 skipped** — includes `test_ensure_schema_fences_ddl_behind_advisory_lock`, the `98a11313/check-3.log` failure (`assert 24 == 21`), now green |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | ok: 15,729 identities |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests` | ok: 545 identities |

Additional acceptance validation executed this round:

- Full `scripts/check-suite-inventory.py` → ok: **17/17 suites** (29,939 unique
  identities, 0 duplicates).
- `scripts/check-backlog-consistency.py` → OK (168 items).
- Exact CI vulture gate `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1,326/1,326 reviewed
  identities banked.
- `scripts/check-doc-links.py` → 0 broken relative links.
- `uv run pytest tests/test_soak_promotion_gates.py -q` → **65 passed**;
  `tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py
  -q` → **16 passed** (81 total, matching the round-44 record).
- `failed_promotion_checks()` re-executed against
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`: failed list is
  exactly `['sustain_duration', 'exact_rc_artifact']`; the other eight
  functional gates carry numeric evidence (49,151 requests across 5 kinds,
  p95 ≤ 47.19 ms, RSS +6.8 %/+8.3 %, FD 30→38 / 29→35, admission ratio 1.0,
  12 concurrent submissions → 1 distinct run id, SIGTERM drain 1.0 s with
  0 5xx / 0 conn errors, 0 nonterminal runs after settle).
- Ancestry: pack head `3da4e035eb` and schema-fence fix `cd77bb81c` are both
  ancestors of HEAD (`git merge-base --is-ancestor` → true).

## Terminal blockers unchanged and external

Parent #89 (this round's own dispatch capture): **open**, "M3-A7 — Run RC soak
and byte-equivalent final promotion"; its acceptance requires RC artifacts
"built only from the candidate commit". No RC designation exists — linked PRs
#1567/#1602 are closed unmerged and #1672 is an open draft. The two remaining
issue-#860 rows (≥ 14,400 s soak of the exact RC artifact; the RC-binding half
of sustained observation) therefore cannot be satisfied by any in-lane round:
`exact_rc_artifact` refuses host-preflight topology by design. Rounds 26–44 hit
the identical terminal pair; this round confirms it at `eebc5c067` with fresh
executions.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced, 2 externally blocked); skipped 0; validation-command errors 0;
escalated 1 (release-owner RC designation under parent #89); inventory delta 0
(no tests added).
