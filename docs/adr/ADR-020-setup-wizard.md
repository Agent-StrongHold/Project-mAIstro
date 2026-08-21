---
id: ADR-020
title: 'Setup Wizard — Browser-first install ceremony'
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-026
  - maistro-engine#ADR-028
  - maistro-engine#ADR-029
implements: []
related:
  - maistro-engine#ADR-022
  - maistro-engine#ADR-023
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-07
---

# ADR-020: Setup Wizard — Browser-first install ceremony

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed), ADR-026 (Internal Trust Root), ADR-028 (Privilege Separation), ADR-029 (Networking Substrate)

---

## Context

Fresh-install onboarding is the conversion moment. Every other subsystem in maistro-engine exists to support an operator going from `curl install.sh | sh` to a working conductor. If the wizard is bad, none of the other architectural choices reach a user.

The wizard must:
- Run in the browser with CLI fallback for headless installs
- Be identical across Linux / macOS / Windows
- Walk the operator through every required configuration step in one continuous flow
- Never produce an insecure install (two-user mandate, warden enabled, vault encrypted, substrate selected, TLS chosen)
- Take ~5 minutes for the easy path (Tailscale, free LLM, no crypto)
- Share code with the running Console so design + auth surface is consistent

**Source:** `Project_mAIstro/specs/infra/S-139-setup-wizard.md` (269 lines)

## Decision

Port the setup wizard spec as a design reference. The wizard is a browser-first PWA served from a temporary localhost endpoint by the conductor binary at first run, sharing the same web UI codebase as the runtime Console.

### Wizard flow (12 steps)

1. **Name your conductor** — 3-32 chars, alphanumeric + hyphens. Flows into dashboard header, audit log, DID document, federation handshake.
2. **Generate Conductor Seed** (ADR-021) — BIP39 24-word phrase, displayed once, proof-of-write-down verification. Optional SLIP39 Shamir backup or hardware wallet (ADR-022).
3. **Create admin** — password + admin keypair derived from seed. Recovery card generation.
4. **Create user one** (REQUIRED, no skip) — enforces ADR-028 two-user invariant.
5. **Add more users** (optional) — 0..N additional household members.
6. **Network substrate** (ADR-029) — mesh / tunnel / local-only / manual.
7. **TLS mode** (ADR-026) — public-CA, local-CA, or both.
8. **LLM providers** — OAuth-first where possible, API-key-paste fallback. Keys flow into vault.
9. **Channels** (optional) — Telegram / voice / email / Obsidian inbox.
10. **Crypto features** (ADR-023, optional, default Skip) — Lightning, Bitcoin, bring-your-own-node.
11. **Smoke tests** — live verification of bouncer, capability envelopes, vault round-trip, audit VC, substrate reachability.
12. **Finalize** — summary page, redirect to substrate URL, temporary server shutdown.

### Key properties

- **Browser-first, CLI fallback** — `--cli` flag runs the same logic with a TUI presenter
- **Headless** — detects no DISPLAY, prints URL + token + SSH tunnel instructions
- **Resume** — state checkpointed after each step in `wizard-state.json` (vault-encrypted after step 3)
- **Idempotent** — re-running `maistro setup` on a configured conductor offers reconfigure or destructive reset
- **Sovereignty path** — all defaults can be deselected for zero outbound third-party traffic

## Interface (spec)

```python
class WizardState:
    step: int
    instance_name: str | None
    seed_generated: bool
    admin_created: bool
    users: list[UserInfo]
    substrate: SubstrateConfig | None
    tls_mode: TLSMode | None
    llm_providers: list[ProviderConfig]
    channels: list[ChannelConfig]
    crypto_mode: CryptoMode

class SetupWizard:
    def start(self, mode: Literal["browser", "cli"]) -> None: ...
    def resume(self, state_path: Path) -> WizardState: ...
    def run_smoke_tests(self) -> list[SmokeTestResult]: ...
    def finalize(self) -> FinalizeResult: ...
```

## Acceptance criteria

- [ ] Default-everything wizard completes in <5 min browser-first on fresh Linux with Tailscale
- [ ] All 12 steps render on Chromium, Firefox, Safari (desktop + mobile)
- [ ] Step 4 is structurally required — no skip possible
- [ ] Step 11 smoke tests run live with real pass/fail; failures block completion
- [ ] State persists across browser close + conductor crash
- [ ] CLI fallback walks the same flow with TUI presenter
- [ ] Sovereignty config: localhost + local-CA + local model + skip crypto = zero outbound HTTP
- [ ] After completion, browser auto-redirects to substrate URL

## Out of scope

- `.msi` / `.pkg` signing infrastructure (S-147 from source)
- Hardware-wallet WebUSB/HID browser integration (ADR-022 covers device protocol)
- Mobile-responsive wizard UI implementation (design spec only)
- Pre-built installer binaries

## Source references

- `~/maistro-engine/specs/infra/S-139-setup-wizard.md` — full 269-line spec
- Cross-references: S-016 (Console), S-138 (browser host), S-141 (vault), S-142 (privilege separation → ADR-028), S-147 (signed binaries), S-149 (seed → ADR-021), S-150 (hardware signing → ADR-022), S-151 (crypto → ADR-023), S-153 (substrate → ADR-029), S-155 (TLS → ADR-026)

## Links

- Source spec: S-139
- Related ADRs: ADR-021, ADR-022, ADR-023, ADR-026, ADR-028, ADR-029
