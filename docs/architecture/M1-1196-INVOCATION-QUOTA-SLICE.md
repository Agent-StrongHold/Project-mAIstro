# Invocation quota implementation scope for #1196

Status: draft implementation, not an accepted architecture decision or closeout.
References: #1196, #55, #718, #1133. No issue is closed by this slice.
Publication base: `develop@78bb7290688a7b404d8d705a47d48c502afdc0a0`.

## Canonical boundary

The implementation attaches one composition-owned quota collaborator to
`InvocationExecutionService`, not independent checks in Router, Agent, or each
strategy. The collaborator accounts for effects; it does not execute providers,
authorize Bindings, own Runs, or choose retries.

Admission reserves every applicable Provider, capability, Workspace, and
principal policy before physical dispatch. The proposed invariant is:

```
verified opening spend + settled spend + outstanding holds + new maximum
    <= limit - reserve
```

SQLite serialization must be database-enforced with `BEGIN IMMEDIATE`, including
across separate processes sharing one file. Pod-local files are not a distributed
quota backend. PostgreSQL parity is a separate unfinished acceptance item.

## Measurement and failure semantics

Amounts are nonnegative integers; costs use micro-USD. Missing measurements are
unknown, never implicit zero. Known completed requests count even if token/cost
measurements are absent. Unknown dimensions retain their holds.

Proven non-dispatch releases a reservation. Unknown outcomes, cancellation after
dispatch, timeout, and process loss do not automatically refund it. Usage-parser
failure must not turn a completed effect into a retryable non-effect.

Canonical terminal Invocation persistence precedes settlement. Re-observation of
the same terminal evidence repairs interrupted settlement without another
provider call or duplicate charge. Reconciliation uses absolute, versioned,
Invocation-attributed observations with duplicate and conflict detection.

Reservations remain attached to their admission-period budget IDs. Reported
usage above a reservation is recorded without clamping. A guessed estimate
cannot bound remote provider spend: trusted adapters must enforce request caps.
Provider evidence must be authenticated and attributed before reconciliation;
this is not a public API accepting caller-asserted corrections.

## Coordination

PR #1252 owns #1133's durable effect stores, backend selection, logical-effect
claiming, and related lifecycle work. This quota slice must preserve that work
and must not introduce a second effect context, store-selection root, executor,
or recovery owner. The existing cross-replica logical-effect uniqueness gap is
not fixed by a quota reservation ledger.

## Remaining acceptance before readiness or closure

- Production Container/CapabilityEffectContext composition, coordinated with
  #1252; no durable-to-memory fallback.
- Canonical Run-to-principal resolution and provider-enforced upper bounds.
- PostgreSQL implementation/migration and backend conformance tests.
- Verified opening balances, historical/ambient coverage, activation and backfill.
- Ordinary Agent/model/tool end-to-end recording and legacy tracker demotion.
- Full governed-wrapper acceptance, repository lint/type/test gates, exact-head
  CI, independent review, and resolved findings.

The first local implementation has 53 focused passing tests, including a real
two-process SQLite race. They run against a source subset with the actual
InvocationExecutionService and an in-memory InvocationStore. They do not prove
production composition, full package initialization, the governed approval
wrapper, provider HTTP transport, PostgreSQL, or monorepo CI.

Keep the PR draft and #1196 open while these acceptance gaps remain.
