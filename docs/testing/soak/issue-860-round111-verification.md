# Issue #860 — round 111 verification and handoff

## Scope and authority

Verified the assigned snapshot only: issue #860 on `auto-860`, starting at
`ed0a7d7ae3bf050e3419f7bf549ea0cd15b28134`. The assigned job directory contains
no `check-*.log` files. I read the profile and accepted execution lease ADRs
`ADR-081626-f383` and `ADR-082526-b36a`. Preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority; the lease ADRs provide
fencing and reclaim contracts but do not establish that a physical-work soak
has proved them under replica loss. No runtime/config evidence identifying a
production release candidate was supplied. No gates, authorization paths,
execution authority or prior work were altered.

## Fresh validation

- `uv run pytest tests/test_soak_promotion_gates.py -x -q` — **84 passed**.
  This validates the promotion-gate behavior, not a production soak.
- Source/profile inspection confirms the load profile explicitly calls the
  current host-process runner a preflight, says it cannot sign a promotion soak,
  and requires >=14,400 seconds on exact production Compose artifacts/config.
  The profile's remaining gaps include representative multi-user/Workspace
  traffic, fan-out, successful tool/model work, Design/Canvas and Goal/background
  reconciliation; process-group sampling does not prove container/worker health;
  schedule admission cancels its queued probe Run and does not prove physical
  Attempt fencing/recovery.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents that
  each replica has a process-local limiter, with an aggregate allowance scaling
  by replica count. Therefore the stronger replica-selection non-bypass claim
  is not established by this implementation. A coordinated shared limiter
  cannot safely be introduced here as an evidence-only repair without choosing
  and validating its deployment/configuration contract.

## Acceptance disposition

No production RC, immutable image digests, normalized runtime configuration or
production topology access was available. Thus all production acceptance below
is **UNVERIFIED**, not inferred from the passing unit tests: representative
production workload; two exact-Release Candidate replicas; >=4-hour sustained
soak; saturation/lease reclaim/leak/shutdown/restart; physical-work exactly-once
fencing and recovery; production telemetry/thresholds; and machine/human
artifacts tied to the exact promoted image/configuration. Replica-selection
rate-limit acceptance is **NOT MET by the documented process-local budget
semantics**. Recorded short host-process shakedown evidence is not promotion
evidence (prior evidence reports 420.05 seconds and `exact_rc_artifact=false`).

No evidence-supported production code change can be made from this environment;
removing or weakening fail-closed promotion requirements would falsify evidence.
This round is a blocked handoff, not integration approval. Next action: provide
the immutable production RC and supported normalized config/topology, repair or
explicitly resolve the replica budget contract, then execute and publish the
>=4-hour production soak with physical Attempt failure/recovery and application
telemetry. Any code/runtime-config changes require a fresh soak.
