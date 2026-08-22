---
id: SPEC-082126-3c9d
title: PII Evasion Normalization
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-08-21
history:
  - status: Proposed
    date: 2026-08-21
  - status: Implemented
    date: 2026-08-21
substrate:
  - maistro-engine#ADR-073
implements:
  - maistro-engine#ADR-073
related:
  - maistro-engine#ADR-072
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/sentinel/test_pii_evasion_normalization.py
  - packages/maistro-core/tests/security/sentinel/test_pii_filter_properties.py
ac-modules:
  AC-1: maistro.security.sentinel.pii_filter
  AC-2: maistro.security.sentinel.pii_filter
  AC-3: maistro.security.sentinel.pii_filter
  AC-4: maistro.security.sentinel.pii_filter
source:
  - SECURITY.md
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-082126-3c9d: PII Evasion Normalization

## Purpose

Make Sentinel's PII/secret redaction resistant to the same cheap representation mismatches Warden already treats as hostile: Unicode compatibility forms, invisible characters, visually confusable letters, and common percent/Base64 encodings.

The control must not solve evasion by globally rewriting user-visible non-Latin text or by flagging content merely because it looks encoded.

## Decision

PII filtering uses one canonical redaction string and additional detection-only views:

1. **Canonical view:** NFKD compatibility decomposition followed by invisible-character stripping. Match offsets and all returned redacted text use this view.
2. **Homoglyph detection view:** the canonical view with the shared curated Cyrillic/Greek confusable map folded to Latin. The map is one-code-point-to-one-code-point, so matches map directly back to canonical offsets. The folded text is never returned to the user.
3. **Percent-decoded candidate view:** percent-bearing token candidates are UTF-8 decoded for detection. They become findings only if decoded content satisfies an existing PII/secret detector and validator; redaction replaces the original encoded candidate span.
4. **Base64/Base64URL candidate view:** token-like candidates are decoded for detection. They become findings only if decoded UTF-8 content satisfies an existing detector and validator; redaction replaces the original encoded candidate span.

Existing specificity/false-positive validators remain authoritative, including Luhn validation, never-issued SSN ranges, and the deliberate E.164-only phone scope.

Current applicable runtime output paths already converge on `scan_and_redact`: DirectStrategy model output, ReactStrategy tool-result sanitation when Sentinel is unavailable, and Sentinel post-call processing. The normalized/evasion-resistant implementation therefore applies at those call sites without a second filter implementation.

## Acceptance Criteria

```gherkin
Feature: Normalized PII and secret filtering

  @AC-1
  Scenario: Canonical Unicode normalization defeats compatibility and invisible evasions
    Given a secret written with compatibility characters or inserted invisible characters
    When the PII filter scans it
    Then the secret is detected
    And the returned redaction uses one deterministic canonical text representation

  @AC-2
  Scenario: Common representation evasions do not hide real PII
    Given a real PII or secret value hidden with a supported homoglyph, percent encoding, Base64, or Base64URL representation
    When the PII filter scans it
    Then the existing detector identifies its real PII family
    And redaction removes the original evasion-bearing span

  @AC-3
  Scenario: Detection views do not create generic encoding or non-Latin false positives
    Given ordinary non-Latin prose, harmless encoded data, or data rejected by an existing PII validator
    When the PII filter scans it
    Then it is not flagged merely because a detection view exists
    And repeated redaction is deterministic and idempotent

  @AC-4
  Scenario: Applicable runtime output paths use the hardened filter
    Given PII hidden by a supported evasion in DirectStrategy output, ReactStrategy tool output, or Sentinel post-call output
    When each path returns content
    Then the evasion-bearing value is redacted before it leaves that path
```

## Non-goals

- Detecting names, postal addresses, dates of birth, or unsupported national identifiers.
- Treating arbitrary encoded/binary content as PII without a decoded detector match.
- Globally replacing homoglyphs in user-visible output.
- Replacing Warden threat detection or log-secret redaction.
