---
id: ADR-064
title: Comprehensive Secret Redaction
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
  AC-1: maistro.security.redact
  AC-2: maistro.security.redact
  AC-3: maistro.security.redact
  AC-4: maistro.security.redact
  AC-5: maistro.security.redact
  AC-6: maistro.security.redact
  AC-7: maistro.security.redact
  AC-8: maistro.security.redact
  AC-9: maistro.security.redact
  AC-10: maistro.security.redact
  AC-11: maistro.security.redact
  AC-12: maistro.security.redact
  AC-13: maistro.security.redact
  AC-14: maistro.security.redact
  AC-15: maistro.security.redact
  AC-16: maistro.security.redact
  AC-17: maistro.security.redact
  AC-18: maistro.security.redact
  AC-19: maistro.security.redact
  AC-20: maistro.security.redact
  AC-21: maistro.security.redact
  AC-22: maistro.security.redact
  AC-23: maistro.security.redact
  AC-24: maistro.security.redact
  AC-25: maistro.security.redact
  AC-26: maistro.security.redact
  AC-27: maistro.security.redact
  AC-28: maistro.security.redact
  AC-29: maistro.security.redact
  AC-30: maistro.security.redact
  AC-31: maistro.security.redact
  AC-32: maistro.security.redact
  AC-33: maistro.security.redact
  AC-34: maistro.security.redact
  AC-35: maistro.security.redact
  AC-36: maistro.security.redact
  AC-37: maistro.security.redact
  AC-38: maistro.security.redact
  AC-39: maistro.security.redact
  AC-40: maistro.security.redact
  AC-41: maistro.security.redact
  AC-42: maistro.security.redact
  AC-43: maistro.security.redact
  AC-44: maistro.security.redact
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-20
  - status: Accepted
    date: 2026-05-20
---

# ADR-064: Comprehensive Secret Redaction

**Status:** Accepted
**Date:** 2026-05-20
**Tranche:** T3
**Depends on:** IMP-050

---

## Context

The conductor-router logs full request/response bodies including API keys. Benchmark
runners log LLM responses that may contain leaked credentials from training data. Agent
trajectory recordings persist every intermediate result to disk. None of these outputs
are scrubbed. API keys, tokens, private keys, and connection strings appear verbatim in
log files, error messages, and on-disk recordings.

This is the single highest-impact security gap in the platform. Both Hermes and OpenClaw
independently built comprehensive regex-based redaction for exactly this reason. Our
existing `maistro.security.patterns.py` covers dangerous commands and prompt injection —
nothing covers secret leakage.

**Requirements from IMP-050:**

- 30+ regex patterns covering: API key prefixes (`sk-`, `ghp_`, `AIza`, `xoxb-`,
  `pplx-`), ENV assignments (`KEY=value`), JSON sensitive field values, Authorization
  headers, Telegram bot tokens, private key blocks, database connection strings, JWTs,
  URL userinfo, URL query parameters that look like keys
- Applied to all log output, error messages, and trajectory recordings
- Replacement text is the pattern name in brackets, e.g. `[REDACTED_API_KEY]`
- Must handle multi-line content
- Must be safe for nested patterns (e.g. a URL inside a JSON value)
- Performance matters — this runs on every log line
- `_REDACT_ENABLED` flag snapshot at import time to prevent runtime bypass

## Decision

Introduce `maistro.security.redact` — a new module in the existing security package.
Single public function `redact(text: str) -> str` plus a pre-compiled composite regex
for one-pass matching.

### 1. Pattern catalogue

All patterns are compiled once at module import into a single `re.Pattern` using
alternation (`|`). Each alternative is a named group so the match tells us which
pattern fired. The catalogue lives in `_PATTERNS: list[tuple[str, re.Pattern[str]]]`
as `(name, compiled)` pairs for documentation; the composite is derived from it.

**Pattern families and names:**

