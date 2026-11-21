# Issue #860 — round 165 validation

## Scope and result

Validated issue #860 from `fd04ff4fa728809636197c643217f74f5a372213` without
changing runtime code or interpreting preflight evidence as promotion evidence.
The assigned job directory contains no `check-*.log` files. No owner-designated
production RC artifact/configuration or production deployment was available to
run a promotion soak. The acceptance remains unmet; this note records validation,
not a release signature.

## Local checks

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — 143 passed.
- `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` — passed.
- `uv run python scripts/check-suite-inventory.py` — passed; 21 suites and 35,468 unique test identities.
- `find /home/dev/maistro/jobs/a099961ceaa14d1caa85035fb62f3154 -maxdepth 1 -name 'check-*.log' -print` — no logs found.

These checks validate the existing promotion-gate harness, not actual multi-replica
production behavior.

## Acceptance status

1. **Representative load profile:** `docs/testing/soak/m3a-load-profile.md` specifies a request mix, but explicitly lists unrepresented population/workspace, Graph/node, successful tool/model, Design/Canvas, and Goal/background-work coverage as blockers. **Not met.**
2. **Two application replicas:** the profile's driver is explicitly host-uvicorn preflight, not the production Compose artifact. **Production RC topology not demonstrated.**
3. **Sustained saturation, queue/lease/retry, leak, and shutdown observations:** the profile requires at least 14,400 seconds; existing evidence is shorter and does not establish all listed long-window behaviors. **Not met.**
4. **Exactly-once/fenced physical work:** schedule admission probe evidence does not prove physical Attempt fencing or sustained Goal reconciliation. **Not met.**
5. **Rate-limit non-bypass across replica selection:** `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents process-local state; ADR-085 specifies per-principal limits but does not require a shared cluster budget. The issue's acceptance does not have evidence of non-bypass, and this lane cannot change that contract by assumption. **Unresolved / not met.**
6. **Required telemetry and thresholds:** historical/partial preflight measurements do not prove production pool saturation, application event-loop latency, worker counts, and other required signals under a promotion soak. **Not met.**
7. **Kill/restart drain, fencing, and recovery:** preflight process exit/rejoin is not physical-work recovery evidence. **Not met at promotion grade.**
8. **Exact RC artifact/configuration and soak:** `scripts/soak/run_soak.py:753-763` deliberately returns `ok: false` for exact artifact identity; the duration floor is 14,400 seconds at line 74. No exact RC was supplied. **Not met.**
9. **Findings filed/reclassified:** the existing evidence notes unresolved findings and no external finding filed (`docs/testing/soak/m3a-soak-evidence.md`). GitHub mutation is outside this lane. **Not met.**
10. **Evidence bound to exact artifact/config hashes:** existing packs are preflight/historical, not evidence for a designated RC. **Not met.**

ADR-085 does not settle whether the rate-limit acceptance requires a cluster-wide
aggregate allowance. Treating a process-local limiter as proven non-bypass, or
changing the authorization/rate-limit architecture in this lane, would exceed
the evidence and scope. Resolution requires the appropriate release/security
owner and a fresh production-topology run against immutable RC/config hashes.
