"""Quota subsystem: legacy usage tracking and canonical Invocation accounting."""

__all__ = [
    "InvocationQuotaDenied",
    "QuotaBalance",
    "QuotaBudget",
    "QuotaEstimate",
    "QuotaEvidenceConflict",
    "QuotaObservation",
    "SqliteInvocationQuota",
]


def __getattr__(name: str) -> object:
    """Load Invocation accounting lazily to keep config imports acyclic."""
    if name == "SqliteInvocationQuota":
        from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

        return SqliteInvocationQuota
    from maistro.quota.invocation_quota import (
        InvocationQuotaDenied,
        QuotaBalance,
        QuotaBudget,
        QuotaEstimate,
        QuotaEvidenceConflict,
        QuotaObservation,
    )

    values = {
        "InvocationQuotaDenied": InvocationQuotaDenied,
        "QuotaBalance": QuotaBalance,
        "QuotaBudget": QuotaBudget,
        "QuotaEstimate": QuotaEstimate,
        "QuotaEvidenceConflict": QuotaEvidenceConflict,
        "QuotaObservation": QuotaObservation,
    }
    try:
        return values[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