| # | Name | What it catches | Example |
|---|------|-----------------|---------|
| 1 | `API_KEY_OPENAI` | `sk-` followed by 20+ alphanumerics | `sk-proj-abc...` |
| 2 | `API_KEY_GITHUB` | `ghp_` followed by 36 chars | `ghp_ABC...` |
| 3 | `API_KEY_GOOGLE` | `AIza` followed by 30+ chars | `AIzaSyA...` |
| 4 | `API_KEY_SLACK` | `xoxb-` followed by 10+ chars | `xoxb-1234-...` |
| 5 | `API_KEY_PERPLEXITY` | `pplx-` followed by 20+ chars | `pplx-abc...` |
| 6 | `API_KEY_ANTHROPIC` | `sk-ant-` followed by 20+ chars | `sk-ant-api03-...` |
| 7 | `API_KEY_STRIPE` | `sk_live_` / `sk_test_` followed by 20+ chars | `sk_live_abc...` |
| 8 | `API_KEY_AWS` | `AKIA` followed by 16 alphanumerics | `AKIAIOSFODNN7EXAMPLE` |
| 9 | `TELEGRAM_BOT_TOKEN` | `\d{8,10}:[a-zA-Z0-9_-]{35}` | `123456789:AAH...` |
| 10 | `PRIVATE_KEY_BLOCK` | `-----BEGIN (RSA \|EC \|DSA \|OPENSSH )?PRIVATE KEY-----` through `-----END` | PEM blocks |
| 11 | `JWT` | `eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+` | `eyJhbG...` |
| 12 | `AUTH_HEADER` | `Authorization:\s*(Bearer\|Basic)\s+\S+` | `Authorization: Bearer abc...` |
| 13 | `DB_CONNECTION_STRING` | `postgres(ql)?://[^:]+:[^@]+@` and similar for mysql, mongodb, redis | `postgres://user:pass@host` |
| 14 | `URL_USERINFO` | `https?://[^/\s:]+:[^/\s@]+@` | `https://user:pass@host` |
| 15 | `URL_QUERY_KEY` | `[?&](api_key\|apikey\|token\|secret\|password\|access_token\|private_key)=\S+` in URLs | `?api_key=abc...` |
| 16 | `ENV_ASSIGNMENT` | `(?<=\s)([A-Z_]{3,}(?:KEY\|TOKEN\|SECRET\|PASSWORD\|PASSWD\|CREDENTIAL\|AUTH))=(\S+)` | `API_KEY=abc...` |
| 17 | `JSON_SENSITIVE_VALUE` | `"(api_key\|apikey\|token\|secret\|password\|passwd\|private_key\|access_token\|credential)"\s*:\s*"[^"]*"` | `{"api_key": "abc"}` |
| 18 | `GENERIC_TOKEN` | `(token\|bearer)\s*[:=]\s*["']?[a-zA-Z0-9._-]{20,}["']?` | `token: abc...` |
| 19 | `SENTRY_DSN` | `https://[a-f0-9]+@o\d+\.ingest\.sentry\.io/\d+` | Sentry DSNs |
| 20 | `HEROKU_API_KEY` | `[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}` in context of `heroku` | Heroku tokens |

Additional patterns (21–30+) cover: `twilio_key`, `sendgrid_key`, `mailgun_key`,
`azure_connection_string`, `gcp_service_account` (entire JSON block), `slack_webhook`,
`discord_webhook`, `github_oauth_access_token` (`gho_`), `npm_token` (`npm_`),
`pypi_token` (`pypi-`), `docker_pat` (`dckr_pat_`). The full catalogue is defined in
the `_PATTERNS` list and is the single source of truth.

### 2. Composite regex construction

Rather than running 30+ individual regex passes (O(30n)), all patterns are combined
into one alternation regex at import time:

```python
_composite: re.Pattern[str] = re.compile(
    "|".join(f"(?P<{name}>{pat.pattern})" for name, pat in _PATTERNS),
    re.MULTILINE | re.DOTALL,
)
```

The single-pass approach means each character is examined at most once by the regex
engine. Named groups identify which pattern matched.

### 3. Replacement strategy

The `_replacement_map` maps group name → replacement label:

