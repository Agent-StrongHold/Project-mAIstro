---
id: ADR-063
title: Credential Pool and Automatic Key Rotation
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-20
substrate: []
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
ac-modules:
  AC-1: maistro.credentials.pool
  AC-2: maistro.credentials.pool
  AC-3: maistro.credentials.pool
  AC-4: maistro.credentials.pool
  AC-5: maistro.credentials.pool
  AC-6: maistro.credentials.pool
  AC-7: maistro.credentials.pool
  AC-8: maistro.credentials.pool
  AC-9: maistro.credentials.pool
  AC-10: maistro.credentials.router
  AC-11: maistro.credentials.router
  AC-12: maistro.credentials.router
  AC-13: maistro.credentials.router
  AC-14: maistro.credentials.router
  AC-15: maistro.credentials.router
  AC-16: maistro.credentials.router
  AC-17: maistro.credentials.pool
  AC-18: maistro.credentials.pool
  AC-19: maistro.credentials.router
  AC-20: maistro.credentials.router
  AC-21: maistro.credentials.pool
  AC-22: maistro.credentials.pool
  AC-23: maistro.credentials.pool
  AC-24: maistro.credentials.router
  AC-25: maistro.credentials.router
  AC-26: maistro.credentials.router
  AC-27: maistro.credentials.router
  AC-28: maistro.credentials.pool
  AC-29: maistro.credentials.pool
  AC-30: maistro.credentials.router
  AC-31: maistro.credentials.router
  AC-32: maistro.credentials.pool
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-20
  - status: Accepted
    date: 2026-05-20
---

# ADR-063: Credential Pool and Automatic Key Rotation

**Status:** Accepted
**Date:** 2026-05-20
**Tranche:** T4
**Depends on:** IMP-001 (error classifier, `maistro/resilience/classifier`)

---

## Context

The evolution engine (`maistro-evolve`) evaluates hundreds of genomes per cycle against paid LLM APIs. Currently, each provider is configured with a single API key via environment variable. This creates two problems:

1. **Single point of failure.** A rate-limit (429) or billing exhaustion (402) on one key halts the entire evolution cycle. Overnight runs stall at 3 AM with no recovery until a human intervenes.
2. **Throughput ceiling.** A single key constrains parallelism. With a pool of N keys, the engine can sustain N times the request rate before hitting provider limits.

Hermes and OpenClaw independently built credential pools, confirming this is table-stakes infrastructure for any system making high-volume paid API calls.

LiteLLM has basic key rotation but no strategy selection, no per-key cooldown tracking, and no integration with the IMP-001 error classifier. Building our own pool gives full control over rotation logic and enables smarter decisions based on classified errors.

## Decision

Introduce `maistro.credentials` — a new package implementing IMP-011 (multi-credential pool) and IMP-012 (automatic key rotation with cycling).

### 1. Credential record

Each key in the pool is tracked by a `CredentialRecord`:

```python
@dataclass
class CredentialRecord:
    key_id: str
    provider: str
    api_key: str
    priority: int = 0

    # Status tracking
    last_status: int | None = None
    last_error_code: str | None = None
    cooldown_until: float | None = None

    # Usage stats
    use_count: int = 0
    error_count: int = 0
    last_used_at: float | None = None

    # Derived
    @property
    def is_available(self) -> bool:
        """True when not in cooldown and not permanently blocked."""
        if self.cooldown_until is None:
            return True
        return time.monotonic() >= self.cooldown_until
```

### 2. Selection strategies

Four strategies, configurable per provider:

| Strategy | Behavior |
|----------|----------|
| `fill_first` | Use highest-priority key until it enters cooldown, then fall to next priority. Maximizes predictability. |
| `round_robin` | Cycle through all available keys in insertion order. Spreads load evenly. |
| `random` | Select uniformly at random from available keys. Prevents thundering herd when multiple consumers share a pool. |
| `least_used` | Pick the available key with the lowest `use_count`. Self-balances over time. |

Strategy is set in `config.yaml` per provider, defaulting to `round_robin`.

### 3. Two-level retry loop

The core execution pattern is a two-level loop:

