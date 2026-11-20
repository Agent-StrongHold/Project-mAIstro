# L80 verifier round 7 — repair-round re-validation at `7f35a7a2a`

All commands below were executed by the round-7 repair worker at the exact
head `7f35a7a2a76cc6f10c3b2860c48e54ca1e6ba1e8` (tree clean, develop base
`031bd0746`). The round-6 verify job returned BLOCKED at this same head on two
findings; both are resolved here by re-execution, not by editing gates.

## Prior finding 1: ac-state ratchet `design_coverage 33.0728 < 38.0924`

Reproduced the verifier's failing condition (no `MAISTRO_TEST_PG_DSN`) and
then ran the gate the way CI runs it (`.github/workflows/quality.yml:642,980`
— DSN set, migrations applied, `--mandate` for PR candidates):

- Dedicated pgvector/pg18 service on `127.0.0.1:5437` (repo minimum is PG 17;
  round-6 pitfall A avoided), `DATABASE_URL=... uv run alembic upgrade head`
  exit 0.
- `MAISTRO_TEST_PG_DSN=... uv run python scripts/check-ac-state.py
  --run-tests --ratchet --mandate ca4caec7d3193fb786e41d9ae3c6ccf94ac15304`:
  **exit 0** — `design coverage 38.0924% over 156 taken decisions`, "10 debt
  counters sit exactly on their ceilings and 1 progress counter sits exactly
  on its floor", criteria mandate 0 unproven, chain mandate clean.

This matches the round-5 conclusion: the 33.0728 reading is the service-less
measurement artifact, not branch debt. The gate wrote only the gitignored
`quality/ac-state.json`; the tracked tree stayed clean.

## Prior finding 2: promotion-surface `134 unprotected vs 24 trusted`

- `uv run python scripts/check-promotion-surface-provenance.py`: **exit 0** —
  `24 tolerated promotion-path module(s) -> 24 unprotected module(s) in
  closure`, `OK: 171 promotion-path module(s)`. The 134-vs-24 reading was
  taken before the `a71fc2e43` merge brought the repair; at this head the
  gate is green, which is also what the round-6 note recorded for GitHub CI
  (`exact-debt-ledger | Vulture Ratchet` SUCCESS at `11c48c428`).
- `uv run python scripts/check-ratchet-provenance.py`: **exit 0** — all 37
  quality JSON consumers have explicit provenance, no candidate-approved
  expansion on any delegated gate.
- `RATCHET_BASE_REV`-style CI invocation `uv run python
  scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: **exit 0**, `1411 reviewed identities ->
  1411 findings` — no unbanked identities, so no ledger amendment is
  required or made in this round.

## Prior finding 4: `Closes #80` in commit `602cc2a8`

`git merge-base --is-ancestor 602cc2a8 HEAD` → **not reachable**. The commit
was message-only-amended into `b37bc32d7`, whose body contains no
closes/fixes/resolves keyword. The auto-close hazard exists only on an
unreachable object; no issue-closure action was taken or is pending from this
lane. Note: `a71fc2e43` and `9e9f5037e` (other lanes' WIP commits merged into
this branch) do carry `(#1488)`/`(#1443)`-style trailer numbers, but their
bodies contain no auto-close keywords (`git log --format=%B` scanned).

## Real-backend conformance (re-executed, not inherited)

- Rebuilt `maistro-builders:latest` from
  `packages/maistro-bootstrap/tests/Dockerfile.sandbox` (the same build the
  CI lane at `.github/workflows/ci.yml:469-471` performs).
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py
  packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q`:
  **32 passed in 39.58s** against real Docker — filesystem isolation, path
  escape, network default-deny, non-root exec, seed credential exclusion
  (`.env`/`.git`/ambient secrets), env credential default-deny, read-only
  rootfs + explicit scratch/workspace scope, process/namespace/device/host-
  socket reachability, timeout kill with detached descendants, context
  cleanup, memory exhaustion containment, argv-level create-time pinning,
  seed-failure cleanup at every transfer stage.
- `uv run pytest packages/maistro-core/tests/sandbox/test_escape_conformance.py
  -q`: 4 passed, 24 skipped — skips are the designed fail-closed behavior
  ("this host cannot build a bubblewrap sandbox": this WSL kernel cannot run
  `bwrap` 0.11.1). The designated hardware-capable lane for that suite is the
  bubblewrap-enabled CI runner (`.github/workflows/ci.yml:445-455`).
- Production-parity: `maistro_rsi/local_loop.py:806` and
  `maistro_rsi/contained_validation.py:80` instantiate the same
  `ContainerBuilderSandbox` the conformance suite exercises; no separate
  hardened fixture exists.

## Residual risks

- `ADR-082526-b36a` lease-timing tests sit close to the PG round-trip budget
  and can flake the coverage number by ±one criterion under load (recorded in
  `l80-ac-state-ratchet-repair.md`; belongs to the runs/lease lane).
- The Bubblewrap escape suite is only proven on CI's userns-capable runner;
  local WSL kernels skip it by design.