```python
_REPLACEMENT_MAP: dict[str, str] = {
    "API_KEY_OPENAI": "[REDACTED_API_KEY]",
    "API_KEY_GITHUB": "[REDACTED_API_KEY]",
    # ... all groups map to their family label
    "JWT": "[REDACTED_JWT]",
    "PRIVATE_KEY_BLOCK": "[REDACTED_PRIVATE_KEY]",
    "DB_CONNECTION_STRING": "[REDACTED_DB_CONNECTION]",
    "URL_USERINFO": "[REDACTED_URL_CREDENTIALS]",
    # etc.
}
```

The `_replace` callback looks up the last-matching named group and returns the label.
If multiple groups somehow match (they can't with leftmost-longest alternation, but
defensively), the first wins.

### 4. Nested pattern safety

All patterns are designed to consume the **entire** secret span in a single match:

- Private key blocks match from `-----BEGIN` through `-----END` (greedy but bounded).
- URLs with userinfo match the full `scheme://user:pass@host` segment.
- JSON values match `"key": "value"` including both key and value.

Because the composite regex is a single alternation, the leftmost-longest match wins.
A JWT embedded in a JSON value will be consumed by the JSON pattern first (if the key
name is sensitive) or by the JWT pattern (if it appears in a non-sensitive context).
Either way, the full span is replaced — there is no partial exposure.

For the rare case where a pattern could partially overlap with another (e.g. an API key
inside a URL query param), the `_replace` callback runs on the full composite match,
so the entire matched span is atomically replaced. No residual fragments leak.

### 5. Multi-line handling

The composite regex is compiled with `re.MULTILINE | re.DOTALL`:

- `re.DOTALL` allows `.` to match newlines — critical for private key blocks and
  multi-line JSON.
- `re.MULTILINE` allows `^` / `$` to match line boundaries — used by ENV assignment
  and header patterns.

`redact()` accepts the full text as a single string and operates on it in one call.
Callers should not pre-split by line.

### 6. Public interface

```python
from maistro.security.redact import redact, is_redaction_enabled

def redact(text: str | None) -> str:
    """Redact all known secret patterns from text.

    Returns the input unchanged if text is None/empty or if
    redaction is disabled via the REDACT_ENABLED=false env var.
    Never raises.
    """
    ...

def is_redaction_enabled() -> bool:
    """Return whether redaction is active. Snapshotted at import time."""
    ...
```

### 7. Import-time snapshot

```python
import os

_REDACT_ENABLED: bool = os.environ.get("REDACT_ENABLED", "true").lower() not in (
    "false", "0", "no",
)
```

This is read once at import. Setting `REDACT_ENABLED=false` at runtime has no effect
unless the module is re-imported. This prevents a compromised agent from disabling
redaction by mutating `os.environ`.

### 8. Integration points

`redact()` is called at three trust boundaries:

1. **Logging** — the `maistro.observability` log formatter wraps every emitted message
   through `redact()` before rendering.
2. **Error messages** — `AgentError` and `MaistroError` pass their `detail` string
   through `redact()` in `__str__`.
3. **Trajectory recordings** — the graph executor (ADR-062) calls `redact()` on the
   `NodeRun.to_result()` output before persisting.

These are three separate integration points, not part of this ADR's implementation
scope. This ADR delivers the `redact()` function; the integration is tracked in
separate IMP items.

### 9. Performance guarantees

- Single-pass regex: O(n) where n is input length. No backtracking because patterns
  are ordered from most-specific to least-specific and avoid unbounded quantifiers
  on ambiguous character classes.
- No dynamic compilation — regex is pre-compiled at module import.
- Short-circuit: if `_REDACT_ENABLED` is `False`, `redact()` returns immediately
  without touching the regex engine.
- `redact("")` and `redact(None)` return immediately — no regex work.
- Benchmark target: <100μs for a typical 1KB log line (measured in tests).

## Consequences

**Positive:**

- All 30+ known secret patterns are scrubbed from logs, errors, and trajectory
  recordings with zero caller effort after integration.
