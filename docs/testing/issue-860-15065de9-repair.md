# Issue #860 repair validation — job 15065de96cbe44dfbc3c5e1fc5888f7d

Scope: issue #860 only; branch `auto-860`; starting HEAD
`af00dd82e69b0baf422c4019bb653ede06860f31` (the supplied develop merge is
already present). The worktree was clean at entry. The assigned job directory
contains no `check-*.log` files; therefore there were no driver check logs to
reuse. Examined the supplied dispatch context and prior result, then verified
current code and acceptance behavior independently. No production soak was
run and no GitHub state was changed.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **84 passed**.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed; 1324/1324 reviewed identities, zero unclassified or never-allowlist findings. No ledger change justified.
- `uv run ruff check . && uv run ruff format --check .`: passed; 3393 files formatted.
- `uv run python scripts/check-backlog-consistency.py`: passed; 168 backlog items.

## Acceptance disposition

| Criterion | Evidence / disposition |
|---|---|
| Representative RC workload | UNVERIFIED: `docs/testing/soak/m3a-load-profile.md:165-184` records outstanding multi-user/Workspace, graph fan-out, successful tool/model, Design/Canvas and background worker workload. |
| Two production replicas | UNVERIFIED: the tested middleware instances are not the production Compose artifact. The profile says the host harness is not that artifact (`m3a-load-profile.md:10-16`). |
| Sustained saturation, reclaim, retries and leak observation | UNVERIFIED: no sustained deployed soak executed. Profile requires at least four hours (`m3a-load-profile.md:141-152`) and lists missing pool/lease/long-window observations (`:176-184`). |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: `scripts/soak/run_soak.py:160-164` explicitly states the schedule admission probe is never executed; accepted ADR-081626-f383 leaves lease-expiry takeover/recovery undefined. Admission uniqueness is not physical Attempt fencing. |
| Replica-selection rate-limit bypass | NOT MET by current implementation: `api/rate_limit.py:90-98` creates a process-local limiter. The executed regression at `tests/test_soak_promotion_gates.py:480-526` observes `[200, 200, 429]` separately on both instances. ADR-085 and `rate_limit.py` explicitly specify process-local enforcement and disclaim a cluster-wide budget; changing this would require an architectural decision/coordinated store, not a silent #860 exception. |
| Required telemetry and thresholds | PARTIAL/UNVERIFIED: existing profile and driver tests cover some probes, but profile lines 176-184 explicitly note application-loop, detached worker/cgroup, pool saturation and lease-reclaim gaps. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no production active Attempt kill/restart experiment was executed. |
| Long soak of exact RC artifact/configuration | UNVERIFIED: `scripts/soak/run_soak.py:744-755` intentionally marks host preflight as not the exact artifact; the gate requires `exact_rc_artifact` and sustained duration (`:770-776`). |
| Findings classified before promotion | PARTIAL: existing backlog consistency check passes, but no newly observed production-soak findings exist to classify. Completeness for final promotion is unverified. |
| Hash-bound machine and human evidence | UNVERIFIED: no evidence from a qualifying immutable production artifact was generated. |

No code or tests were changed: a code-only adjustment cannot supply required
production evidence, and converting process-local rate limiting to a distributed
budget would conflict with its documented contract without an accepted design.
No test inventory delta is applicable. Disposition: **BLOCKED** pending an
immutable RC/configuration, architecture decision for the cluster-budget
requirement, representative production workload, and >=4-hour artifact-bound
soak including active Attempt recovery and complete telemetry.
