---
id: ADR-083026-aba1
title: "A record with no caller says so, and a turn's token total says how many calls reported one"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-a91e
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/capabilities/test_invocation_layer_states_its_reach.py
layer: Observability
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-aba1: A record with no caller says so, and a turn's token total says how many calls reported one

## Context

#63 (M1-E3) asks that "provider/model/tool/token/cost metadata attaches to the
correct Invocation/Attempt". Scoping that turned up two things, neither of
which is what the acceptance line assumes.

**The Invocation layer has no production caller.** `Invocation` is documented
as "One actual provider call beneath one physical Attempt".
`InvocationExecutionService.invoke` implements effect-retry semantics careful
enough to refuse a retry whose remote outcome cannot be proven absent;
`GovernedInvocationExecutionService` adds durable human approval;
`HarnessManager.send_invocation` composes them behind Warden and the
per-session ActionGate. Nothing calls any of it:

```
$ grep -rn "send_invocation\|GovernedInvocationExecutionService(\|InvocationExecutionService(" packages/ | grep -v /tests/
packages/maistro-core/src/maistro/capabilities/harness_manager.py:113:    async def send_invocation(
```

One hit, and it is the definition. `_vulture_whitelist.py` already keeps
`InvocationExecutionService.invoke` alive deliberately, so the absence is known
somewhere — just not where a reader of the module meets it. Its store,
`capabilities/invocation_store.py`, is SQLite-only, creates its own
`capability_invocations` table with no alembic migration, and is likewise never
constructed. (The `SqliteInvocationStore` the container *does* wire is a
different class of the same name, in `maistro.events.invocations`.)

Making that path real is #55 (M1-D1), an open P0. Until it lands, spend cannot
attach to an Invocation, because there is no Invocation.

**What does run sums the calls away.** `strategies/direct.py` and
`strategies/react.py` read `usage.get("prompt_tokens", 0)` per provider call and
accumulate `total_input`/`total_output` across the loop; `agents/base.py`
records one `Outcome` per turn with the totals. Two consequences:

- A four-call ReAct turn stores one pair. Which call was expensive, and whether
  a retry cost what the first try cost, is not recoverable — the numbers were
  seen and then added together before anything durable saw them.
- `usage.get("prompt_tokens", 0)` makes a provider that reported no `usage`
  object indistinguishable from one that reported zero. ADR-083026-a91e ruled
  that out for node metrics: "a metric nobody measured is `None`, and an
  aggregate says how many it had". The same fabrication is here, in the
  aggregate this one produces.

## Decision

**1. A record nothing constructs says so, where a reader meets it.**
`Invocation`, `InvocationExecutionService`,
`GovernedInvocationExecutionService`, `HarnessManager.send_invocation` and
`capabilities/invocation_store.py` each state that no production path
constructs them today and name #55 as what changes that. A reader should not
have to run the grep above to learn that the careful retry semantics in front
of them have never run.

This is deliberately not a deletion. The semantics are correct and #55 is the
issue that will use them; removing them would cost the design and change
nothing about the gap.

**2. The turn's total says how many calls reported one.** `Outcome` gains
`usage_reported_calls`: how many of the turn's provider calls returned a
`usage` object. `None` for a writer that did not count — a row from before this
change, or a producer that does not know — and an integer otherwise, `0`
included. So `input_tokens = 0, usage_reported_calls = 0` reads as "nothing was
reported" and `input_tokens = 0, usage_reported_calls = 3` reads as "three calls
reported, and they were free", which are different facts and were the same
number.

The token fields themselves stay non-optional `int`. Making them `Optional`
would ripple through twenty-seven non-test files that add, sum and render them,
for a distinction the count beside the value already draws — which is exactly
the shape ADR-083026-a91e chose (`tokens_measured` beside the value, not a
nullable value).

**3. The `Outcome` pair says what it is.** Its docstring states that the token
fields are a sum over the provider calls of one turn, so a reader does not take
them for one call's usage. Per-call attribution needs a per-call record, and
that is #55's to provide.

**4. `usage.get(..., 0)` goes.** The strategies read what the provider sent and
count the calls that sent it. A call that reported nothing contributes nothing
to the sum and nothing to the count, rather than contributing a zero that reads
as a measurement.

## Consequences

### Positive
- A reader of the capability layer learns its reach from the module, not from a
  grep.
- "Free" and "unreported" stop being the same stored number.
- When #55 lands, the follow-up is small: the per-call record exists, and this
  change has already established what absent means.

### Negative / Trade-offs
- `usage_reported_calls` is a count, not a per-call breakdown. It distinguishes
  the two cases that were conflated; it does not answer which call cost what.
  That answer needs #55.
- One more nullable column on `outcomes`.

### Neutral
- No behaviour changes for a provider that reports usage on every call: the
  totals are what they were, with a count beside them.