- **Inner loop** (per-key): retries the same key with jittered exponential backoff for transient errors (5xx, network timeouts, server disconnects). Uses IMP-001 classification to identify `retryable=True` errors. Default: up to 3 retries with backoff `2s, 4s, 8s`.
- **Outer loop** (pool-level): on rate-limit (429) or billing (402) errors, places the current key in cooldown and rotates to the next available key. Continues until either a request succeeds or all keys are exhausted.

```python
async def execute_with_pool(
    pool: CredentialPool,
    provider: str,
    call_fn: Callable[[str], Awaitable[T]],
    *,
    max_retries: int = 3,
    backoff_config: BackoffConfig | None = None,
) -> T:
    """
    Inner loop: retry same key on transient errors.
    Outer loop: rotate keys on rate-limit/billing errors.
    Raises PoolExhaustedError when all keys are in cooldown.
    """
```

### 4. Cooldown semantics

- **429 (rate limit):** cooldown = `min(60s, Retry-After header value)`. Key becomes available after cooldown expires.
- **402 (billing):** cooldown = `3600s` (1 hour). Billing exhaustion is unlikely to resolve quickly.
- **Transient errors:** no cooldown. Inner loop retries with backoff; key stays available for other consumers.
- **Permanent errors (401, 403):** key is marked `blocked=True`. Requires manual intervention or admin API call to reset.

### 5. PoolExhaustedError

When all keys are in cooldown or blocked:

```python
class PoolExhaustedError(Exception):
    provider: str
    total_keys: int
    blocked_keys: int
    cooling_down_keys: int
    soonest_available_at: float  # monotonic timestamp

    @property
    def wait_seconds(self) -> float:
        return max(0.0, self.soonest_available_at - time.monotonic())
```

Callers can inspect `wait_seconds` to decide whether to sleep and retry or propagate the error.

### 6. Protocol-driven design

Following the engine's DI conventions (ADR-019), the pool is accessed through a protocol:

```python
class CredentialProvider(Protocol):
    async def acquire(self, provider: str) -> CredentialRecord: ...
    async def release(self, provider: str, key_id: str, status: int, error: Exception | None) -> None: ...
    async def get_stats(self, provider: str) -> PoolStats: ...
```

This allows in-memory pools for single-process evolution runs and distributed pools (backed by Redis or PostgreSQL) for multi-node deployments without changing business logic.

### 7. Stats and reporting

```python
@dataclass
class PoolStats:
    provider: str
    strategy: SelectionStrategy
    total_keys: int
    available_keys: int
    blocked_keys: int
    cooling_down_keys: int
    total_use_count: int
    total_error_count: int
    per_key: list[CredentialRecord]
```

Exposed via the `/admin/credentials` endpoint in `maistro-server` and logged every 60 seconds during evolution runs.

## Consequences

- **Positive:** Evolution runs survive rate limits and billing exhaustion on individual keys. Throughput scales linearly with the number of keys per provider.
- **Positive:** Strategy selection lets operators tune for cost spreading (`round_robin`), predictability (`fill_first`), or load balancing (`least_used`).
- **Positive:** Integration with IMP-001 classifier means rotation decisions are based on classified error semantics, not raw HTTP status codes alone.
- **Negative:** Adds operational complexity. Operators must manage multiple keys per provider and monitor for blocked keys.
- **Negative:** In-memory pool state is lost on process restart. Distributed deployments need a shared store (future ADR).
- **Risk:** If all keys belong to the same billing account, billing exhaustion (402) blocks all keys simultaneously. Mitigation: key diversity across billing accounts where possible.

## Out of scope

- Persistent credential storage (separate ADR, likely PostgreSQL-backed `CredentialStore`)
- OAuth token refresh (IMP-049)
- Auto-discovery of credentials from CLI tools (IMP-050)
- Distributed pool with shared state across processes (IMP-051)
- Admin API for adding/removing keys at runtime (IMP-052)
- Integration with HashiCorp Vault or AWS Secrets Manager (per-product concern)

## File layout

```
maistro/credentials/
├── __init__.py        # Public exports: CredentialPool, CredentialRecord, etc.
├── types.py           # SelectionStrategy enum, CredentialRecord, PoolStats, PoolExhaustedError
├── protocols.py       # CredentialProvider protocol
├── pool.py            # InMemoryCredentialPool implementation
├── strategies.py      # fill_first, round_robin, random, least_used strategy functions
└── rotation.py        # execute_with_pool two-level retry/rotation loop
```

## Source references

