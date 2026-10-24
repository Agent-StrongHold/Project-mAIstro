---
id: SPEC-222
title: "Credential pool: selection strategies, cooldown tracking, and rotation"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-038
  - maistro-engine#ADR-063
implements:
  - maistro-engine#ADR-063
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-core/tests/credentials/test_pool.py
  - packages/maistro-core/tests/credentials/test_credential_store.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-222: Credential pool: selection strategies, cooldown tracking, and rotation

## Context

Single-key provider configuration meant any rate limit or billing failure
from a provider stalled all requests for that provider until a human
intervened. ADR-063 decided to ship a `maistro.credentials` package with a
pool of equivalent keys per provider, pluggable selection strategies, and
automatic rotation/cooldown on failure, so a single exhausted or
rate-limited key degrades gracefully instead of blocking the provider.

## Goals

- `CredentialPool`: holds `CredentialRecord`s for one provider, selects via
  `SelectionStrategy` (`fill_first | round_robin | random | least_used`),
  tracks per-key use/error counts and cooldown/blocked state.
- `execute_with_pool`: runs a call against the pool, retrying on the same
  key with jittered backoff, rotating keys on rate-limit/billing/auth
  failures, raising `PoolExhaustedError` when no key is usable.
- `CredentialProvider` Protocol (`acquire`/`release`/`get_stats`) for
  store-backed pool implementations.

## Non-goals

- Persisted credential storage — `store.py`/`providers.py` exist
  alongside this spec's pool/rotation surface but are not covered here.
- Cross-provider fallback (e.g. falling back from one model provider to
  another) — pool rotation is within a single provider's key set only.

## Decision

`packages/maistro-core/src/maistro/credentials/types.py`:

```python
class SelectionStrategy(StrEnum):
    FILL_FIRST, ROUND_ROBIN, RANDOM, LEAST_USED

@dataclass class CredentialRecord:
    key_id, provider, api_key, priority=0
    last_status, last_error_code, cooldown_until, blocked=False
    use_count=0, error_count=0, last_used_at
    @property def is_available(self) -> bool: ...

@dataclass class PoolExhaustedError(Exception):
    message, provider="", total_keys=0, blocked_keys=0, cooling_down_keys=0, soonest_available_at
    @property def wait_seconds(self) -> float: ...

@dataclass class PoolStats:
    provider, strategy, total_keys=0, available_keys=0, blocked_keys=0,
    cooling_down_keys=0, total_use_count=0, total_error_count=0, per_key=[]
```

`packages/maistro-core/src/maistro/credentials/pool.py`:

```python
class CredentialPool:
    def __init__(self, provider, entries=None, strategy=SelectionStrategy.ROUND_ROBIN) -> None: ...
    def select(self) -> CredentialRecord: ...        # raises PoolExhaustedError when none available
    def record_success(self, key_id: str) -> None: ...
    def record_failure(self, key_id, status_code=0, error_code="", cooldown_seconds=0.0, block=False) -> None: ...
    def clear_cooldown(self, key_id: str) -> None: ...
    def get_stats(self) -> PoolStats: ...
```

`packages/maistro-core/src/maistro/credentials/rotation.py`:

```python
async def execute_with_pool[T](
    pool: CredentialPool,
    call_fn: Callable[[CredentialRecord], Awaitable[T]],
    *, max_retries=3, backoff_config=None, max_key_rotations=None,
) -> RotationResult[T]: ...
```

`packages/maistro-core/src/maistro/credentials/protocols.py`:

```python
@runtime_checkable
class CredentialProvider(Protocol):
    async def acquire(self, provider: str) -> CredentialRecord: ...
    async def release(self, provider, key_id, status, error=None) -> None: ...
    async def get_stats(self, provider: str) -> PoolStats: ...
```

`select()` raises `PoolExhaustedError` carrying the soonest cooldown
expiry and counts of blocked/cooling-down keys when no entry is
available. `execute_with_pool` classifies failures via
`maistro.resilience.classifier.classify_error`: HTTP 402 → 1-hour
cooldown without blocking; 401/403 → immediate block; 429/rate-limit →
60s cooldown (or `Retry-After` if shorter); retryable errors retry on the
same key with `jittered_backoff` before rotating. Rotation stops after
`pool.size` rotations (or `max_key_rotations` if given), then raises
`PoolExhaustedError`.

## Acceptance criteria

- [x] `CredentialPool.select()` supports `fill_first`, `round_robin`,
      `random`, and `least_used` strategies
- [x] `select()` raises `PoolExhaustedError` with `total_keys`,
      `blocked_keys`, `cooling_down_keys`, `soonest_available_at` when no
      key is available
- [x] `record_failure` cools down or blocks a key without removing it
      from the pool
- [x] `execute_with_pool` retries on the same key before rotating, and
      rotates on cooldown/block-triggering failures
- [x] `execute_with_pool` raises `PoolExhaustedError` after exhausting
      `max_key_rotations`
- [x] `CredentialProvider` Protocol exists for store-backed
      acquire/release/get_stats

## Testing

Covered by `packages/maistro-core/tests/credentials/test_pool.py` and
`test_credential_store.py`.

## Open questions

- `store.py` and `providers.py` (persisted credential storage backing
  `CredentialProvider`) exist in the same package but are not detailed in
  this spec — candidate for a follow-up spec if their surface grows
  independently.

## References

- [ADR-038: Reliability taxonomy](../adr/ADR-038-reliability-taxonomy.md)
- [ADR-063: Credential pool and rotation](../adr/ADR-063-credential-pool-and-rotation.md)
- `packages/maistro-core/src/maistro/credentials/types.py`
- `packages/maistro-core/src/maistro/credentials/pool.py`
- `packages/maistro-core/src/maistro/credentials/rotation.py`
- `packages/maistro-core/src/maistro/credentials/protocols.py`
