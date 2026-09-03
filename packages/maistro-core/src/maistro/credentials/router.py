"""Scoped credential routing for Provider selection on the Invocation path.

ADR-063 specified the pool and its rotation semantics; #58 moves *where*
rotation happens. Selection is no longer a detached library loop that owns its
own retries (the removed ``maistro.credentials.rotation.execute_with_pool``):
it happens where the Provider choice is known — the canonical
``ProviderResolver`` seam beneath a Binding — and cooldown/blocking happens as
real Invocation outcomes are recorded through :meth:`CredentialRouter.record_outcome`.
A rate-limited key is cooled by the outcome of the actual provider call, and
the next Invocation's acquisition rotates to the next authorized key. Physical
retries remain whole new Invocations under later Attempts, owned by the
canonical execution model — never by this module.

Encryption and master-key rotation are a separate concern and stay in
:mod:`maistro.credentials.store` (see ``docs/CREDENTIAL-ROTATION-RUNBOOK.md``);
nothing here persists or decrypts secrets.

Scope: every pool is keyed by ``(workspace_id, project_id, provider)`` and
every acquisition is additionally constrained to the ``credential_refs`` the
Binding authorizes. A Binding that names no refs, or refs absent from its
scope, acquires nothing — the failure is closed and typed, not a silent
fallback to some other workspace's key.
"""

from __future__ import annotations

from maistro.credentials.pool import CredentialPool
from maistro.credentials.types import (
    CredentialRecord,
    PoolStats,
    SelectionStrategy,
)
from maistro.resilience.classifier import ClassifiedError, ErrorCategory, classify_error

#: 429 (rate limit) cooldown in seconds, absent a Retry-After value (#AC-12).
RATE_LIMIT_COOLDOWN_SECONDS = 60.0
#: 402 (billing) cooldown in seconds — billing exhaustion rarely resolves fast (#AC-15).
BILLING_COOLDOWN_SECONDS = 3600.0

ScopeKey = tuple[str, str, str]


class CredentialScopeError(PermissionError):
    """A Binding's authorized scope covers no usable credential.

    Distinct from :class:`PoolExhaustedError` on purpose: a scope error is a
    durable authorization/configuration mismatch that retrying cannot fix, so
    it denies loudly instead of surfacing as transient unavailability.
    """


