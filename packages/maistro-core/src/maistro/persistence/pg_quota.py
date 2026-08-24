"""PostgreSQL quota tracker."""

from __future__ import annotations

from typing import TYPE_CHECKING

from maistro.quota.billing import cycle_key as _canonical_cycle_key

if TYPE_CHECKING:
    import asyncpg


def cycle_key(billing_cycle: str) -> str:
    """Resolve a billing *cycle type* to the key for the cycle running now.

    `billing_cycle` is a type -- "monthly" or "daily" -- not an instance:
    `ModelQuota.billing_cycle` defaults to "monthly" and `QuotaBurnScheduler`
    passes that string straight through. This function used to return it
    lowercased, so every month's usage accumulated into the single row keyed
    `"monthly"` and nothing ever rolled over. A provider that exhausted its
    free tier once stayed over quota permanently, and the router kept
    deprioritising it forever.

    `InMemoryQuotaTracker` never had that bug -- it uses
    `maistro.quota.billing.cycle_key`, which renders the current `%Y-%m` or
    `%Y-%m-%d`. Two implementations of one protocol disagreeing about what a
    key means is the bug; this delegates rather than restating it, so they
    cannot drift again.

    `sqlite_quota.py` imports this same function, so the SQLite tracker had the
    identical defect and is fixed by the same line. That one is pre-existing
    and outside #122's diff -- it is fixed here because leaving a known
    never-rolls-over bug in the sibling backend while repairing this one would
    be the wrong half of a shared fix.
    """
    return _canonical_cycle_key(billing_cycle)


class PgQuotaTracker:
    """PostgreSQL-backed quota tracker."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_usage(
        self,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, object]:
        """Record token usage."""
        ck = cycle_key(billing_cycle)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO quota_usage
                   (provider, cycle_key, input_tokens, output_tokens,
                    total_tokens, request_count)
                   VALUES ($1, $2, $3, $4, $5, 1)
                   ON CONFLICT (provider, cycle_key) DO UPDATE SET
                     input_tokens = quota_usage.input_tokens + $3,
                     output_tokens = quota_usage.output_tokens + $4,
                     total_tokens = quota_usage.total_tokens + $5,
                     request_count = quota_usage.request_count + 1
                   RETURNING *""",
                provider,
                ck,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
            )
        return {
            "provider": provider,
            "cycle_key": ck,
            "input_tokens": row["input_tokens"] if row else 0,
            "output_tokens": row["output_tokens"] if row else 0,
            "total_tokens": row["total_tokens"] if row else 0,
            "request_count": row["request_count"] if row else 0,
        }

    async def get_usage_pct(
        self,
        provider: str,
        billing_cycle: str,
        free_tokens: int,
    ) -> float:
        """Get usage as a percentage of free tier."""
        if free_tokens <= 0:
            return 0.0
        ck = cycle_key(billing_cycle)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT total_tokens FROM quota_usage WHERE provider = $1 AND cycle_key = $2",
                provider,
                ck,
            )
        total: int = row["total_tokens"] if row else 0
        return total / free_tokens

    async def get_all_usage(self) -> list[dict[str, object]]:
        """Get all usage records."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM quota_usage ORDER BY provider, cycle_key",
            )
        return [
            {
                "provider": r["provider"],
                "cycle_key": r["cycle_key"],
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
                "total_tokens": r["total_tokens"],
                "request_count": r["request_count"],
            }
            for r in rows
        ]
