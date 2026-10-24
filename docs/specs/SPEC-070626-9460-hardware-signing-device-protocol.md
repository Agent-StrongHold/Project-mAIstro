---
id: SPEC-070626-9460
title: "Hardware signing device protocol and simulated device (no physical transport)"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-022
implements:
  - maistro-engine#ADR-022
related:
  - maistro-engine#ADR-023
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

# SPEC-070626-9460: Hardware signing device protocol and simulated device

> **Unresolved on migration.** Migrated at `Proposed` to preserve design intent,
> not reconciled against ADR-022. Automated review (#457) raised, and this was
> verified against the ADR text:
>
> - **Software fallback contradicts ADR-022's fail-closed requirement.**
>   ADR-022 states "Hardware unplugged: conductor enters degraded mode (no
>   signing) rather than crashing". This spec's mode ladder falls back to a
>   retained software seed after a disconnect, which defeats the boundary an
>   operator chose a hardware-backed mode to get. Remove the fallback or amend
>   the ADR.
> - `SignatureResult` records `mode_used` but no device/key identity, so two
>   devices of the same vendor are indistinguishable in an audit record.

## Context

ADR-022 specifies a signing-mode ladder — hardware devices (Ledger, Trezor, YubiKey, mobile)
preferred over software signing, with graceful degradation between modes. Today only the
software mode exists (`ConductorSeed.sign`, ADR-021). No physical device or HID/WebUSB
transport library is available in this environment to build and test real hardware drivers
against, so this SPEC establishes the `SigningDevice` protocol and mode-selection ladder with a
simulated/fake device as the only concrete implementation — the interface real device drivers
will implement later, proven end-to-end against a fake rather than left as an unverified
sketch.

## Goals

- `SigningDevice` protocol: detect, sign, get public key, disconnect — the shape any real
  Ledger/Trezor/YubiKey/mobile driver will implement.
- A mode-selection ladder: prefer the highest-priority *connected* device; fall back to
  `ConductorSeed` software signing (Mode 4) when no hardware device is detected or a detected
  device fails.
- `SimulatedSigningDevice` — an in-memory fake implementing the protocol, usable for testing
  the ladder and for local development without real hardware.
- A signing-modality audit record: every signature records which mode/device signed it, so a
  security review can distinguish hardware-backed signatures from software fallback ones.

## Non-goals

- Real Ledger/Trezor/YubiKey/mobile transport implementations (WebUSB, HID, BLE, platform
  authenticator APIs) — no physical device or transport library is available to build and test
  against in this environment; those are follow-up work implementing this SPEC's protocol.
- Device provisioning/pairing UX — hive-conductor frontend concern.

## Decision

### SigningDevice protocol and modes

```python
# maistro/identity/hardware_signing.py

class SigningMode(IntEnum):
    """Lower value = higher priority in the fallback ladder."""
    HARDWARE_LEDGER = 1
    HARDWARE_TREZOR = 2
    HARDWARE_YUBIKEY = 3
    SOFTWARE = 4   # ConductorSeed.sign — always available, the guaranteed floor

class SigningDevice(Protocol):
    mode: SigningMode

    async def detect(self) -> bool:
        """Is this device currently connected and ready?"""

    async def sign(self, path: str, message: bytes) -> bytes:
        """Sign message using the key at path on-device. Raises
        DeviceDisconnectedError if detect() would now return False,
        DeviceUserRejectedError if the on-device confirmation was declined."""

    async def public_key(self, path: str) -> bytes: ...

    async def disconnect(self) -> None: ...
```

### Mode-selection ladder

```python
@dataclass
class SigningLadder:
    """Tries devices in SigningMode priority order; ConductorSeed software
    signing is always the final fallback (never itself in the `devices` list --
    it's the built-in floor)."""
    devices: tuple[SigningDevice, ...]
    software_seed: ConductorSeed

    async def sign(self, path: str, message: bytes) -> SignatureResult:
        """Try each device in priority order (detect() first, then sign());
        on DeviceDisconnectedError or detect()=False, try the next; on
        DeviceUserRejectedError, stop and propagate (a user rejection is not
        a fallback trigger — it's an explicit refusal). If every device is
        unavailable, falls back to software_seed.sign(path, message).
        Returns SignatureResult(signature, mode_used) so the caller/audit
        trail knows which mode actually signed."""

@dataclass(frozen=True)
class SignatureResult:
    signature: bytes
    mode_used: SigningMode
```

### Simulated device (test/dev fake)

```python
class SimulatedSigningDevice(SigningDevice):
    """In-memory fake: a fixed keypair, toggleable connected/rejects-next-sign
    state for exercising the ladder's fallback and user-rejection paths."""
    mode: SigningMode

    def __init__(self, mode: SigningMode, *, connected: bool = True) -> None: ...
    def set_connected(self, connected: bool) -> None: ...
    def reject_next_sign(self) -> None: ...
```

### Audit

Every `SigningLadder.sign()` call's `SignatureResult.mode_used` is recorded by the caller into
the ADR-037 event log (`signing.completed` with `mode` field) — the ladder itself does not
emit events (kept as a pure library primitive, matching the codebase's DI convention); callers
that care about audit trails pass the result to their own event emission.

## Acceptance criteria

- [ ] `SigningLadder.sign()` with all `devices` disconnected falls back to
      `software_seed.sign()`, returning `mode_used=SigningMode.SOFTWARE`.
- [ ] `SigningLadder.sign()` with the highest-priority device connected uses it, returning that
      device's `mode` — lower-priority devices and software are never consulted (property:
      first connected device in priority order wins).
- [ ] A device that raises `DeviceDisconnectedError` mid-sign causes the ladder to try the next
      device/software, not propagate the disconnection as a hard failure.
- [ ] A device that raises `DeviceUserRejectedError` propagates immediately — the ladder does
      NOT fall back to a lower-priority device or software on an explicit user rejection
      (property: rejection is terminal, not a trigger for silently trying another signer).
- [ ] `SimulatedSigningDevice` correctly implements the full protocol (detect/sign/public_key/
      disconnect) and its `set_connected`/`reject_next_sign` test hooks work as documented.
- [ ] The mode-priority ordering (`Ledger < Trezor < YubiKey < Software`, by
      `IntEnum` value) is enforced by the ladder regardless of the order devices are listed in
      `devices`.

## Testing

- Unit: ladder with 0/1/N devices, each device connected/disconnected/rejecting, verifying
  correct fallback and correct `mode_used`.
- Unit: `SimulatedSigningDevice` protocol conformance (a generic protocol-conformance test that
  any future real driver can also run against).
- Property (Hypothesis): for any generated sequence of device connected/rejecting states, the
  ladder either (a) uses the highest-priority connected non-rejecting device, or (b) falls back
  to software if none are connected, or (c) propagates a rejection from whichever device was
  tried — never silently drops a signing request.

## Open questions

- Real device transports (WebUSB for Ledger, HID for Trezor, platform authenticator for
  YubiKey/mobile) are explicitly deferred (Non-goals) pending access to physical hardware or
  transport libraries to test against — this SPEC's acceptance criteria are scoped to the
  protocol + simulated device only.

## References

- [ADR-022: Hardware Signing Devices](../adr/ADR-022-hardware-signing.md)
- [ADR-021: Conductor Seed](../adr/ADR-021-conductor-seed.md) — software signing floor
- [ADR-023: Agent Crypto Operations & Spending Policy](../adr/ADR-023-agent-crypto-ops.md) — a consumer of signing mode for spending-policy tiering
