---
id: SPEC-014
title: "LiteLLM free-tier auto-configuration — OAuth-first onboarding for the LLM hook"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-04-25
substrate:
  - maistro-engine#ADR-028
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests: []
layer: Agents
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-25
---

# SPEC-014: LiteLLM Free-Tier Auto-Configuration

See `blakematthews-dev/project_maistro` specs/infra/S-144-litellm-freetier.md for full spec.

## Acceptance Criteria

- [ ] Setup wizard offers 4 default free-tier providers; OAuth where supported, paste-API fallback elsewhere
- [ ] OAuth flows for Groq and OpenRouter complete in-browser without leaving the Console
- [ ] All API keys stored in the vault (SPEC-011); never written to disk in cleartext, never appear in litellm.yaml as a plaintext value
- [ ] LiteLLM routing prefers free-tier providers, falls back across them on rate-limit / outage, degrades gracefully when all are exhausted
- [ ] Sovereignty mode: configuration with zero external providers and one local OpenAI-compatible endpoint is fully supported and tested
- [ ] Bouncer screens LiteLLM responses; malicious tool-call sequences from any provider are caught
- [ ] OAuth token expiry: when an OAuth-issued API key expires or is revoked by a provider, conductor surfaces a `PROVIDER_AUTH_EXPIRED` alert on the dashboard naming the provider and offering a one-click re-authentication link; LiteLLM routing automatically excludes the expired provider and falls back to remaining configured providers immediately — expired credentials are not silently retried until they begin generating 401 errors
- [ ] Privacy disclosure: the setup wizard explicitly surfaces a "free providers may train on your prompts" warning before storing any external API keys; the warning includes a link to each selected provider's privacy policy; sovereignty mode (local-only) is presented as a clear alternative in the same screen
