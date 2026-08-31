---
id: ADR-083026-cdcb
title: "A design project's org and team are soft scope axes, enforced at the store"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-068
  - maistro-engine#ADR-019
implements: []
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - packages/maistro-design/tests/test_project_scope.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-083026-cdcb: A design project's org and team are soft scope axes, enforced at the store

## Context

Migration 003 declared `design_projects.org_id` and `team_id` as foreign keys to
`orgs.id` and `teams.id`. No migration in this repository created either table,
so the whole chain rolled back at 003 and a fresh database ended with zero
tables (#177).

The repair for #177 created minimal `orgs` and `teams` tables inside 003 itself
so the keys would resolve. That made the chain apply. It did not make the
product work: nothing populates those tables, and the only `org_id` the Design
Studio ever supplies is the route's `"default-org"` fallback. Measured against
`develop` at `31c6102`, on a database freshly migrated to head:

```
maistro_test=> SELECT count(*) FROM orgs;
 0
maistro_test=> INSERT INTO design_projects (name, skill_slug, design_system_slug, org_id)
               VALUES ('probe','s','ds','default-org');
ERROR:  insert or update on table "design_projects" violates foreign key
        constraint "design_projects_org_id_fkey"
DETAIL:  Key (org_id)=(default-org) is not present in table "orgs".
```

"Schema cannot migrate" became "schema migrates but the product cannot write."

The FK was not enforcing an ownership model. It was enforcing membership in two
tables that exist only to be referenced — the placeholder shape #326 explicitly
rules out. Meanwhile the real scope leak on this surface went unchecked:
`GET /v1/design/projects/{id}` took no scope at all, so any authenticated
caller could read any org's project, and `update` and `delete` matched on id
alone.

## Decision

**`org_id` and `team_id` are soft scope identifiers, not references.** This is
what ADR-068 and the root `CLAUDE.md` already say — `global → org → team → user
→ agent → session` are scope axes in maistro-core; only the hard `tenant`
boundary is Stronghold's — and it is what every other table in this schema
already does. `learnings`, `episodes` and `outcomes` (001) and the three canvas
tables (002) all declare `org_id` as plain text with a `''` default and no
foreign key. `design_projects` was the sole exception.

So migration 024 drops both constraints and drops the `orgs` and `teams` tables
with them. Dropping them is the point: leaving two empty tables standing
invites the next migration to reference them again.

**A scope-less project is still refused, by something the product can satisfy.**
The FK is replaced with `CHECK (org_id <> '')`. The old constraint asked "is
this org a row in a table nothing writes"; the new one asks "did the caller name
a scope", which is a question with an answer. `team_id` stays nullable and
unchecked — a project need not belong to a team.

**Scope is enforced where scope is known: the store.** `get`, `update` and
`delete` now take the caller's `org_id` and match on it, and `create` refuses a
blank one. Out-of-scope reads return `None` rather than raising, so the route
answers 404: whether a project exists in another org is itself scoped
information, and a 403 would leak it.

**The Conductor's own org id is a named constant, not a literal.** The route
still prefers `request.state.org_id` when a deployment sets one. The fallback is
`CONDUCTOR_ORG_ID`, with the reason written beside it — the Agent Conductor is
single-org by construction, so one deployment-wide scope is the truth here, and
inventing a per-user org would be a tenancy model this repo has not decided.

## Consequences

### Positive
- An ordinary Design Studio project creation succeeds on a clean database. It
  could not before, on any database this repo provisions.
- One authenticated caller can no longer read, edit or delete another scope's
  design project.
- Two tables that existed only to be referenced are gone, so nothing reads as
  an ownership model that is not one.

### Negative / Trade-offs
- The database no longer refuses an `org_id` that names nothing. It never
  meaningfully did: the referenced table was always empty, so the constraint
  refused *every* value rather than the wrong ones.
- `get`, `update` and `delete` take an extra argument. Every caller is in this
  repository and every one of them already knows the scope.

### Neutral
- `downgrade` restores the tables and the keys, backfilling an `orgs` row for
  each distinct `org_id` present. The previous chain could not round-trip
  through this shape at all — re-adding a foreign key over existing rows fails
  without the backfill, and that is what made the old state untestable.
