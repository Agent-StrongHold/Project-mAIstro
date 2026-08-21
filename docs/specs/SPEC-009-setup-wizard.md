---
id: SPEC-009
title: "Setup wizard — browser-first install ceremony, CLI fallback, shares Console codebase"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-028
  - maistro-engine#ADR-021
implements:
  - maistro-engine#ADR-020
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: UserClient
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-009: Setup Wizard

See `blakematthews-dev/project_maistro` specs/infra/S-139-setup-wizard.md for full spec.

## Acceptance Criteria

- [ ] Default-everything wizard run completes in <5 minutes browser-first on a fresh Linux laptop with Tailscale already installed
- [ ] All 12 steps render correctly on Chromium, Firefox, Safari (desktop + mobile-responsive)
- [ ] Step 4 (Create user one) is structurally required — form does not advance without a name; verified by browser automation
- [ ] Step 11 smoke tests run live and display real pass/fail; failures block wizard completion with clear remediation steps
- [ ] Step 11 smoke test failure: conductor enters `SETUP_INCOMPLETE` mode (localhost-only); a `SMOKE_TEST_FAILED` dashboard banner names the failing test with remediation steps; operator can re-run via `maistro setup --retry-smoke-tests` without restarting the wizard; non-localhost connections enabled only after all five smoke tests pass
- [ ] Wizard state persists across browser close + reopen + conductor crash
- [ ] CLI fallback (`--cli`) walks the same logical flow with a TUI presenter
- [ ] Sovereignty configuration: localhost substrate + local-CA + local model + skip crypto produces a working conductor with zero outbound HTTP verifiable via tcpdump
- [ ] After wizard completion, browser auto-redirects to the substrate URL
