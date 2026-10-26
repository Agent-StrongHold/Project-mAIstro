# Issue #860 — assigned validation round (51ae886d)

## Scope and repository state

Processed only the assigned #860 snapshot at starting commit
`97d0695daae992761be355a3e06ffaf42f138dff`. The job directory had no
`check-*.log` files. Fetched and merged `origin/develop` (`fec8d567`); merge
completed without conflicts. It contributed unrelated installer/restore work;
no issue-specific code, tests, or gates were modified. Canonical authority
remains `Goal -> Graph -> Run -> NodeRun -> Attempt` per accepted
ADR-081226-a66b; ADR-081626-f383 defines Attempt fencing but explicitly does
not itself prove production reclaim/recovery under process loss.

## Validation performed

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
  This establishes promotion-gate behavior only; it is not production soak
  evidence.
- Inspected `docs/testing/soak/m3a-load-profile.md`, the supplied round-109
  evidence, `scripts/soak/run_soak.py` behavior documented by the profile, and
  accepted lifecycle/lease ADRs.
- No production release candidate, immutable image digests, normalized
  production configuration/topology, or production deployment access is
  available. No live soak was run.

## Acceptance disposition

The checked-in profile defines a ≥14,400 second exact-production-Compose soak,
while the supplied round-109 shakedown ran 420.05 seconds and reports
`exact_rc_artifact.ok=false`; therefore it cannot sign promotion. Profile
sections “Remaining representative-profile gaps” and “Round-2 amendments” also
state the uncovered user/Workspace population, Graph/node fan-out, successful
tool/model/Canvas traffic, Goal/background reconciliation, sustained schedule
traffic, physical Attempt fencing/recovery, worker/cgroup telemetry and
application event-loop latency remain unverified. The configured limiter is
process-local (profile describes aggregate allowance scaling by replica
count), so the stronger claim that replica selection cannot increase a
principal's aggregate allowance is not established.

Accordingly the issue acceptance is **not proven / blocked**, not waived by the
84 passing tests. No safe evidence-supported implementation change can replace
an unavailable production RC soak; do not weaken fail-closed gates. No tests
were added, so there is no suite inventory delta.

## Next evidence required

Provide the designated immutable production RC and normalized deployment
configuration, resolve the replica-selection rate-budget contract, then execute
and publish the ≥4-hour representative two-replica soak with production
telemetry and active physical Attempt fencing/recovery evidence. Re-run after
any code/runtime configuration change.
