# L80 verifier round 6 — independent re-verification at `11c48c428`

All commands below were executed by the round-6 verifier at the exact head
`11c48c428b7e65bc7ec881d846fa6666ef33ba36` (tree clean, base `ca4caec7d`).

## Real-backend conformance (executed, not inherited)

- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox.py -v`:
  **11 passed in 38.58s** against real Docker (29.7.2) and the production
  `ContainerBuilderSandbox` (filesystem, path escape, network egress probe,
  non-root exec, seed credential exclusion, env default-deny, read-only
  rootfs + scoped writes, process/namespace/device/host-socket, timeout kill
  incl. detached descendants, context cleanup, memory exhaustion).
- `uv run pytest packages/maistro-bootstrap/tests/test_container_sandbox_hardening.py
  packages/maistro-bootstrap/tests/test_container_sandbox_argv_status.py -q`:
  **18 passed** (create-time argv pinning: `--network=none`, unprivileged uid,
  single root `chown` before seed, host-side index-allowlist tar, env allowlist).
- `uv run pytest packages/maistro-rsi/tests/test_autonomous_isolation_tier.py -q`:
  **7 passed**.
- `uv run ruff check .`: clean.

## Gates (with the two environment pitfalls that produce false failures)

1. `scripts/check-ac-state.py --run-tests --ratchet --mandate ca4caec7d…` with
   `MAISTRO_TEST_PG_DSN`: **PASSES** (`design coverage 38.0924%`, exit 0).
   Pitfall A: the DSN service must be **PostgreSQL 17+** (repo minimum). A
   pg16 service makes `test_a_postgres_url_wires_the_postgres_store`
   (`ConfigError: … older than the minimum supported major version 17`) fail
   and drags `design_coverage` to 37.6277 — this is an environment artifact,
   not branch debt. The gate also writes `quality/ac-state.json`
   (gitignored; tracked tree stays clean).
2. `RATCHET_BASE_REV=ca4caec7d… scripts/check-ratchet-provenance.py`: **OK**
   (`24 tolerated → 24 unprotected`, no expansion). `check-shipped-surface-truth.py`:
   complete.
3. Pitfall B: `scripts/check-vulture-baseline.py` **with default args**
   (`packages tests`) FAILS even at the base — it scans non-`src` trees
   (`hive-conductor/dags`, `hive-conductor/backend`) the ledger deliberately
   does not cover. CI's designated invocation passes at this head, exit 0,
   `1412 reviewed identities -> 1412 findings`:
   `RATCHET_BASE_REV=ca4caec7d… scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.

## GitHub CI at the exact head

`statusCheckRollup` for PR #1450 at `11c48c428`: every completed check
SUCCESS except one intentional SKIP (`Container scan + SBOM + cosign`).
Relevant: `test | CI` SUCCESS (carries the real Builder sandbox conformance
lane, `.github/workflows/ci.yml` job `test`), `postgres (pg17)`/`postgres
(pg18)` SUCCESS, `exact-debt-ledger | Vulture Ratchet` SUCCESS.

## Premature-closure review

`git log ca4caec7d..HEAD` bodies scanned: no closes/fixes/resolves. The
deprecated commit `602cc2a8` ("Closes #80" in body) is **not reachable** from
HEAD — it was message-only-amended into `b37bc32d7`. PR body says only
"Refs #80".
