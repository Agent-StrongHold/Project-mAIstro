---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-rsi/tests: +0
  packages/maistro-core/tests: +0
---
# L80 verifier round 8 — both round-7 BLOCKED findings resolved at `b0fd073a9`

The round-7 verify job returned NEEDS-REPAIR at head
`b0fd073a98d602c7446ad774cdbd7378ab147ed2` (develop base `176043b01`) on two
findings. Both are resolved by re-execution with the environments the gates
actually specify — no gate was edited, no note was re-banked, the tree's
tracked content is unchanged except this record.

## Finding 1: `check-ac-state` design_coverage 34.0299 below floors 38.0924/38.4867

Round 5 (`l80-ac-state-ratchet-repair.md`) already proved this counter is a
**service-less measurement artifact**: 133 AC-marked tests skip without
`MAISTRO_TEST_PG_DSN`, and a skipped AC test leaves its criterion below
`passing`, reading `design_coverage` ~5 points low. The round-7 verifier's run
reproduced the artifact because its DB service was reachable but **unmigrated**
(275 PG-leg tests error on `UndefinedTableError: relation "quota_usage_events"
does not exist` without `alembic upgrade head`; CI applies migrations in a
dedicated step, `quality.yml` "Apply migrations", before the gate).

Re-executed at this exact head, CI-equivalent (fresh `pgvector/pgvector:pg18`
service, `uv sync --locked --all-extras`, `DATABASE_URL=... uv run alembic
upgrade head` exit 0, `MAISTRO_TEST_PG_DSN` set):

- `RATCHET_BASE_REV=176043b01 --mandate 176043b01` → **exit 0**:
  `design coverage 38.4867% over 157 taken decisions`, "10 debt counters sit
  exactly on their ceilings and 1 progress counter sits exactly on its floor",
  criteria mandate 0 unproven, chain mandate clean.
- The round-7 verifier's exact argv (`RATCHET_BASE_REV=ca4caec7d --mandate
  ca4caec7d`) → **exit 0**, same 38.4867 and same three OK lines.
- Control: the same measurement on a detached worktree of the develop base
  `176043b01` with the DSN but **without** migrations reproduces 34.0299 —
  the branch and its base are identical at every service level, so the
  shortfall was never branch debt.

Authoritative confirmation: PR #1450 (branch `auto-80`, head `b0fd073a9`) CI
ran to completion with **every check SUCCESS**, including `Quality gate
(Pillars 1–4, 7, 8)` — the job that runs this gate with services.

## Finding 2: PR CI IN_PROGRESS / CI completion UNVERIFIED

`gh pr view 1450` now reports every check COMPLETED/SUCCESS: `test` (which
contains the real Builder sandbox conformance lane), `Quality gate`,
`integration-scope`, `gates-ran` (SUCCESS status context), `exact-debt-ledger`
(vulture ratchet — green, so no ledger amendment is warranted this round),
`postgres (pg17)`, `postgres (pg18)`, `durable-events`, `docker-build`,
`hive-conductor-e2e`, SAST, supply chain, coverage gates.

## Acceptance re-validation at this head (executed, not assumed)

- `docker build --tag maistro-builders:latest --file
  packages/maistro-bootstrap/tests/Dockerfile.sandbox
  packages/maistro-bootstrap/tests` → image built.
- `pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py -q` →
  **25 passed** (live Docker: network default-deny, credential blanking incl.
  FTP/case spellings, tracked-only seed with `.env`/`.git` exclusion,
  non-root uid, read-only rootfs with explicit writes, process/namespace/
  device/host-socket, timeout kill of detached descendants, cleanup, memory
  exhaustion — all against the production `ContainerBuilderSandbox` imported
  from `maistro_bootstrap.builders.container_sandbox`).
- `pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q` →
  **7 passed** (Tier-3 refused for autonomous loops).
- Core Tier-3 escape lane `pytest
  packages/maistro-core/tests/sandbox/test_escape_conformance.py -q` → 4
  passed, 24 skipped **fail-closed by design**: the capability probe runs
  under the spawn rlimits (`RLIMIT_NPROC` from `max_processes`), and this
  host carries 449 tasks for the UID, so `clone` returns EAGAIN and Tier 3 is
  honestly refused (CI relaxes the userns restriction and runs these live;
  that lane is green). A manual live Tier-3 run on this kernel with a budget
  that fits (`max_processes=1024`) confirmed: host fs hidden, loopback-only
  networking with DNS failing, 5 processes in the PID namespace, device
  access blocked, uid 1000.
- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- Suite inventories for `packages/maistro-bootstrap/tests` and
  `packages/maistro-rsi/tests` unchanged → recorded inventories still match.

## Residual risk

The `ADR-082526-b36a` lease-timing knife-edge (documented in round 5) remains
the only ±one-criterion wobble in the coverage number; it is a runs/lease
suite concern, not a sandbox one.
