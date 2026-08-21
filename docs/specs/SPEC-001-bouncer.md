---
id: SPEC-001
title: "Bouncer — security screening (20+ regex + LLM)"
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-02-25
accepted: 2026-02-25
implemented: 2026-03-23
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
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-02-25
  - status: Accepted
    date: 2026-02-25
  - status: AC Defined
    date: 2026-03-23
---

# SPEC-001: Bouncer

Pre-execution security screen: 20+ regex patterns for injection/exfil/prompt-attack patterns, negative LLM pass for ambiguous cases. Blocks non-recoverable `TOOL_VIOLATION` and `SAFETY_VIOLATION` errors.

## Key files
- `conductor/orchestrator/agents/bouncer.py`

## warden.file_scan()

File attachments entering conductor via any channel (email, MCP, A2A) pass through a multi-stage analysis pipeline before their content touches any agent context. The pipeline's only job is routing content to Warden with the correct trust label — Warden makes all judgment calls. The only hard blocks at the file-analysis layer are structural integrity failures (magic bytes mismatch) and resource-exhaustion risks (zip bombs).

### Stage 1: Magic bytes vs. declared extension

Read the first 16 bytes of the file. Compare against a map of known magic-byte signatures (PDF `%PDF-`, ZIP `PK\x03\x04`, PNG `\x89PNG`, JPEG `\xFF\xD8\xFF`, etc.).

- **Match**: proceed to Stage 2.
- **Mismatch**: **hard block** — log `FILE_INTEGRITY_VIOLATION`, reject the file.

### Stage 2: Hidden ZIP scan

Scan the entire file for the ZIP local-file header magic bytes (`PK\x03\x04`) at any byte offset beyond the expected location.

- **Not found**: proceed to Stage 3.
- **Found at unexpected offset**: recurse through Stage 1–5 for each entry; label entire file **untrusted** → Warden scan.

### Stage 3: File size mismatch

- **Extreme compression ratio** (uncompressed > 1 GB or ratio > 1000:1): **hard block** — log `ZIP_BOMB_DETECTED`.
- **Excess bytes**: label the file **untrusted** → Warden scan.

### Stage 4: strings extraction

- **Non-text-carrier file type** (PNG, JPEG, BMP, WAV): strings labeled **untrusted** → Warden scan.
- **Text-carrier file type** (PDF, HTML, DOCX, plain text): proceed to Stage 5.

### Stage 5: Parser vs. strings diff (text-carrier only)

- **Strings output is a subset of parser output**: pass to Warden with **standard trust label**.
- **Strings output contains content not in parser output**: diff content labeled **untrusted** → Warden scan.

### Trust label routing summary

| Condition | Label | Action |
|---|---|---|
| Magic bytes mismatch | — | Hard block (`FILE_INTEGRITY_VIOLATION`) |
| Zip bomb | — | Hard block (`ZIP_BOMB_DETECTED`) |
| Clean file (all stages pass) | standard | Warden scan (standard path) |
| Hidden ZIP detected | untrusted | Warden scan (elevated scrutiny) |
| File size excess bytes | untrusted | Warden scan (elevated scrutiny) |
| Non-text-carrier strings | untrusted | Warden scan (elevated scrutiny) |
| Parser vs. strings diff | untrusted | Warden scan (elevated scrutiny) |

### Key files
- `conductor/orchestrator/agents/warden_file_scan.py` (new)
- `conductor/orchestrator/agents/bouncer.py` (wire `file_scan()` into attachment handling)

## Acceptance Criteria

- **AC-1**: 20+ regex patterns detect injection, exfiltration, and prompt-attack patterns and raise `TOOL_VIOLATION` or `SAFETY_VIOLATION`.
- **AC-2**: Magic bytes mismatch between file header and declared extension raises `FILE_INTEGRITY_VIOLATION` hard block.
- **AC-3**: ZIP bomb detection (ratio > 1000:1 or uncompressed > 1 GB) raises `ZIP_BOMB_DETECTED` hard block.
- **AC-4**: Hidden ZIP at unexpected offset labels file as untrusted and routes to Warden scan.
- **AC-5**: Non-text-carrier file strings are labeled untrusted and routed to Warden scan.
- **AC-6**: Parser vs. strings diff on text-carrier files correctly identifies hidden content and labels it untrusted.
- **AC-7**: Clean files passing all stages are routed to Warden with standard trust label.
