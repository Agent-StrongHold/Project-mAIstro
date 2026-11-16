"""The coin-ledger billing identity contract (#827).

The coin ledger bills spend in microchips for engine work. Until now the
engine side of that integration was duck-typed (`Agent._record_outcome` handed
whatever it had to a `charge_usage` attribute), and one question had no answer
anywhere in this repository: **is the ledger's `request_id` audit correlation
or an idempotency key?** The two readings have opposite failure modes —

- dedupe on it, and any caller that repeats a correlation id drops charges
  behind it; a client reusing `X-Request-ID` could suppress every charge after
  the first; and
- merely store it, and a transport-level retry of the same logical charge
  bills twice.

This protocol ends the ambiguity by giving the two readings separate fields
with separate rules, and by fixing the billable lifecycle the idempotency key
names.

**The billable unit is the canonical Run.** Every governed admission creates a
server-generated Run — chat admission admits one Run per turn
(`maistro/runs/chat_admission.py`), direct work and graph work enter through
the same canonical Run service. The Run is the only identity in that model
that is always present at charge time, always server-controlled, and stable
across retries: retrying a NodeRun creates a new Attempt while *preserving*
`run_id` (SPEC-081226-a66b), so a Run-scoped charge key collapses every retry
of one unit of work to exactly one charge. The Attempt is therefore the retry
boundary, not the billable unit — an Attempt adds no charge. Sub-Run billing
(a per-Invocation split) belongs to the provider-quota ledger (#718), which
already records canonical Invocations; this ledger deliberately does not mint
a second, finer identity.

**`charge_key` is the idempotency field.** It names the billable unit: the
canonical Run id. The uniqueness scope is ledger-wide — at most one charge
row per key, for the whole ledger, not per org/team/session. Reporting the
same key again is the same logical charge: implementations must record
nothing new and return the original receipt. The key must be
server-controlled; the engine passes the Run id from the ambient
`ExecutionContext` and never a client-supplied value.

**`request_id` is the audit-correlation field.** It carries the request id in
the `ExecutionContext` sense — the same value `Outcome.request_id` records —
and it may be client-influenced (`X-Request-ID`). Implementations store it and
index it for audit, non-uniquely; they never dedupe on it, never enforce
uniqueness on it, and never let it stand in for a charge key.

**An absent key must never suppress a charge.** Work can execute outside any
canonical Run (a container seam that admits no Run). There the engine passes
`charge_key=None`, and the implementation records the charge unconditionally.
That is the safe direction, the same one ADR-083026-56ee chose for the
per-turn key: a doubled charge in a rare transport retry is visible and
refundable; a silently dropped charge is neither. The conformance suite in
`packages/maistro-core/tests/agents/test_coin_ledger_conformance.py` rejects
any adapter that dedupes on `request_id` or suppresses unkeyed charges.

**The receipt.** `charge_usage` returns a mapping carrying at least
`charged_microchips: int` and `pricing_version: str`. A retried report of an
already-charged key returns the original receipt, so an Outcome written after
a retry reports what the one charge cost rather than a second amount.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CoinLedger(Protocol):
    """Bills engine spend in microchips under a Run-scoped idempotency key.

    Implementations are concrete adapters (Stronghold's PostgreSQL ledger is
    the reference deployment); the persistence policy — schema, indexes,
    migrations — lives with the adapter, not here. The engine depends only on
    this method and the two-field identity contract documented in the module
    docstring and ADR-100826-c0e1.
    """

    async def charge_usage(
        self,
        *,
        charge_key: str | None,
        request_id: str,
        org_id: str,
        team_id: str,
        user_id: str,
        model_used: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any]:
        """Record one billable charge, at most once per `charge_key`.

        `charge_key` — the billable unit's server-controlled identity: the
        canonical Run id, or `None` when the work ran outside any Run. A
        repeated key is a retried report of one charge, not a second charge:
        record nothing new and return the original receipt. `None` is *not*
        dedupable — record the charge unconditionally, whatever the
        `request_id` says.

        `request_id` — audit correlation only. May be a client-supplied
        `X-Request-ID`; store it, index it non-uniquely, never dedupe on it.

        The remaining parameters describe what the charge was for; they are
        reportable dimensions, never identity.

        Returns a mapping with at least `charged_microchips` (int) and
        `pricing_version` (str).
        """
        ...