- Pattern-based detection catches secrets from providers we don't currently use —
  not limited to keys we know about.
- Single-pass regex avoids performance degradation on high-throughput logging paths.
- Import-time flag snapshot prevents runtime bypass by compromised agents.

**Negative:**

- False positives are possible: a string like `sk-proj-my-test-value` in test output
  will be redacted. The `REDACT_ENABLED` escape hatch exists for debugging.
- Pattern catalogue requires maintenance as new providers and key formats emerge.
  Adding a pattern is a one-line change to `_PATTERNS`.
- Very long inputs (megabytes) still incur a full-pass scan. The benchmark target
  and short-circuit paths mitigate this for normal usage.
- Redaction labels are lossy — the original secret type (OpenAI vs GitHub) is not
  distinguishable in the output by default. This is intentional: logs should not
  reveal which provider's key leaked.

## Out of scope

- Context-aware redaction (e.g., redact only in log context, not in HTTP response
  bodies sent to clients). Callers decide when to invoke `redact()`.
- Structured logging integration (automatic redaction of JSON log fields). Covered
  by the observability integration point.
- Secret rotation or revocation triggered by detection. Out of scope for redaction.
- PII redaction (names, emails, SSNs). Separate concern, separate module.
- Entropy-based heuristic detection (e.g., detecting high-entropy strings without
  known prefixes). Future enhancement if pattern coverage proves insufficient.

## File layout

```
maistro/security/
├── __init__.py              # Updated: export redact
├── redact.py                # NEW: redact(), is_redaction_enabled(), pattern catalogue
├── patterns.py              # Existing: dangerous commands, injection (unchanged)
├── warden/                  # Existing (unchanged)
├── sentinel/                # Existing (unchanged)
└── ...                      # Other existing modules (unchanged)
```

## Source references

- `docs/analysis/COMPETITIVE-IMPROVEMENTS.md` — IMP-050 definition, lines 1236–1256
- `maistro/security/patterns.py` — existing pattern data (style reference)
- Hermes secret redaction module — pattern-based approach
- OpenClaw secret scrubber — pattern-based approach
- OWASP Agentic Top 10 — "Sensitive Data Disclosure" risk category

## Links

- PR: (pending)
- Issue: IMP-050
- Follow-up ADRs: observability integration (logging formatter), trajectory integration

---

## Gherkin acceptance criteria

> **Measurement note (2026-08-20).** All 44 scenarios are tagged `@AC-N`,
> measured by `scripts/check-ac-state.py`, and bound to passing tests over
> `maistro.security.redact`, which is reachable. The last nine closed in two
> steps: AC-35/36 got the ratio-based scaling benchmarks alongside the
> quadratic-pattern fixes, and the remaining catalogue gaps got their
> patterns — AC-12..14 (`[REDACTED_JSON_SECRET]`, whole `"name": "value"`
> pair consumed since the engine substitutes fixed strings), AC-25
> (username-only userinfo, and the label corrected to this ADR's
> `[REDACTED_URL_CREDENTIALS]`), AC-42 (Telegram bot tokens), AC-43 (Sentry
> DSNs — ordered above the userinfo pattern, which also matches a DSN;
> span-merge ties go to the earlier-listed pattern and this ADR requires the
> DSN label). AC-18 needed no code: `OPENSSH ` was already inside the
> private-key pattern's `[A-Z ]{0,32}` label prefix, now pinned by a test.