- `docs/analysis/COMPETITIVE-IMPROVEMENTS.md` — IMP-011, IMP-012
- Hermes credential pool — strategy-based selection
- OpenClaw credential pool — automatic cycling
- `packages/maistro-core/src/maistro/resilience/classifier.py` — IMP-001 error classification

## Links

- PR: (pending)
- Issue: (pending)
- Follow-up work (unwritten): persistent credential store; distributed pool

---

## Gherkin Acceptance Criteria

### Feature: Pool selection strategies

> **Measurement note (2026-08-19).** These 32 scenarios are tagged `@AC-N` and
> measured by `scripts/check-ac-state.py`. Twenty-nine are bound to passing
> tests. Three stay `declared`:
>
> - **AC-15, AC-16, AC-19** — the 402/429 paths *through a request*. The
>   cooldown mechanics they rely on are proven (`record_failure` with a billing
>   cooldown, single-key exhaustion), but no test drives the specific
>   request-execution sequence each scenario describes, so binding one would
>   claim more than it shows.
>
> Every bound criterion caps at `passing`, not `reachable`: both
> `maistro.credentials.pool` and `maistro.credentials.rotation` are in
> `quality/reachability-baseline.json`. The key pool rotates, cools down,
> blocks on 401/403 and reports stats — and nothing in a running process calls
> it. Same shape as ADR-066's P1 layer.
>
> **Superseded by the 2026-09-02 note above:** #58 wired the pool into the
> canonical Invocation path (`maistro.container` → `effect_context` →
> `credential_routing` → `credentials.pool`), so pool and router left the
> unreachable baseline and their criteria can reach the `reachable` rung.

