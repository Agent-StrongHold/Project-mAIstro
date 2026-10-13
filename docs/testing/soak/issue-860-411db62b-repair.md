# Issue #860 validation — job 411db62b

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`e63e820c161475aac34ca4498f7ba1ab0c697295`, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Worktree clean at start; no
salvage needed; no remote mutations. Prior block under resolution: job
80201704's `NEEDS-DEEP-REVIEW` (worker requested attention).

This job directory contains no driver `check-*.log` files (verified by
listing). The referenced failure log is the historical
`98a113…/check-3.log` (schema-fence DDL count 24 vs 21), re-executed below
rather than trusted.

## What this round adds

Independent re-verification, on the exact starting HEAD, of every claim the
prior round made — including a full re-execution of the deterministic
battery and a direct audit of the round-44 evidence artifact. No code,
test, or evidence content changed; the round-44 live soak is retained as
the freshest valid evidence (its `git_head` pin `b4cfb94db` differs from
`e63e820c1` only by the evidence/report docs themselves, so the
production-code identity is unchanged).

## Executed checks on HEAD `e63e820c1`

| Command | Result |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — supplied check-3.log failure is stale on HEAD (fix landed in `cd77bb81c`) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **Clean:** 1323 reviewed identities → 1323 findings, `unclassified: 0`, `never_allowlist: 0`; no ledger amendment (not a CI-repair round) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3270 files already formatted |
| `failed_promotion_checks(m3a-round44-shakedown.json)` (executed) | `['sustain_duration', 'exact_rc_artifact']` — exactly the two by-design host-preflight gates |

## Round-44 evidence audit (direct artifact reads, not report excerpts)

- `hashes.git_head = b4cfb94db…`, digest-pinned Postgres image, rendered
  nginx + soak-env hashes present — machine-readable identity binding.
- `sustain_seconds = 420.05` vs `minimum_seconds = 14400` (gate fails by
  design on host preflight; no CLI override, `run_soak.py:730-741`).
- `exactly_once_tasks`: 12 concurrent submissions → 12 delivered, 1
  distinct run id, 11 duplicate run ids collapsed, `ok: true`.
- `exactly_once_schedule_claim`: cross-process claim race, 0 occurrences
  with multiple runs, `ok: true`.
- `rate_limit.enforced_everywhere = true` — through-LB 472/469 429s;
  direct-replica probes 600/600 and 547/556 429s.
- `kill_restart`: SIGTERM, drained in 1.0 s, rc 143 path, 0 drain-5xx,
  0 conn errors, `rejoined: true`; `nonterminal_runs = 0` after settle.
- RSS bounded (+7.6 % / +7.2 %), FD max 47/42.
- `m3a-load-profile.md` carries pass/fail thresholds and an explicit
  remaining-gaps section (users/Workspaces, Graph fan-out, model/tool
  paths, event-loop series, Goal-worker reconciliation).

## Code claims re-verified at source

- `main.py:648` installs `RateLimitMiddleware` per process;
  `api/rate_limit.py:93` constructs a per-process `InMemoryRateLimiter`
  (H3 standing contrary evidence, encoded by
  `tests/test_soak_promotion_gates.py:436`). Unchanged; #842 is closed and
  scopes cluster-wide sharing out — security-owner disposition required.
- `preflight_artifact_check()` refuses host-topology equivalence by
  design with no override — correct, not a defect.

## Acceptance audit

Unchanged from the prior round's table, now independently confirmed:
criteria provable inside this lane are proven on fresh HEAD-pinned
evidence; the four that remain (≥ 4 h soak of the exact RC Compose
artifact, RC-identity drain/fencing, promotion-grade telemetry series,
cluster-wide rate-limit budget) are outside worker authority — release
owner per #89 and security owner for H3.

## Inventory notes

No test files added or modified; suite counts unchanged (65 gate tests;
37+6 pg-learnings). No `docs/testing/inventory-notes/` delta required.

## Disposition

**NEEDS-DEEP-REVIEW — resolved as a verified ownership handoff.** The
prior escalation was not a worker failure: every executable check is green
on HEAD, the only failing promotion gates fail by construction for a host
preflight, and the remaining acceptance items are explicitly release-owner
(≥ 4 h exact-RC soak, #89) and security-owner (cluster-wide rate-limit
budget, H3) decisions. No code defect is known to remain in this lane.
