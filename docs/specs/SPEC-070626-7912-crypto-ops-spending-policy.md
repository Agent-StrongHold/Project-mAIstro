---
id: SPEC-070626-7912
title: "Agent crypto operations: SpendingPolicy and TransactionIntent gating (testnet-only, no execution backend)"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-022
  - maistro-engine#ADR-023
implements:
  - maistro-engine#ADR-023
related:
  - maistro-engine#ADR-068
  - maistro-engine#SPEC-070626-9460
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070626-7912: Agent crypto operations — SpendingPolicy and TransactionIntent (testnet-only)

> **Unresolved on migration.** Migrated at `Proposed` to preserve design intent,
> not reconciled against ADR-023. Automated review (#457) raised, and this was
> verified against the ADR text:
>
> - **`key_class` is taken from the agent-authored intent.** ADR-023 makes
>   hot/cold a property of the derivation path (`m/44'/<chain>'/0' = COLD —
>   admin signature required for every tx`), so a caller-supplied class lets an
>   agent self-declare `cold` and route around the hot-key cap. Classification
>   must come from trusted wallet state.
> - The daily cap is evaluated against a caller-supplied snapshot with no atomic
>   reservation, so concurrent intents can both pass and exceed it.
> - Non-positive `amount_sats` passes every documented upper-bound check.
> - `ApproverGraph.resolve()` maps scopes but never returns an approve/deny
>   outcome, so the documented denial path has no operation that can produce it.

## Context

ADR-023 specifies how agents propose, gate, and (if approved) execute value-moving operations
— spending limits, hot/cold key classification, approval tiers integrating with ADR-068's
authorization ladder. This SPEC builds the policy/gating layer — the part that is pure logic
and fully testable without a real wallet backend — and stops short of real execution. No
LDK/bitcoin/lightning library is a dependency, so "execution" is a typed interface an actual
wallet backend implements later; this SPEC's default and only shipped backend operates against
a testnet-only simulated ledger, making unsafe-by-default value movement structurally
impossible until a real backend is deliberately wired in.

## Goals

- `SpendingPolicy`: per-agent limits (max per-transaction, max per-day, hot/cold key
  classification) that a `TransactionIntent` is checked against before any execution is
  attempted.
- `TransactionIntent`: an agent's proposed value-moving action — amount, destination, purpose —
  as a first-class typed object, never a bare dict, so policy checks and audit trails have a
  stable shape to key off.
- Approval-tier integration: intents exceeding policy thresholds require ADR-068 elevation
  before execution proceeds (reuses the existing approver-graph/elevation machinery from
  SPEC-246/247 rather than inventing a parallel approval mechanism).
- `CryptoExecutionBackend` protocol with a `TestnetSimulatedBackend` default — the only backend
  that ships; it moves simulated testnet balances only, never real funds, and is the safe
  default for any environment that hasn't explicitly wired a real backend.

## Non-goals

- Real Bitcoin/Lightning execution (LDK, BOLT-12, on-chain broadcast) — no such library is a
  dependency; `CryptoExecutionBackend` is the seam a real implementation plugs into later, out
  of scope here.
- Hot/cold key *custody* mechanics beyond classification — actual key isolation (e.g. cold keys
  living on an air-gapped signer) depends on ADR-022's hardware signing ladder
  (SPEC-070626-9460), reused here, not reimplemented.
- Phantom/mempool monitoring, fee estimation, UTXO selection — real-wallet concerns that only
  matter once a real `CryptoExecutionBackend` exists.

## Decision

### TransactionIntent and SpendingPolicy

```python
# maistro/identity/crypto_ops.py

@dataclass(frozen=True)
class TransactionIntent:
    """An agent's proposed value-moving action. Immutable once created —
    any policy-driven modification (e.g. amount capped) produces a new intent,
    never mutates in place, so the audit trail is unambiguous about what was
    originally proposed vs. what was approved."""
    agent_id: str
    amount_sats: int              # always integer satoshis; no float amounts anywhere
    destination: str               # address/invoice/identifier, backend-interpreted
    purpose: str                   # human-readable justification, always required
    key_class: Literal["hot", "cold"]
    network: Literal["testnet", "mainnet"] = "testnet"

@dataclass(frozen=True)
class SpendingPolicy:
    agent_id: str
    max_per_transaction_sats: int
    max_per_day_sats: int
    hot_key_daily_cap_sats: int     # tighter cap specifically for hot-key intents
    require_elevation_above_sats: int  # intents over this always need ADR-068 elevation
    allowed_networks: tuple[Literal["testnet", "mainnet"], ...] = ("testnet",)

class SpendingPolicyStore(Protocol):
    async def get(self, agent_id: str) -> SpendingPolicy: ...
```

### Policy evaluation

```python
class PolicyVerdict(StrEnum):
    APPROVED = "approved"                    # within limits, no elevation needed
    NEEDS_ELEVATION = "needs_elevation"       # over require_elevation_above_sats
    DENIED_NETWORK = "denied_network"         # network not in allowed_networks
    DENIED_LIMIT = "denied_limit"             # exceeds max_per_transaction or daily cap

async def evaluate_intent(
    intent: TransactionIntent,
    policy: SpendingPolicy,
    *,
    spent_today_sats: int,        # caller-supplied running total for the agent/day
) -> PolicyVerdict:
    """Pure function: network check first (mainnet fails closed unless
    explicitly allowed), then per-transaction cap, then daily cap (using the
    tighter hot_key_daily_cap_sats when key_class == "hot"), then the
    elevation threshold. Never mutates intent or policy."""
```

`evaluate_intent` never itself calls anything — no side effects, no network I/O, fully
deterministic given its three inputs, so it is trivially property-testable.

### Execution backend and testnet-only default

```python
class CryptoExecutionBackend(Protocol):
    async def execute(
        self, intent: TransactionIntent, *, signature: bytes
    ) -> "ExecutionResult":
        """Actually move value. Real implementations plug in here; NOT part
        of this SPEC's shipped code beyond the testnet simulator below."""

@dataclass(frozen=True)
class ExecutionResult:
    tx_id: str
    network: Literal["testnet", "mainnet"]
    confirmed: bool

class TestnetSimulatedBackend(CryptoExecutionBackend):
    """The only backend this SPEC ships. Maintains simulated per-agent
    testnet balances in memory; execute() on a mainnet intent raises
    MainnetExecutionNotSupportedError unconditionally — there is no code
    path in this backend that can move real funds."""

    async def execute(self, intent: TransactionIntent, *, signature: bytes) -> ExecutionResult:
        if intent.network != "testnet":
            raise MainnetExecutionNotSupportedError(intent.network)
        ...
```

### Approval-tier integration (ADR-068 reuse)

```python
async def propose_and_execute(
    intent: TransactionIntent,
    *,
    policy_store: SpendingPolicyStore,
    backend: CryptoExecutionBackend,
    signing_ladder: SigningLadder,     # SPEC-070626-9460
    approver_graph: ApproverGraph,     # SPEC-246, reused unchanged
    spent_today_sats: int,
) -> ExecutionResult:
    """
    1. evaluate_intent -> verdict.
    2. DENIED_* -> raise SpendingPolicyDeniedError(verdict) immediately, no signing attempted.
    3. NEEDS_ELEVATION -> resolve via approver_graph (SPEC-246's existing resolution,
       not a new approval mechanism); denial there raises the same error type
       elevation flows already raise (SPEC-247).
    4. APPROVED (directly or after elevation) -> sign via signing_ladder, then
       backend.execute(intent, signature=...).
    """
```

## Acceptance criteria

- [ ] `evaluate_intent` returns `DENIED_NETWORK` for an intent whose `network` is not in
      `policy.allowed_networks`, before checking any amount limits (network check is first and
      fails closed).
- [ ] `evaluate_intent` returns `DENIED_LIMIT` when `amount_sats > max_per_transaction_sats`,
      regardless of daily totals (property: single-transaction cap is enforced independent of
      the daily cap).
- [ ] `evaluate_intent` returns `DENIED_LIMIT` when `spent_today_sats + amount_sats` exceeds
      `max_per_day_sats` (or `hot_key_daily_cap_sats` for hot-key intents) — the tighter hot-key
      cap is used whenever `key_class == "hot"`, never the looser general daily cap.
- [ ] `evaluate_intent` returns `NEEDS_ELEVATION` when `amount_sats >
      require_elevation_above_sats` and none of the DENIED_* conditions apply.
- [ ] `evaluate_intent` returns `APPROVED` only when none of the above conditions trigger
      (property: APPROVED implies within both per-transaction and daily limits, on an allowed
      network, and at or below the elevation threshold).
- [ ] `TestnetSimulatedBackend.execute()` on a mainnet-network intent raises
      `MainnetExecutionNotSupportedError` unconditionally (property: no input produces a
      successful mainnet execution result from this backend).
- [ ] `propose_and_execute` denies before signing for any `DENIED_*` verdict (signing_ladder is
      never invoked — asserted via a signing ladder that raises if called).
- [ ] `propose_and_execute` for a `NEEDS_ELEVATION` verdict routes through the existing
      `ApproverGraph` resolution (SPEC-246) rather than a bespoke approval path.

## Testing

- Unit: `evaluate_intent` across all four verdict branches, boundary conditions (exactly at
  each cap), hot vs. cold key_class daily-cap selection.
- Unit: `TestnetSimulatedBackend` execute happy path (testnet) and denial (mainnet).
- Unit: `propose_and_execute` end-to-end for APPROVED, NEEDS_ELEVATION (mocked approver graph
  approving and denying), and each DENIED_* case (signing ladder never called).
- Property (Hypothesis): for any generated `(intent, policy, spent_today_sats)` triple,
  `evaluate_intent`'s verdict is consistent with a direct re-derivation from the four
  conditions in priority order (network, per-tx limit, daily limit, elevation threshold) —
  guards against the implementation silently reordering checks.

## Open questions

- Whether `SpendingPolicyStore` should support per-agent policy overrides layered on a
  product-wide default (similar to ADR-053 recipe overlays), or require every agent to have an
  explicit policy row — leaning toward requiring explicit policy (no implicit default,
  matching ADR-057's "no implicit default" precedent for memory exposure mode) so a
  newly-onboarded agent cannot spend before an operator has deliberately set its limits.
- Real `CryptoExecutionBackend` implementations (Bitcoin on-chain, Lightning via LDK) are
  entirely out of scope here per the ADR-023 build decision — this SPEC only guarantees the
  seam exists and that the shipped default cannot move real value.

## References

- [ADR-023: Agent Crypto Operations & Spending Policy](../adr/ADR-023-agent-crypto-ops.md)
- [ADR-068: Unified Authorization & Elevation](../adr/ADR-068-unified-authorization-and-elevation.md)
- [SPEC-246: Approver graph](SPEC-246-authz-approver-graph.md)
- [SPEC-247: Elevation flows](SPEC-247-authz-elevation-flows.md)
- [SPEC-070626-9460: Hardware signing device protocol](SPEC-070626-9460-hardware-signing-device-protocol.md)
