---
id: ADR-023
title: 'Agent Crypto Operations & Spending Policy'
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-022
implements: []
related:
  - maistro-engine#ADR-024
  - maistro-engine#ADR-025
  - maistro-engine#ADR-027
  - maistro-engine#ADR-028
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-07
---

# ADR-023: Agent Crypto Operations & Spending Policy

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed), ADR-022 (Hardware Signing)

---

## Context

Once the Conductor Seed (ADR-021) can derive wallet keys, the natural question is: can the agent spend? A single prompt-injection could drain a wallet if signing is unconstrained. The naive "never" answer forfeits the crypto-native value proposition. We need a structured policy that makes "agent has wallet" sane.

**This entire spec is opt-in.** A conductor with no crypto plugins installed has no wallet, no LN node, signs no transactions, and functions fully. The wizard's crypto step defaults to **Skip**. The Conductor Seed is generated regardless because it is the root of trust for *all* signing — AgentSpec, audit log, elevation — not just wallets.

**Source:** `Project_mAIstro/specs/security/S-151-agent-crypto-ops.md` (216 lines)

## Decision

Four parts: (1) three-stage transaction model, (2) per-path spending policy, (3) hot/cold wallet separation, (4) unified HITL signing via the hot wallet.

### 1. Three-stage transaction model: propose → sign → execute

- **Propose** — agent constructs a transaction intent (chain, recipient, amount, reason). Intent lands in elevation queue. Agent never sees private keys.
- **Sign** — dashboard/mobile push presents structured diff. Admin signs with seed (ADR-021) or hardware wallet (ADR-022). Within hot-wallet policy bounds, conductor signs directly.
- **Execute** — broadcast via configured RPC. Result recorded in audit log with signed tx hash.

### 2. Spending policy (per-derivation-path)

```yaml
policy:
  path: m/44'/0'/1'          # Bitcoin hot wallet
  daily_cap_sats: 100000      # 0.001 BTC/day
  transaction_cap_sats: 25000 # max single tx
  cooling_off_hours: 24       # new addresses wait 24h
  whitelist_only: false
  velocity_per_hour: 5
  on_breach: deny             # deny | escalate-to-cold
```

Defaults: `daily_cap_sats: 0` (receive-only until admin sets non-zero cap). Policy changes require admin signature.

### 3. Hot vs. cold wallet pattern

```
m/44'/<chain>'/0' = COLD — admin signature required for every tx
m/44'/<chain>'/1' = HOT  — conductor signs within policy bounds, balance hard-capped
```

Cold refills hot on admin-approved schedule. Compromise of hot = bounded loss.

### 4. Unified HITL signing via hot wallet

The same signing primitive that authorizes a 1000-sat tip also authorizes a HITL elevation request. Admin's mobile wallet (Phoenix, Mutiny, Zeus, Breez) becomes the universal signing surface via BIP-322.

### Lightning support (day one)

- LDK embedded or sidecar; hot-channel balance cap (default $50 worth)
- Channel open/close requires admin (cold) signature
- Auto-receive; spending unlocked by admin via dashboard
- Public Lightning address: `<instance>@<conductor-host>` via LNURL or BOLT-12

### Bouncer integration

New regex tier for crypto-operation prompts: `send all`, `drain`, `unstake everything`, known-bad addresses. A Bouncer hit on a crypto operation is **non-recoverable** — intent never reaches propose stage.

### Phantom-via-testnet rule

Every wallet plugin must have successful testnet/signet history before any mainnet operation. Phantom detects wallet ops, swaps to testnet RPC, runs proposed op against test funds.

## Interface (spec)

```python
@dataclass
class SpendingPolicy:
    path: str
    daily_cap_sats: int = 0
    transaction_cap_sats: int = 0
    cooling_off_hours: int = 24
    whitelist_only: bool = False
    velocity_per_hour: int = 5
    on_breach: str = "deny"

@dataclass
class TransactionIntent:
    chain: str
    type: str           # "send" | "swap" | "channel_open" etc.
    recipient: str
    amount_sats: int
    reason: str
    requesting: dict    # skill + invocation_id
    policy_check: str   # "passed" | "violation_details"

class CryptoOps:
    def propose(self, intent: TransactionIntent) -> str: ...    # returns intent_id
    def check_policy(self, intent: TransactionIntent) -> bool: ...
    def sign_cold(self, intent_id: str) -> bytes: ...           # requires admin
    def sign_hot(self, intent_id: str) -> bytes | None: ...     # auto within policy
    def execute(self, intent_id: str, signature: bytes) -> str: ...  # returns tx_hash
```

## Acceptance criteria

- [ ] Conductor with no crypto plugins runs end-to-end with no wallet code paths invoked
- [ ] Wizard crypto step defaults to Skip
- [ ] Propose/sign/execute round-trip works on signet for Bitcoin, Lightning, and one EVM chain
- [ ] Daily cap blocks exceeding txs; override requires cold-key signature
- [ ] Cooling-off enforced: tx to new address queued until period elapses
- [ ] Hot-channel balance cap respected; auto-refill from cold requires admin signature
- [ ] Bouncer rejects "send all"/"drain" patterns at propose stage
- [ ] Phantom blocks mainnet with no testnet history; promotion requires admin sign-off
- [ ] Spending policy per-path, configurable via dashboard; policy edits require admin signature
- [ ] Audit log records every signed operation with modality, path, intent, signature, result

## Out of scope

- Wallet app development (uses existing BIP-322-compatible wallets)
- Exchange integration (CEX/DEX)
- Multi-chain smart contract interaction beyond basic send
- Faucet implementation details (uses existing community faucets)

## Source references

- `~/maistro-engine/specs/security/S-151-agent-crypto-ops.md` — full 216-line spec

## Links

- Source spec: S-151
- Related ADRs: ADR-021 (Conductor Seed), ADR-022 (Hardware Signing), ADR-024 (DID/VC), ADR-025 (Electrum Server), ADR-027 (Lightning Federation), ADR-028 (Privilege Separation)
