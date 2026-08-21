---
name: adr
description: Scaffold a new Architecture Decision Record in docs/adr/. Uses the date-based ADR-MMDDYY-XXXX ID scheme (per ADR-062026-9b30; sequential ADR-NNN is frozen) and the ADR-031 front-matter schema (validated by maistro-registry; registry CI is strict). Pass a short title as the argument, e.g. /adr graph-caching-strategy
disable-model-invocation: false
---

The user wants to create a new ADR. The argument is $ARGUMENTS (the short title/slug).

Front matter is machine-validated by maistro-registry (`extra = forbid` — unknown or missing fields fail), and registry CI runs strict (warnings are failures). Get it exactly right.

Steps:
1. Convert $ARGUMENTS to a kebab-case slug (lowercase, hyphen-separated). This is BOTH the filename
   slug and the input to the ID hash in step 2, so fix it first.
2. Generate a **date-based ID** per **ADR-062026-9b30**. Sequential `ADR-NNN` numbering is FROZEN —
   do NOT read the highest existing number and do NOT scan other PR branches. That scheme races
   whenever two PRs are open at once (PR #156/#157 both grabbed `ADR-100`); the date-based ID derives
   only from this record's own title + date, so concurrent PRs cannot collide. Format
   `ADR-MMDDYY-XXXX`:
   - `MMDDYY` = today's `created` date (e.g. 2026-06-21 → `062126`).
   - `XXXX` = `sha1(<kebab-slug>)[:4]` — 4 lowercase hex chars (disambiguates same-day records only).
   Compute both at once (substitute your slug):
   ```bash
   python3 -c "import hashlib,datetime; s='<kebab-slug>'; print(f'ADR-{datetime.date.today():%m%d%y}-{hashlib.sha1(s.encode()).hexdigest()[:4]}')"
   ```
   The id MUST match `^ADR-\d{6}-[0-9a-f]{4}$`.
3. Filename → `docs/adr/ADR-MMDDYY-XXXX-<kebab-slug>.md`.
4. Use today's date from the environment for `created` (YYYY-MM-DD). Do NOT guess.
5. Create the file with this template, filling in real values:

```markdown
---
id: ADR-MMDDYY-XXXX
title: "<one-line title>"
repo: maistro-engine
kind: adr
status: Proposed
created: <YYYY-MM-DD>
substrate: []        # ADRs/SPECs this builds on, e.g. maistro-engine#ADR-031
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []       # note: hyphen in YAML key
contracts: []        # any of: boundary, behavioral, cross-service
tests: []
layer: <Layer>       # one of: Foundation, Orchestration, Agents, Tools, Memory, Observability, Reliability, Governance, UserClient, Evolve, Crypto, Connectivity, Ability, Identity (last five per ADR-098)
owners:
  - '@BlakeMatthews-dev'
---

# ADR-MMDDYY-XXXX: <Title>

## Context

<What is the situation that motivates this decision?>

## Decision

<What is the change we're making?>

## Consequences

### Positive
-

### Negative / Trade-offs
-

### Neutral
-
```

6. After writing, validate it (if `python3 -m maistro_registry.cli` fails on a missing dependency,
   prefix with `uv run --no-sync --with pydantic --with pyyaml --with httpx`):
   ```bash
   PYTHONPATH=packages/maistro-registry/src python3 -m maistro_registry.cli validate docs/adr/ADR-MMDDYY-XXXX-<slug>.md
   ```
   Fix any reported errors before finishing.
7. Show the user the created file path and remind them to update the status (Proposed → Accepted) once agreed.