def _status_from_error(error: Exception) -> int:
    """HTTP status carried by the exception object, 0 when there is none.

    The classifier folds status into its *category* but does not copy the
    number into ``detail`` (the removed detached loop silently lost 401/403
    blocking this way — #58 makes outcome-driven rotation real, so the mapping
    reads the same attributes the classifier reads).
    """

    for attr in ("status_code", "statusCode", "code"):
        value = getattr(error, attr, None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    response = getattr(error, "response", None)
    if response is not None:
        value = getattr(response, "status_code", None)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return 0


def _effective_status(classified: ClassifiedError, status_code: int) -> int:
    """The status the cooldown table keys on: raised, else classified detail."""

    if status_code:
        return status_code
    detail = classified.detail
    if isinstance(detail, dict):
        status = detail.get("status_code", 0)
        return status if isinstance(status, int) else 0
    return 0


def _rate_limit_cooldown(classified: ClassifiedError) -> tuple[float, bool]:
    """Up to RATE_LIMIT_COOLDOWN_SECONDS, honoring a provider Retry-After."""

    retry_after = classified.retry_after_seconds
    if retry_after and retry_after > 0:
        return min(RATE_LIMIT_COOLDOWN_SECONDS, retry_after), False
    return RATE_LIMIT_COOLDOWN_SECONDS, False


def cooldown_for_failure(
    classified: ClassifiedError, *, status_code: int = 0
) -> tuple[float, bool]:
    """Map a classified provider error to ``(cooldown_seconds, should_block)``.

    Carries the ADR-063 cooldown table onto Invocation outcomes: 429 cools for
    up to 60s (honoring ``Retry-After``), 402 cools for an hour, 401/403 block
    permanently, and transient/unknown errors set no cooldown so the key stays
    available to other Invocations (#AC-14). Status comes from the raised
    error itself; classification categories cover errors that carry no status.
    """

    effective = _effective_status(classified, status_code)

    if effective == 402 or classified.category is ErrorCategory.BILLING:
        return BILLING_COOLDOWN_SECONDS, False
    if effective in (401, 403) or classified.category is ErrorCategory.AUTH:
        return 0.0, True
    if effective == 429 or classified.category is ErrorCategory.RATE_LIMIT:
        return _rate_limit_cooldown(classified)
    return 0.0, False


class CredentialRouter:
    """One authority for runtime credential selection and outcome rotation.

    The in-memory implementation of ADR-063's protocol-driven pool access,
    scoped per Workspace/Project and per Binding-authorized ``credential_refs``.
    Construction happens in the composition root
    (:func:`maistro.capabilities.effect_context.new_in_memory_effect_context`);
    consumption happens through
    :mod:`maistro.capabilities.credential_routing`, which wraps the canonical
    Provider resolver/executor pair of the Invocation path.
    """

    def __init__(self, *, strategy: SelectionStrategy = SelectionStrategy.ROUND_ROBIN) -> None:
        self._pools: dict[ScopeKey, CredentialPool] = {}
        self._strategy = strategy

    @property
    def strategy(self) -> SelectionStrategy:
        return self._strategy

    def add(
        self,
        *,
        workspace_id: str,
        project_id: str,
        record: CredentialRecord,
    ) -> None:
        """Register a credential in one Workspace/Project scope.

        Re-registering the same ``key_id`` in the same scope replaces the prior
        record rather than duplicating it, so an operator refresh of a key is
        idempotent.
        """

        scope = (workspace_id, project_id, record.provider)
        pool = self._pools.get(scope)
        if pool is None:
            pool = CredentialPool(provider=record.provider, strategy=self._strategy)
            self._pools[scope] = pool
        pool.remove(record.key_id)
        pool.add(record)

    def pool_for(
        self,
        *,
        workspace_id: str,
        project_id: str,
        provider: str,
    ) -> CredentialPool | None:
        return self._pools.get((workspace_id, project_id, provider))

    def stats(
        self,
        *,
        workspace_id: str,
        project_id: str,
        provider: str,
    ) -> PoolStats | None:
        """Pool health for one scope, or None when no pool is configured.

        Key ids and counts only — never secret material (ADR-063 stats table).
        """

        pool = self.pool_for(workspace_id=workspace_id, project_id=project_id, provider=provider)
        return pool.get_stats() if pool is not None else None

    async def acquire(
        self,
        *,
        workspace_id: str,
        project_id: str,
        provider: str,
        credential_refs: tuple[str, ...] = (),
    ) -> CredentialRecord:
        """Select the next credential a Binding may use in its own scope.

        Raises :class:`CredentialScopeError` when the scope holds no pool for
        this provider, when the Binding names no ``credential_refs`` at all, or
        when none of the refs it names exist in this scope — authorization
        failures, closed rather than fallen through. Raises
        :class:`PoolExhaustedError` when authorized credentials exist but are
        all blocked or cooling down — a transient condition the caller surfaces
        as capability unavailability until the soonest cooldown expires.
        """

        pool = self.pool_for(workspace_id=workspace_id, project_id=project_id, provider=provider)
        if pool is None or pool.size == 0:
            raise CredentialScopeError(
                f"no credentials configured for provider {provider!r} in "
                f"workspace {workspace_id!r} / project {project_id!r}"
            )
        if not credential_refs:
            raise CredentialScopeError(
                "credential_refs is empty: a Binding crossing the credential "
                "routing seam must name the credentials it authorizes"
            )
        authorized = frozenset(credential_refs)
        configured = pool.key_ids()
        if not (authorized & configured):
            raise CredentialScopeError(
                f"Binding authorizes credentials {sorted(authorized)}, but scope "
                f"workspace {workspace_id!r} / project {project_id!r} configures "
                f"{sorted(configured)} for provider {provider!r}"
            )
        return pool.select(allowed_key_ids=authorized)

    async def record_outcome(
        self,
        *,
        workspace_id: str,
        project_id: str,
        provider: str,
        key_id: str,
        error: Exception | None,
    ) -> None:
        """Fold one actual provider-call outcome into the scoped pool.

        Called by the Invocation-path executor wrapper after each physical
        provider call: ``error=None`` is a success (clears error state, bumps
        use count); otherwise the exception is classified (IMP-001) and mapped
        through the ADR-063 cooldown/block table, so rotation is a reaction to
        the provider's own response — never a timer started speculatively.
        """

        pool = self.pool_for(workspace_id=workspace_id, project_id=project_id, provider=provider)
        if pool is None:
            return

        if error is None:
            pool.record_success(key_id)
            return

        classified = classify_error(error)
        status_code = _status_from_error(error)
        cooldown, should_block = cooldown_for_failure(classified, status_code=status_code)
        pool.record_failure(
            key_id,
            status_code=status_code,
            error_code=classified.category.value,
            cooldown_seconds=cooldown,
            block=should_block,
        )


__all__ = [
    "BILLING_COOLDOWN_SECONDS",
    "RATE_LIMIT_COOLDOWN_SECONDS",
    "CredentialRouter",
    "CredentialScopeError",
    "ScopeKey",
    "cooldown_for_failure",
]
