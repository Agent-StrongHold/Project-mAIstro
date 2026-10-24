---
id: SPEC-223
title: "Secret redaction: pattern catalogue and entropy fallback"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate:
  - maistro-engine#ADR-064
implements:
  - maistro-engine#ADR-064
related:
  - maistro-engine#SPEC-080226-4c1f
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/security/test_redact.py
layer: Reliability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-223: Secret redaction: pattern catalogue and entropy fallback

## Context

Logs, error messages, and trajectory recordings could leak API keys, DB
connection strings, JWTs, and private keys verbatim whenever an
exception's string representation or a debug log line embedded raw
credential material. ADR-064 decided to ship a single `redact()` function
covering known secret shapes by regex plus a high-entropy fallback for
unknown key formats, so call sites only need one import to neutralize
leakage.

## Goals

- `redact(text: str) -> str`: strips known secret shapes (private keys, DB
  connection strings, auth headers, env-var assignments, query params,
  URL userinfo, AWS keys, JWTs, known provider API-key prefixes) and
  replaces each with a labeled placeholder (e.g. `[REDACTED_API_KEY]`).
- An entropy heuristic (`_looks_like_secret`) that catches unknown
  32+ char high-entropy, mixed-case-and-digit tokens that don't match any
  named pattern, replacing them with `[REDACTED_HIGH_ENTROPY]`.
- Span-merging substitution so overlapping pattern matches don't leave
  partial fragments or get redacted twice.

## Non-goals

- Wiring `redact()` into logging handlers, error-message formatting, or
  trajectory recording — these integration points are explicitly tracked
  separately per ADR-064 and are not implemented by this module.
  **No such tracking artifact was ever created**, so for the whole life of this
  module `redact()` had zero production callers while `SECURITY.md` and
  `COMPLIANCE.md` described it as an operative control. That is now closed by
  [SPEC-080226-4c1f](SPEC-080226-4c1f-log-redaction-wiring.md), which installs it
  on both log pipelines; this SPEC's own scope is unchanged.
- A runtime on/off toggle — the implemented module always redacts; there
  is no `is_redaction_enabled()` / `_REDACT_ENABLED` flag as sketched in
  ADR-064's interface section.

## Decision

`packages/maistro-core/src/maistro/security/redact.py`:

```python
_PATTERNS: list[tuple[re.Pattern[str], str]] = [...]  # private keys, DB conn strings,
    # auth headers, env-var assignments, query params, URL userinfo,
    # AWS keys, JWTs, known API-key prefixes (sk-, ghp_, AIza, xoxb-, etc.)

_HIGH_ENTROPY_RE: re.Pattern[str]

def _shannon_entropy(s: str) -> float: ...
def _looks_like_secret(s: str) -> bool: ...
def redact(text: str) -> str: ...
```

`redact()` collects all pattern matches plus high-entropy-token matches
as `(start, end, replacement)` spans, sorts by start position (longest
match wins on overlap), merges overlapping spans, then builds the
redacted string in a single pass — avoiding the order-dependent
sequential-`re.sub` bug where an earlier substitution could partially
consume or duplicate-redact a later pattern's match. Auth-header and
`Bearer`/`Basic`/`Token` patterns are anchored to header-assignment
context (preceded by `:`/`=` or at line start) so they don't fire on
ordinary prose containing those words.

## Acceptance criteria

- [x] `redact()` replaces each known secret shape with a distinct
      `[REDACTED_*]` label
- [x] Auth-header / bearer-token patterns are anchored to assignment
      context, not bare prose
- [x] Overlapping pattern matches are merged so the longer match wins,
      with no partial-fragment leakage
- [x] An entropy-based fallback redacts unknown 32+ char high-entropy
      tokens with mixed case and digits
- [ ] `is_redaction_enabled()` / `_REDACT_ENABLED` toggle, and the
      logging/error-message/trajectory integration points described in
      ADR-064 — not implemented; `redact()` exists as a standalone
      function with no call-site wiring yet

## Testing

Covered by `packages/maistro-core/tests/security/test_redact.py`.

## Open questions

- Whether/when `redact()` gets wired into logging handlers, error
  formatting, and trajectory recording remains open — ADR-064 explicitly
  tracks these as separate follow-up work.
- Whether a redaction on/off toggle is still wanted, given the current
  module always redacts unconditionally.

## References

- [ADR-064: Secret redaction](../adr/ADR-064-secret-redaction.md)
- `packages/maistro-core/src/maistro/security/redact.py`
