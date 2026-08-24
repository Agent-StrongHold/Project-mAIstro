---
name: spec
description: Scaffold a new SPEC design doc in docs/specs/. Produces strict front matter validated by maistro-registry (id, title, repo, kind, status, created, lifecycle history, layer, owners, relationships). Pass a short title as the argument, e.g. /spec capability-budgeting
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
4. Use today's date from the environment for `created` and the initial history entry (YYYY-MM-DD). Do NOT guess.
5. Write the file with this exact front-matter shape, filling in real values:

```markdown
---
id: SPEC-MMDDYY-XXXX
title: "<one-line title>"
repo: maistro-engine
kind: spec
status: Proposed
created: <YYYY-MM-DD>
history:
  - status: Proposed
    date: <YYYY-MM-DD>
substrate: []        # ADRs/SPECs this builds on, e.g. maistro-engine#ADR-031
implements: []       # ADRs this realizes
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

-

## Testing

<How this is verified — unit, integration, formal invariants.>

## Open questions

-

## References

-
```

Field rules (enforced by the schema and ADR-097 lifecycle linter):
- New specs start `Proposed`. Valid SPEC lifecycle states are `Proposed`, `Deferred`, `Will Not Implement`, `Accepted`, `AC Defined`, `In Progress`, `Tests Passing`, `Implemented`, `Superseded`, and `Deprecated`; transitions follow ADR-097.
- Every new document includes append-only `history`; every transition entry has an ISO date, and front-matter `status` matches the latest history entry.
- Taken states require `accepted` plus at least one owner. `Implemented` additionally requires `implemented`. When an `Accepted` or `Implemented` transition is present, its history date must match the corresponding metadata date.
- `layer` ∈ {Foundation, Orchestration, Agents, Tools, Memory, Observability, Reliability, Governance, UserClient, Evolve, Crypto, Connectivity, Ability, Identity}. Scope definitions for the last five are in ADR-098. Pick the best fit; ask the user if unclear.
- `contracts` entries ∈ {boundary, behavioral, cross-service}.
- Cross-references use the form `maistro-engine#<ID>`, where `<ID>` is either a legacy
  `ADR-NNN`/`SPEC-NNN` (for the ~150 records that predate the freeze) or a date-based
  `ADR-MMDDYY-XXXX`/`SPEC-MMDDYY-XXXX`. Both are accepted by the schema; reference targets by
  whatever ID they actually carry.
- Empty lists are valid; omit no keys required by the scaffold.

6. After writing, validate it (if `python3 -m maistro_registry.cli` fails on a missing dependency,
   prefix with `uv run --no-sync --with pydantic --with pyyaml --with httpx`):
   ```bash
   PYTHONPATH=packages/maistro-registry/src python3 -m maistro_registry.cli validate docs/specs/SPEC-MMDDYY-XXXX-<slug>.md
   ```
   Fix any reported errors before finishing.
7. Show the user the created path. When the design is agreed, advance it through ADR-097 rather than editing `status` alone: append the dated history transition and add the required lifecycle metadata (`accepted`, and later `implemented`) at the same time.