```gherkin
Feature: Comprehensive secret redaction
  As the maistro security layer
  I want to redact all known secret patterns from text
  So that secrets never appear in logs, errors, or trajectory recordings

  Background:
    Given the redact module is imported from "maistro.security.redact"
    And redaction is enabled

  # --- 1. API key prefix patterns ---

  @AC-1
  Scenario: OpenAI API key is redacted
    Given input text containing "api_key=sk-proj-abc123def456ghi789jkl012mno345"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "sk-proj-abc123"

  @AC-2
  Scenario: GitHub personal access token is redacted
    Given input text containing "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "ghp_ABCDE"

  @AC-3
  Scenario: Google API key is redacted
    Given input text containing "key=AIzaSyA1234567890abcdefghijklmnopqrstuv"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "AIzaSy"

  @AC-4
  Scenario: Slack bot token is redacted
    Given input text containing a Slack bot token pattern (xoxb- prefix followed by digits and chars)
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain the original token

  @AC-5
  Scenario: Perplexity API key is redacted
    Given input text containing "Authorization: Bearer pplx-abcdef1234567890abcdef123456"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "pplx-"

  @AC-6
  Scenario: Anthropic API key is redacted
    Given input text containing "sk-ant-api03-abcdefghijklmnopqrstuvwxyz1234567890"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "sk-ant-"

  @AC-7
  Scenario: Stripe live key is redacted
    Given input text containing a Stripe live key pattern (sk_live_ prefix followed by alphanumeric chars)
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain the original key

  @AC-8
  Scenario: AWS access key ID is redacted
    Given input text containing "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    When redaction is applied
    Then the output contains "[REDACTED_API_KEY]"
    And the output does not contain "AKIAIOSFODNN7"

  # --- 2. ENV assignment redaction ---

  @AC-9
  Scenario: ENV variable with sensitive name is redacted
    Given input text containing "export DATABASE_PASSWORD=hunter2"
    When redaction is applied
    Then the output contains "[REDACTED_ENV_SECRET]"
    And the output does not contain "hunter2"

  @AC-10
  Scenario: ENV assignment for API key is redacted
    Given input text containing "API_KEY=sk-proj-abc123def456ghi789"
    When redaction is applied
    Then the output does not contain "sk-proj-abc123"
    And the output contains "[REDACTED"

  @AC-11
  Scenario: ENV variable with non-sensitive name is preserved
    Given input text containing "export PATH=/usr/local/bin"
    When redaction is applied
    Then the output contains "PATH=/usr/local/bin"

  # --- 3. JSON sensitive field redaction ---

  @AC-12
  Scenario: JSON password field value is redacted
    Given input text containing '{"username": "admin", "password": "s3cret!", "role": "user"}'
    When redaction is applied
    Then the output contains "[REDACTED_JSON_SECRET]"
    And the output does not contain "s3cret!"
    And the output contains '"username": "admin"'

  @AC-13
  Scenario: JSON api_key field value is redacted
    Given input text containing '{"api_key": "sk-proj-1234567890abcdef", "model": "gpt-4"}'
    When redaction is applied
    Then the output contains "[REDACTED_JSON_SECRET]"
    And the output does not contain "sk-proj-"
    And the output contains '"model": "gpt-4"'

  @AC-14
  Scenario: JSON non-sensitive field is preserved
    Given input text containing '{"name": "agent-1", "status": "running"}'
    When redaction is applied
    Then the output contains '"name": "agent-1"'
    And the output contains '"status": "running"'

  # --- 4. Authorization header redaction ---

  @AC-15
  Scenario: Bearer token in Authorization header is redacted
    Given input text containing "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig"
    When redaction is applied
    Then the output contains "[REDACTED_AUTH_HEADER]"
    And the output does not contain "eyJhbG"

  @AC-16
  Scenario: Basic auth in Authorization header is redacted
    Given input text containing "Authorization: Basic dXNlcjpwYXNz"
    When redaction is applied
    Then the output contains "[REDACTED_AUTH_HEADER]"
    And the output does not contain "dXNlcjpwYXNz"

  # --- 5. Private key block redaction ---

  @AC-17
  Scenario: RSA private key block is redacted
    Given input text containing a multi-line RSA private key block starting with "-----BEGIN RSA PRIVATE KEY-----" and ending with "-----END RSA PRIVATE KEY-----"
    When redaction is applied
    Then the output contains "[REDACTED_PRIVATE_KEY]"
    And the output does not contain "BEGIN RSA PRIVATE KEY"
    And the output does not contain any base64 key data between the markers

  @AC-18
  Scenario: OpenSSH private key block is redacted
    Given input text containing "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64data\n-----END OPENSSH PRIVATE KEY-----"
    When redaction is applied
    Then the output contains "[REDACTED_PRIVATE_KEY]"
    And the output does not contain "base64data"

  # --- 6. Database connection string redaction ---

  @AC-19
  Scenario: PostgreSQL connection string with password is redacted
    Given input text containing "postgres://admin:hunter2@db.example.com:5432/mydb"
    When redaction is applied
    Then the output contains "[REDACTED_DB_CONNECTION]"
    And the output does not contain "hunter2"

  @AC-20
  Scenario: MySQL connection string with password is redacted
    Given input text containing "mysql://root:p@ssw0rd@localhost:3306/production"
    When redaction is applied
    Then the output contains "[REDACTED_DB_CONNECTION]"
    And the output does not contain "p@ssw0rd"

  @AC-21
  Scenario: MongoDB connection string with password is redacted
    Given input text containing "mongodb://user:s3cret@cluster.example.net/mydb"
    When redaction is applied
    Then the output contains "[REDACTED_DB_CONNECTION]"
    And the output does not contain "s3cret"

  # --- 7. JWT redaction ---

  @AC-22
  Scenario: JWT token is redacted
    Given input text containing "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    When redaction is applied
    Then the output contains "[REDACTED_JWT]"
    And the output does not contain "eyJhbG"

  @AC-23
  Scenario: JWT in Authorization header is redacted by auth header pattern
    Given input text containing "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.sig"
    When redaction is applied
    Then the output contains "[REDACTED"
    And the output does not contain "eyJhbG"

  # --- 8. URL userinfo redaction ---

  @AC-24
  Scenario: URL with username and password is redacted
    Given input text containing "https://admin:hunter2@api.example.com/v1/endpoint"
    When redaction is applied
    Then the output contains "[REDACTED_URL_CREDENTIALS]"
    And the output does not contain "admin:hunter2"

  @AC-25
  Scenario: URL with only username is redacted
    Given input text containing "https://admin@api.example.com/v1/endpoint"
    When redaction is applied
    Then the output contains "[REDACTED_URL_CREDENTIALS]"
    And the output does not contain "admin@"

  # --- 9. URL query parameter redaction ---

  @AC-26
  Scenario: URL with api_key query parameter is redacted
    Given input text containing "https://api.example.com/v1/endpoint?api_key=sk-proj-123456&format=json"
    When redaction is applied
    Then the output contains "[REDACTED_URL_PARAM]"
    And the output does not contain "sk-proj-"
    And the output contains "format=json"

  @AC-27
  Scenario: URL with token query parameter is redacted
    Given input text containing "https://oauth.example.com/callback?token=abc123def456&state=random"
    When redaction is applied
    Then the output contains "[REDACTED_URL_PARAM]"
    And the output does not contain "abc123def456"
    And the output contains "state=random"

  @AC-28
  Scenario: URL with non-sensitive query parameter is preserved
    Given input text containing "https://api.example.com/v1/endpoint?limit=100&offset=0"
    When redaction is applied
    Then the output contains "limit=100"
    And the output contains "offset=0"

  # --- 10. Multi-line content ---

  @AC-29
  Scenario: Multi-line text with secrets on different lines is fully redacted
    Given input text containing:
      """
      Config loaded:
      DATABASE_URL=postgres://admin:secret@db:5432/app
      API_KEY=sk-proj-abcdef123456
      Connected successfully.
      """
    When redaction is applied
    Then the output does not contain "secret"
    And the output does not contain "sk-proj-"
    And the output contains "Config loaded:"
    And the output contains "Connected successfully."

  @AC-30
  Scenario: Private key block spanning multiple lines is fully redacted
    Given input text containing:
      """
      Here is the key:
      -----BEGIN RSA PRIVATE KEY-----
      MIIEpAIBAAKCAQEA0Z3VS5JJcds3xfn/yGaTK...
      ZPwkY9tX3kF3wXHrWKBhJ5bHUmIg
      -----END RSA PRIVATE KEY-----
      Use it wisely.
      """
    When redaction is applied
    Then the output contains "[REDACTED_PRIVATE_KEY]"
    And the output does not contain "MIIEpAIB"
    And the output contains "Here is the key:"
    And the output contains "Use it wisely."

  # --- 11. Nested patterns ---

  @AC-31
  Scenario: API key inside JSON value is redacted without partial leakage
    Given input text containing '{"token": "sk-proj-abc123def456ghi789jkl012mno345pqr678"}'
    When redaction is applied
    Then the output does not contain "sk-proj-"
    And the output does not contain "abc123"
    And the output contains "[REDACTED"

  @AC-32
  Scenario: URL with credentials inside JSON field is redacted
    Given input text containing '{"connection_string": "postgres://admin:s3cret@db.example.com/app"}'
    When redaction is applied
    Then the output does not contain "s3cret"
    And the output does not contain "admin:s3cret@"

  @AC-33
  Scenario: URL with api_key query param containing an API key prefix is redacted
    Given input text containing "https://api.example.com?api_key=sk-proj-1234567890abcdef"
    When redaction is applied
    Then the output does not contain "sk-proj-"
    And the output does not contain "1234567890"

  @AC-34
  Scenario: JWT inside an Authorization header is fully consumed
    Given input text containing "Authorization: Bearer eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjMifQ.sig123"
    When redaction is applied
    Then the output does not contain "eyJhbG"
    And the output does not contain "sig123"
    And the output contains "[REDACTED_AUTH_HEADER]"

  # --- 12. Performance ---

  @AC-35
  Scenario: Redaction of a 1KB log line completes within 1ms
    Given a generated input text of 1024 bytes containing 3 embedded secrets
    When redaction is applied 100 times
    Then the total execution time is less than 100 milliseconds

  @AC-36
  Scenario: Redaction does not exhibit catastrophic backtracking on adversarial input
    Given input text containing 10000 repetitions of "sk-" followed by non-matching characters
    When redaction is applied
    Then the operation completes within 1 second
    And the process does not hang or exceed reasonable CPU usage

  # --- 13. Non-matching content passes through unchanged ---

  @AC-37
  Scenario: Plain text with no secrets is returned unchanged
    Given input text "The agent completed task #42 successfully in 3.2 seconds."
    When redaction is applied
    Then the output is exactly "The agent completed task #42 successfully in 3.2 seconds."

  @AC-38
  Scenario: Code snippet without secrets is returned unchanged
    Given input text containing:
      """
      def hello(name: str) -> str:
          return f"Hello, {name}!"
      """
    When redaction is applied
    Then the output is identical to the input

  @AC-39
  Scenario: URLs without credentials or sensitive params are preserved
    Given input text containing "https://api.example.com/v1/models?limit=50"
    When redaction is applied
    Then the output contains "https://api.example.com/v1/models?limit=50"

  # --- 14. Empty and None input handling ---

  @AC-40
  Scenario: Empty string returns empty string
    Given input text ""
    When redaction is applied
    Then the output is ""

  @AC-41
  Scenario: None input returns empty string
    Given input text is None
    When redaction is applied
    Then the output is ""

  # --- 15. Telegram bot token ---

  @AC-42
  Scenario: Telegram bot token is redacted
    Given input text containing "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    When redaction is applied
    Then the output contains "[REDACTED_TELEGRAM_TOKEN]"
    And the output does not contain "AAHdqTcvCH1"

  # --- 16. Sentry DSN ---

  @AC-43
  Scenario: Sentry DSN is redacted
    Given input text containing "https://abc123def456@o123456.ingest.sentry.io/789012"
    When redaction is applied
    Then the output contains "[REDACTED_SENTRY_DSN]"
    And the output does not contain "abc123def456"

  # --- 17. Multiple secrets in one string ---

  @AC-44
  Scenario: Multiple different secret types in one string are all redacted
    Given input text containing "key=sk-proj-abc123 and db=postgres://u:p@h/d and token=eyJhbGciOiJ9.eyJ.c2ln"
    When redaction is applied
    Then the output does not contain "sk-proj-"
    And the output does not contain "postgres://u:p@h"
    And the output does not contain "eyJhbG"
    And the output contains "[REDACTED_API_KEY]"
    And the output contains "[REDACTED_DB_CONNECTION]"
    And the output contains "[REDACTED_JWT]"
```

