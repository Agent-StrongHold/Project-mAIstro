# Issue #860 — round 111 (job 81380b7f) validation of the round-110 state

**Not promotion evidence or integration approval.** Round 110 independently
verified round 109's repair and closed with a BLOCKED escalation ("worker
requested attention"). This round resolves that attention request as far as
in-repo authority allows: it re-executes the full deterministic battery at the
dispatched head, re-verifies the evidence-pack binding, re-confirms the
external blocker status from the fresh dispatch capture, and records the row-5
disposition as an explicit reconciliation against closed #842's acceptance
text rather than a bare assertion. No source, test, or ledger file was
authored or modified by this round; the only tree content added is this
record.

## Snapshot

- Start head `62edb1ab4` — exactly the dispatched head; tree clean. End head:
  same + this record.
- The dispatch job directory contained **no `check-*.log` files**: the driver
  executed zero deterministic checks. Every result below was run fresh in
  this round and logged as `check-*.log` in
  `/home/dev/maistro/jobs/81380b7fff66413290f6b47a72bfeb94/`.
- `git fetch origin`: `origin/develop` is still `ab8b3737f` — the declared
  base, already an ancestor of HEAD. **No develop drift; no sync needed.**
- **Production identity binding intact**: `git diff 5a59c724a..62edb1ab4
  --name-only` contains **zero non-`docs/` paths** — the production code
  soaked in round 109 is byte-for-byte the production code at this head, so
  the round-109 evidence pack remains bound to the current tree without a
  re-soak.

## Deterministic battery at `62edb1ab4` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (check-0) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**; ratchet base `ab8b3737fa64`, candidate `62edb1ab4fa5`; no ledger amendment (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4), including the row-5 regression lock `test_replica_selection_has_an_independent_production_allowance` (tests/test_soak_promotion_gates.py:439) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** (skips require `MAISTRO_TEST_PG_DSN`) (check-5) — the file that failed in job 98a11313 `check-3.log` remains green |
| `uv run mypy packages/maistro-{core,server,turing,canvas,bootstrap,registry,evolve,rsi,design,ext-harness}/src` (ci.yml exact ten-package arguments) | **Success: no issues found in 1057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory, 0 byte-identical test files (check-7) |

## Promotion gates + evidence-pack integrity (check-8, reproduced live)

`PYTHONPATH=scripts uv run python` loading `failed_promotion_checks` from
`scripts/soak/run_soak.py` at this head and applying it to
`docs/testing/soak/evidence/m3a-round109-shakedown.json` exits 1 with exactly
**`['sustain_duration', 'exact_rc_artifact']`** — identical to rounds 109 and
110; **no functional promotion check fails**, only the two externally blocked
ones:

- `PROMOTION_MIN_SUSTAIN_SECONDS = 14400` vs pack `sustain_seconds = 420.05`
  (row 3).
- `exact_rc_artifact` refuses host-preflight topology by design (row 8).

Pack integrity re-verified in the same run: rendered nginx conf on disk
sha256 `86291c53ab2a81fd…` **matches** `hashes.nginx_rendered_conf_sha256`;
`hashes.git_head = 5a59c724a20e…` with `git_clean = true`.

## Row-5 disposition reconciled against closed #842's acceptance text

The round-109/110 records asserted the process-local rate limiter is "a
product property requiring a product change". This round verified that claim
against the owning issue's own acceptance criteria (#842, **closed**):

> "Distributed/supported multi-replica deployments share enforcement state
> **or explicitly fail safe within the claimed policy**; a process-local
> limiter cannot be advertised as cluster-wide."

The implementation takes the second branch, exactly as #842 sanctions:

- `RateLimitMiddleware` state is process-local and **deliberately not
  advertised as cluster-wide** — the middleware docstring
  (packages/maistro-server/src/maistro_server/api/rate_limit.py, "Enforcement
  scope (per #842 AC)") states the aggregate budget of an N-replica
  deployment is N × the configured limit and names a coordinated store as "a
  separate change".
- The per-replica allowance is regression-locked as a *finding*, not an
  aspiration: `test_replica_selection_has_an_independent_production_allowance`
  (tests/test_soak_promotion_gates.py:439) preserves the falsification of the
  old shared-store claim.

Consequently: a shared-store limiter is a **new product change outside this
soak lane's scope** (it would also invalidate all existing soak evidence per
the issue's own "any code/runtime-config change requires a new soak" rule,
without unblocking rows 3/8). The contrary evidence for acceptance row 5
stands as filed under row 9 (F1–F12 mapping, in-repo; GitHub filing
prohibited in this lane).

## External blocker status re-confirmed (fresh dispatch capture, 2026-10-17)

- Parent **#89 "M3-A7 — Run RC soak and byte-equivalent final promotion"**:
  **open**. RC PR **#1672**: **open draft** (`15ce4681`). No RC artifact
  exists to soak; #1567/#1602/#2100 are merged history, none a designation.
  Row 8 remains blocked on the release owner, not on this lane.
- Row 3 (≥ 14,400 s sustain) remains above any in-lane round window;
  background execution is prohibited; no production Compose runner is
  designated in-lane.

## Disposition

Unchanged from round 110, now with fresh evidence and the #842 reconciliation
on record: rows 1–2, 4, 6–7, 10 carry verified bounded evidence bound to the
current production identity (byte-identical since the soaked head) and must
be re-evidenced at the eventual promotion commit; rows 3 and 8 are externally
blocked (RC designation under open parent #89; ≥ 4 h window); row 5 is
contrary-by-design per closed #842's explicit fail-safe branch. The requested
attention (RC designation) stays with the release owner; nothing in-repo
remains repairable by this lane.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary-by-design); skipped 0; validation errors 0; escalated 1
(RC designation under parent #89 — unchanged); inventory delta 0 (no tests
added or removed by this round; the harness note
`docs/testing/inventory-notes/m3a-860-multi-replica-soak.md` already covers
the tooling); repairs 0 (nothing in-repo to repair; battery re-proven green
at the dispatched head).
