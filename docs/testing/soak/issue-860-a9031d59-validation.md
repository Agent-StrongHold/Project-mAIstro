# Issue #860 validation — job a9031d59

## Starting state and sync

Started at `e67da081b9b238db8f90c1632a3332d49c8f527b` on `auto-860`, clean. The supplied job directory contained no `check-*.log` files. The previous result artifact was reviewed and its `BLOCKED` disposition independently rechecked. `origin/develop` resolved after fetch to the assigned base `cd655954018c3bfd17861a75dfee6ac78f67353d`; merging it into this branch completed without conflicts, producing merge commit `388509ea13e8` (the exact full hash is recorded by Git).

## Executed validation

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — PASS: all 1321 findings match 1321 reviewed identities; zero unclassified or never-allowlisted findings. No ledger amendment was justified.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q` — PASS, 92 tests.
- `uv run ruff check .` and `uv run ruff format --check .` — PASS; format check covered 3407 files.
- `uv run python scripts/check-suite-inventory.py` — PASS, 21 suites / 33086 unique test identities.
- `uv run python scripts/check-backlog-consistency.py` — PASS.
- `uv run python scripts/check-adr-index.py` — PASS.
- `docker compose -f deploy/docker-compose.prod.yml ps` — BLOCKED before startup: required `POSTGRES_PASSWORD` is unset. No production replicas started.

## Acceptance evidence

The current release profile (`docs/testing/soak/m3a-load-profile.md`) expressly characterizes `scripts/soak/run_soak.py` as a host-process preflight, not the production Compose artifact. It requires at least 14400 seconds and its artifact check cannot pass on the host preflight. The supplied round109 evidence records 420.05 seconds and `exact_rc_artifact.ok=false`; its hashes identify a different commit, not this candidate. Profile §“Remaining representative-profile gaps” explicitly leaves concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas, Goal/background reconciliation, exact physical-work fencing, and long-window worker/pool observations incomplete. The rate-limit result measures process-local behavior and documents that aggregate allowance scales with replica count.

The accepted `docs/adr/ADR-081626-f383-execution-lease-fencing.md` assigns lease identity and fencing enforcement to the canonical Run store; a successful schedule/Run-count probe is not proof of physical-work fencing. The accepted `docs/adr/ADR-073126-c4e1-release-and-versioning-process.md` permits RCs on `develop` to be soaked before promotion. No exact RC/configuration was available or exercised here. No changes to the execution authority or authorization model were made.

| Criterion | Status |
|---|---|
| Representative RC workload | PARTIAL: defined preflight mix; profile documents remaining workload gaps. |
| Two production replicas | UNVERIFIED: Compose blocked by missing `POSTGRES_PASSWORD`. |
| Sustained saturation, lease reclaim, retry/backoff, leak and shutdown observations | NOT MET: available evidence is 420.05 seconds, short of 14400 seconds and not production Compose. |
| Exactly-once schedule/task/Run/Attempt work and Goal reconciliation | UNVERIFIED at production multi-replica grade; targeted preflight probes do not establish physical-work fencing or sustained reconciliation. |
| Rate/security/degraded behavior resistant to replica selection | UNVERIFIED for aggregate replica-selection guarantee; documented limit is process-local. |
| Required telemetry and explicit thresholds | PARTIAL in the profile/preflight; no long-window production telemetry. |
| Kill/restart, drain, fencing and recovery | UNVERIFIED in production; no production process could be started. |
| Four-hour soak of exact RC/configuration | NOT MET: 420.05 seconds, different hash, host preflight. |
| Load findings reclassified to earliest broken invariant | UNVERIFIED; no external issue actions taken. |
| Machine/human evidence tied to immutable exact RC/config hashes | NOT MET for this candidate. |

**Disposition: BLOCKED for #860 acceptance.** The sync and static/test gates pass, but required production credentials/configuration and exact RC are absent. This note records the blocker; it does not claim promotion readiness or waive any criterion. No tests were added, so no test inventory delta is required.
