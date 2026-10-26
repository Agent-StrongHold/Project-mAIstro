# Issue #860 — round 161 validation

## Scope and state

Processed only issue #860 in `auto-860`. Starting HEAD was
`0ec675e7ac072190a48483dc672870aef1bee225`; the worktree was clean. No
`check-*.log` files were present in the assigned job directory. This is a
fresh validation record, not promotion approval. No production/RC deployment
credentials, immutable RC image/configuration, or external finding workflow was
available in this worktree. No tests were added and no inventory delta applies.

The previous block was not a develop-sync conflict: prior reports identified
missing exact-RC production evidence, a host-process harness incapable of
passing promotion requirements, and an acceptance gap between the stipulated
rate-limit behavior and the implemented process-local contract. Those remain
true at this HEAD; the prior attempt's code/docs were retained and reviewed,
not discarded.

## Fresh checks

| Command / inspection | Result |
|---|---|
| `uv run pytest tests/test_soak_promotion_gates.py -x -q` | 84 passed |
| `uv run ruff check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` | passed |
| `uv run ruff format --check scripts/soak/run_soak.py tests/test_soak_promotion_gates.py` | passed; 2 files formatted |
| Parsed `docs/testing/soak/evidence/m3a-round160-shakedown.json` | `git_head=161836aa5b7730559f54d14f2be92642ab5446be`, clean=true, sustain=60.08 sec; task/schedule admission, drain, LB failover/rejoin, rate gate and settle checks true; `exact_rc_artifact=false` and `sustain_duration=false` |

The evidence pack is intentionally bound to its recorded earlier run commit,
not this validation HEAD. It is a 60-second host-uvicorn preflight, not evidence
for a promoted image. `scripts/soak/run_soak.py:69,744-755,1623-1626` sets a
14,400-second minimum and its host-process preflight always reports exact-RC
false. This validation did not run a new soak because no qualifying RC target
was designated; a short preflight cannot satisfy those requirements.

## Acceptance and architecture

The load-profile contract at `docs/testing/soak/m3a-load-profile.md:13-24`
requires exact production Compose image/config identities; lines 139-148
require at least four hours; lines 165-184 declare missing users/Workspaces,
Graph/tool/Canvas/Goal worker and long-window observations blockers. These
remain unmet. Two host processes and component probes do not prove deployed
replica execution, active physical Attempt recovery/fencing, production
telemetry, or absence of duplicate physical side effects.

The implementation at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37`
explicitly describes a process-local limiter with N× aggregate allowance. It
therefore does not establish a cluster-wide budget or that replica selection
cannot increase a principal's aggregate allowance. No replacement authorization
path or scheduler was introduced.

Reviewed accepted authority: ADR-081226-a66b (canonical Run → NodeRun → Attempt
lifecycle), ADR-081626-f383 (durable Attempt lease/fencing), and
ADR-082526-b36a (lease reclaim contract). Fencing/reclaim protects canonical
execution authority; it does not by itself prove exactly-once physical external
side effects. No architecture change in this round.

| Criterion | Evidence / status |
|---|---|
| Representative RC workload and two supported production replicas | UNVERIFIED; no RC deployment was run; profile gaps remain. |
| Sustained load, saturation, queue/lease/retry and leak telemetry | UNVERIFIED; prior evidence is 60.08 seconds, below 14,400 seconds. |
| No duplicate physical work through Run/NodeRun/Attempt and Goal paths | UNVERIFIED; admission counters do not execute/fail physical work. |
| Rate/security behavior resistant to replica selection | UNVERIFIED; production limiter is explicitly process-local. |
| Active-work kill/restart with loss/duplication oracles | UNVERIFIED; prior checks establish drain/rejoin, not active physical-work recovery. |
| Exact RC image/config hash-bound four-hour soak | BLOCKED; no immutable target supplied; harness preflight is mechanically ineligible. |
| Findings filed/reclassified | UNVERIFIED; no external mutations permitted or performed. |

## Handoff

**NEEDS-REPAIR / blocked on production evidence and contract alignment.** No
actual production behavior change is justified by the available evidence in this
isolated round; attempting to remove the exact-RC or duration fail-closed gates
would misrepresent acceptance. To proceed, the owning team must designate an
immutable RC and normalized production config, run the representative workload
with physical-work/recovery oracles and required telemetry for at least four
hours, and resolve the rate-limit acceptance versus process-local contract.
Any intervening code/runtime-config change invalidates the run. Local checks
above passed; promotion acceptance is not established.
