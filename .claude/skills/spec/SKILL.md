---
name: spec
description: Scaffold a new SPEC design doc in docs/specs/. Produces strict front matter validated by maistro-registry (id, title, repo, kind, status, created, layer, owners, relationships). Pass a short title as the argument, e.g. /spec capability-budgeting
disable-model-invocation: false
---

The user wants to create a new SPEC. The argument is $ARGUMENTS (the short title/slug).

Front matter is machine-validated by maistro-registry (`extra = forbid` — unknown or missing fields fail). Get it exactly right.

Steps:
1. Convert $ARGUMENTS to a kebab-case slug (lowercase, hyphen-separated). This is BOTH the filename
   slug and the input to the ID hash in step 2, so fix it first.
2. Generate a **date-based ID** per **ADR-062026-9b30**. Sequential `SPEC-NNN` numbering is FROZEN —
   do NOT read the highest existing number and do NOT scan other PR branches. That scheme races
   whenever two PRs are open at once (PR #156/#157 both grabbed `ADR-100`); the date-based ID derives
   only from this record's own title + date, so concurrent PRs cannot collide. Format
   `SPEC-MMDDYY-XXXX`:
   - `MMDDYY` = today's `created` date (e.g. 2026-06-21 → `062126`).
   - `XXXX` = `sha1(<kebab-slug>)[:4]` — 4 lowercase hex chars (disambiguates same-day records only).
   Compute both at once (substitute your slug):
   ```bash
   python3 -c "import hashlib,datetime; s='<kebab-slug>'; print(f'SPEC-{datetime.date.today():%m%d%y}-{hashlib.sha1(s.encode()).hexdigest()[:4]}')"
   ```
   The id MUST match `^SPEC-\d{6}-[0-9a-f]{4}$`.
3. Filename → `docs/specs/SPEC-MMDDYY-XXXX-<kebab-slug>.md`.
4. Use today's date from the environment for `created` (YYYY-MM-DD). Do NOT guess.
5. Write the file with this exact front-matter shape, filling in real values:

```markdown
---
id: SPEC-MMDDYY-XXXX
title: "<one-line title>"
repo: maistro-engine
kind: spec
status: Proposed
created: <YYYY-MM-DD>
substrate: []        # ADRs/SPECs this builds on, e.g. maistro-engine#ADR-031
implements: []       # ADRs this realizes -- REQUIRED to be non-empty (#164);
                     # a spec naming no ADR raises specs_implementing_nothing
related: []          # loosely related, e.g. maistro-engine#SPEC-184
supersedes: []
blocks: []
blocked-by: []       # note: hyphen in YAML key
contracts: []        # any of: boundary, behavioral, cross-service
tests: []
layer: <Layer>       # see valid values below (Evolve/Crypto/Connectivity/Ability per ADR-098)
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-MMDDYY-XXXX: <Title>

## Context

<What problem / situation motivates this spec?>

## Goals

-

## Non-goals

-

## Decision

<The design. Interfaces, data shapes, control flow.>

## Acceptance criteria

<REQUIRED (#164). A spec with no criteria raises `specs_owing_criteria` past
its ceiling and fails the AC ratchet. If this spec genuinely cannot be
measured -- a naming convention, a narrative, a decision record with no
runtime surface -- say so in the front matter instead:

    non-measurable: <why, in a sentence a reviewer can weigh>

That retires the debt; leaving the section empty does not. The schema
refuses an empty or token reason, and refuses the field on an ADR.>

-

## Testing

<How this is verified — unit, integration, formal invariants.>

## Open questions

-

## References

-
```

Field rules (enforced by the schema):
- `status` ∈ {Proposed, Accepted, Implemented, Superseded, Blocked, Abandoned} — new specs start `Proposed`.
- `layer` ∈ {Foundation, Orchestration, Agents, Tools, Memory, Observability, Reliability, Governance, UserClient, Evolve, Crypto, Connectivity, Ability, Identity}. Scope definitions for the last five are in ADR-098. Pick the best fit; ask the user if unclear.
- `contracts` entries ∈ {boundary, behavioral, cross-service}.
- Cross-references use the form `maistro-engine#<ID>`, where `<ID>` is either a legacy
  `ADR-NNN`/`SPEC-NNN` (for the ~150 records that predate the freeze) or a date-based
  `ADR-MMDDYY-XXXX`/`SPEC-MMDDYY-XXXX`. Both are accepted by the schema; reference targets by
  whatever ID they actually carry.
- Empty lists are valid; omit no keys (every field is required).

6. After writing, validate it (if `python3 -m maistro_registry.cli` fails on a missing dependency,
   prefix with `uv run --no-sync --with pydantic --with pyyaml --with httpx`):
   ```bash
   PYTHONPATH=packages/maistro-registry/src python3 -m maistro_registry.cli validate docs/specs/SPEC-MMDDYY-XXXX-<slug>.md
   ```
   Fix any reported errors before finishing.
7. Show the user the created path and remind them to flip `status: Proposed → Accepted` once agreed, and to fill `implements`/`tests` as work lands.