## Test plan

| Test | Type | Covers |
|------|------|--------|
| `test_redact_openai_key` | unit | API_KEY_OPENAI pattern |
| `test_redact_github_pat` | unit | API_KEY_GITHUB pattern |
| `test_redact_google_key` | unit | API_KEY_GOOGLE pattern |
| `test_redact_slack_token` | unit | API_KEY_SLACK pattern |
| `test_redact_perplexity_key` | unit | API_KEY_PERPLEXITY pattern |
| `test_redact_anthropic_key` | unit | API_KEY_ANTHROPIC pattern |
| `test_redact_stripe_key` | unit | API_KEY_STRIPE pattern |
| `test_redact_aws_key` | unit | API_KEY_AWS pattern |
| `test_redact_env_assignment` | unit | ENV_ASSIGNMENT pattern (sensitive names) |
| `test_preserve_env_non_sensitive` | unit | ENV_ASSIGNMENT does not over-match |
| `test_redact_json_password` | unit | JSON_SENSITIVE_VALUE pattern |
| `test_redact_json_token` | unit | JSON_SENSITIVE_VALUE pattern |
| `test_preserve_json_non_sensitive` | unit | JSON non-sensitive fields untouched |
| `test_redact_bearer_header` | unit | AUTH_HEADER Bearer |
| `test_redact_basic_header` | unit | AUTH_HEADER Basic |
| `test_redact_rsa_private_key` | unit | PRIVATE_KEY_BLOCK RSA |
| `test_redact_openssh_private_key` | unit | PRIVATE_KEY_BLOCK OpenSSH |
| `test_redact_postgres_connection` | unit | DB_CONNECTION_STRING PostgreSQL |
| `test_redact_mysql_connection` | unit | DB_CONNECTION_STRING MySQL |
| `test_redact_mongodb_connection` | unit | DB_CONNECTION_STRING MongoDB |
| `test_redact_jwt` | unit | JWT pattern |
| `test_redact_url_userinfo` | unit | URL_USERINFO pattern |
| `test_redact_url_query_api_key` | unit | URL_QUERY_KEY api_key param |
| `test_redact_url_query_token` | unit | URL_QUERY_KEY token param |
| `test_preserve_url_non_sensitive_params` | unit | URL query non-sensitive params preserved |
| `test_redact_telegram_bot_token` | unit | TELEGRAM_BOT_TOKEN pattern |
| `test_redact_sentry_dsn` | unit | SENTRY_DSN pattern |
| `test_redact_multiline` | unit | Multi-line content, all lines scrubbed |
| `test_redact_private_key_multiline` | unit | Private key spanning multiple lines |
| `test_nested_json_api_key` | unit | API key inside JSON value |
| `test_nested_url_in_json` | unit | Connection string inside JSON value |
| `test_nested_jwt_in_auth_header` | unit | JWT inside Authorization header |
| `test_nested_url_query_with_key_prefix` | unit | API key prefix inside URL query param |
| `test_multiple_secrets_one_string` | unit | All secret types redacted in single pass |
| `test_plain_text_unchanged` | unit | No false positives on plain text |
| `test_code_unchanged` | unit | No false positives on code |
| `test_url_without_secrets_unchanged` | unit | Clean URLs preserved |
| `test_empty_string` | unit | Empty string returns empty string |
| `test_none_returns_empty` | unit | None returns empty string |
| `test_performance_1kb` | benchmark | 1KB with 3 secrets < 1ms per call |
| `test_no_catastrophic_backtracking` | property | Adversarial input completes in time bound |
| `test_redact_disabled_flag` | unit | REDACT_ENABLED=false returns input unchanged |
| `test_flag_snapshot_at_import` | unit | Runtime env mutation has no effect |