> **Measurement note (2026-09-02, #58).** The rotation scenarios below are
> now bound to `maistro.credentials.rotation`'s successor: #58 moved
> credential selection to Provider resolution and rotation to real Invocation
> outcomes (see the ac-modules map — `maistro.credentials.router`), and the
> detached `execute_with_pool` retry loop this feature originally assumed was
> removed with it. The behavioral table is unchanged: 429 cools (≤60s,
> honoring Retry-After), 402 cools an hour, 401/403 block, transients set no
> cooldown. Physical retries are whole new Invocations under later Attempts,
> owned by the canonical execution model — not a library sleep loop invisible
> to it. AC-24/25/26/27/30/31's anchors moved from `pool` to `router` for the
> same reason: the request-driven halves of those scenarios execute there
> now. One improvement: the old loop read `detail["status_code"]`, which the
> classifier never populated, so a 401 through `execute_with_pool` never
> actually blocked its key; the router reads the status off the raised error,
> and AC-24/AC-25 now have passing outcome-driven tests.

```gherkin
Feature: Credential pool selection strategies
  As the evolution engine
  I want to select API keys from a pool using configurable strategies
  So that I can optimize throughput, cost, and load distribution per provider

  Background:
    Given a credential pool for provider "openai" with 3 keys:
      | key_id | priority |
      | key-a  | 10       |
      | key-b  | 5        |
      | key-c  | 1        |

  @AC-1
  Scenario: fill_first selects highest-priority available key
    Given the pool strategy is "fill_first"
    When I acquire a credential for "openai"
    Then the selected key_id is "key-a"

  @AC-2
  Scenario: fill_first falls to next priority when top key is in cooldown
    Given the pool strategy is "fill_first"
    And key "key-a" is in cooldown for 60 seconds
    When I acquire a credential for "openai"
    Then the selected key_id is "key-b"

  @AC-3
  Scenario: round_robin cycles through keys in order
    Given the pool strategy is "round_robin"
    When I acquire a credential for "openai" 3 times in sequence
    Then the selections are ["key-a", "key-b", "key-c"]

  @AC-4
  Scenario: round_robin wraps around after exhausting the pool
    Given the pool strategy is "round_robin"
    When I acquire a credential for "openai" 5 times in sequence
    Then the selections are ["key-a", "key-b", "key-c", "key-a", "key-b"]

  @AC-5
  Scenario: round_robin skips keys in cooldown
    Given the pool strategy is "round_robin"
    And key "key-b" is in cooldown for 60 seconds
    When I acquire a credential for "openai" 4 times in sequence
    Then the selections are ["key-a", "key-c", "key-a", "key-c"]

  @AC-6
  Scenario: random selects from available keys only
    Given the pool strategy is "random"
    And key "key-c" is in cooldown for 60 seconds
    When I acquire a credential for "openai" 100 times
    Then only keys ["key-a", "key-b"] are ever selected
    And each key is selected between 30 and 70 times

  @AC-7
  Scenario: least_used selects the key with fewest uses
    Given the pool strategy is "least_used"
    And key "key-a" has been used 10 times
    And key "key-b" has been used 3 times
    And key "key-c" has been used 7 times
    When I acquire a credential for "openai"
    Then the selected key_id is "key-b"

  @AC-8
  Scenario: least_used breaks ties by priority
    Given the pool strategy is "least_used"
    And key "key-a" has been used 5 times
    And key "key-b" has been used 5 times
    And key "key-c" has been used 5 times
    When I acquire a credential for "openai"
    Then the selected key_id is "key-a"

  @AC-9
  Scenario: all strategies skip blocked keys
    Given the pool strategy is "round_robin"
    And key "key-b" is permanently blocked
    When I acquire a credential for "openai" 4 times in sequence
    Then the selections are ["key-a", "key-c", "key-a", "key-c"]
```

### Feature: Automatic rotation on rate-limit errors

```gherkin
Feature: Automatic key rotation on rate-limit (429) errors
  As the evolution engine
  I want the pool to automatically rotate to the next key on 429 errors
  So that overnight runs survive rate limits without human intervention

  @AC-10
  Scenario: 429 on first key rotates to second key and request succeeds
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    And the pool strategy is "fill_first"
    When I execute a request that returns 429 on "key-a"
    And the request succeeds on "key-b"
    Then the result is returned successfully
    And key "key-a" is in cooldown
    And key "key-b" is available

  @AC-11
  Scenario: 429 with Retry-After header sets cooldown to that value
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I execute a request that returns 429 on "key-a" with Retry-After 30
    Then key "key-a" cooldown is 30 seconds

  @AC-12
  Scenario: 429 without Retry-After header defaults to 60-second cooldown
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I execute a request that returns 429 on "key-a" without Retry-After header
    Then key "key-a" cooldown is 60 seconds

  @AC-13
  Scenario: inner loop retries transient 5xx on same key before rotating
    Given a credential pool for "openai" with keys ["key-a"]
    And the inner loop max retries is 3
    When I execute a request that returns 500 then 502 then 200 on "key-a"
    Then the result is returned successfully
    And "key-a" was attempted 3 times
    And no key rotation occurred

  @AC-14
  Scenario: transient errors do not trigger cooldown
    Given a credential pool for "openai" with keys ["key-a"]
    When I execute a request that returns 500 then 200 on "key-a"
    Then key "key-a" has no cooldown set
```

### Feature: Automatic rotation on billing errors

```gherkin
Feature: Automatic key rotation on billing (402) errors
  As the evolution engine
  I want the pool to rotate to the next key on 402 billing exhaustion
  So that a depleted billing account does not halt the run

  @AC-15
  Scenario: 402 rotates to next key with 1-hour cooldown
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    And the pool strategy is "fill_first"
    When I execute a request that returns 402 on "key-a"
    And the request succeeds on "key-b"
    Then the result is returned successfully
    And key "key-a" cooldown is 3600 seconds

  @AC-16
  Scenario: 402 on all keys causes pool exhaustion
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I execute a request that returns 402 on "key-a"
    And the request returns 402 on "key-b"
    Then a PoolExhaustedError is raised
    And the error soonest_available_at is within 3600 seconds from now
```

### Feature: Pool exhaustion error

```gherkin
Feature: PoolExhaustedError when all keys are unavailable
  As the evolution engine
  I want a clear error when all keys are exhausted
  So that I can decide whether to wait, fail gracefully, or alert

  @AC-17
  Scenario: all keys in cooldown raises PoolExhaustedError with soonest recovery
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    And key "key-a" is in cooldown for 30 seconds
    And key "key-b" is in cooldown for 120 seconds
    When I acquire a credential for "openai"
    Then a PoolExhaustedError is raised
    And error.wait_seconds is approximately 30
    And error.cooling_down_keys is 2

  @AC-18
  Scenario: all keys blocked raises PoolExhaustedError with infinite wait
    Given a credential pool for "openai" with keys ["key-a"]
    And key "key-a" is permanently blocked
    When I acquire a credential for "openai"
    Then a PoolExhaustedError is raised
    And error.blocked_keys is 1
    And error.wait_seconds is negative or zero

  @AC-19
  Scenario: single-key pool exhaustion on 429
    Given a credential pool for "openai" with keys ["key-a"]
    When I execute a request that returns 429 on "key-a"
    Then a PoolExhaustedError is raised
    And error.total_keys is 1

  @AC-20
  Scenario: PoolExhaustedError includes provider name
    Given a credential pool for "anthropic" with keys ["key-x"]
    And key "key-x" is in cooldown for 60 seconds
    When I acquire a credential for "anthropic"
    Then a PoolExhaustedError is raised
    And error.provider is "anthropic"
```

### Feature: Cooldown tracking and recovery

```gherkin
Feature: Cooldown expiration and key recovery
  As the credential pool
  I want keys to become available again after their cooldown expires
  So that the pool self-heals without manual intervention

  @AC-21
  Scenario: key becomes available after cooldown expires
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    And key "key-a" was put in cooldown 61 seconds ago with duration 60
    When I acquire a credential for "openai"
    Then key "key-a" is available and can be selected

  @AC-22
  Scenario: key is not available during cooldown
    Given a credential pool for "openai" with keys ["key-a"]
    And key "key-a" was put in cooldown 10 seconds ago with duration 60
    Then key "key-a" is not available

  @AC-23
  Scenario: release with success clears error state but preserves use_count
    Given a credential pool for "openai" with keys ["key-a"]
    And key "key-a" has last_error_code "rate_limit" and use_count 5
    When I release "key-a" with status 200 and no error
    Then key "key-a" last_status is 200
    And key "key-a" last_error_code is None
    And key "key-a" use_count is 6

  @AC-24
  Scenario: permanent error (401) blocks key immediately
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I release "key-a" with status 401
    Then key "key-a" is permanently blocked
    And key "key-a" is not available

  @AC-25
  Scenario: 403 blocks key immediately
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I release "key-a" with status 403
    Then key "key-a" is permanently blocked

  @AC-26
  Scenario: cooldown duration is capped at 60 seconds for rate limit
    Given a credential pool for "openai" with keys ["key-a"]
    When I release "key-a" with status 429 and no Retry-After header
    Then key "key-a" cooldown is at most 60 seconds

  @AC-27
  Scenario: cooldown from Retry-After is capped at 60 seconds
    Given a credential pool for "openai" with keys ["key-a"]
    When I release "key-a" with status 429 and Retry-After 300
    Then key "key-a" cooldown is 60 seconds
```

### Feature: Stats and reporting

```gherkin
Feature: Credential pool statistics and reporting
  As an operator
  I want visibility into pool health and key utilization
  So that I can detect blocked keys, uneven load, and exhaustion risk

  @AC-28
  Scenario: pool stats reflect current state
    Given a credential pool for "openai" with keys ["key-a", "key-b", "key-c"]
    And key "key-a" has use_count 100 and error_count 2
    And key "key-b" has use_count 80 and is in cooldown for 30 seconds
    And key "key-c" is permanently blocked
    When I get stats for "openai"
    Then total_keys is 3
    And available_keys is 1
    And cooling_down_keys is 1
    And blocked_keys is 1
    And total_use_count is 180
    And total_error_count is 2

  @AC-29
  Scenario: pool stats include per-key breakdown
    Given a credential pool for "openai" with keys ["key-a", "key-b"]
    When I get stats for "openai"
    Then per_key contains records for "key-a" and "key-b"
    And each record includes key_id, use_count, error_count, and is_available

  @AC-30
  Scenario: acquire increments use_count and updates last_used_at
    Given a credential pool for "openai" with keys ["key-a"]
    And key "key-a" has use_count 0
    When I acquire a credential for "openai"
    Then key "key-a" use_count is 1
    And key "key-a" last_used_at is set to the current time

  @AC-31
  Scenario: error response increments error_count
    Given a credential pool for "openai" with keys ["key-a"]
    When I release "key-a" with status 429 and an error
    Then key "key-a" error_count is 1

  @AC-32
  Scenario: stats report strategy name
    Given a credential pool for "openai" with strategy "least_used"
    When I get stats for "openai"
    Then strategy is "least_used"
```
